from __future__ import annotations
from fastapi import APIRouter, UploadFile, File, HTTPException, Request
from pydantic import BaseModel, Field
import http.client, json, os, tempfile
from fastapi import Request


router = APIRouter(prefix="/nlp", tags=["nlp"])

# =========================
# Models
# =========================

class ParseReq(BaseModel):
    text: str = Field(..., description="Freitext, z.B. '80 g Hafer + 250 g Quark'")
    day: str | None = None
    meal_type: str | None = None  # breakfast|lunch|dinner|snack (optional, nur Metadaten)

class ParsedItem(BaseModel):
    name: str
    grams: float

class ParseResp(BaseModel):
    items: list[ParsedItem]
    confidence: float | None = None

class TranscribeResp(BaseModel):
    text: str
    language: str | None = None

class ParseFromAudioResp(BaseModel):
    text: str
    parsed: ParseResp


# =========================
# Ollama helpers
# =========================

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "127.0.0.1")
OLLAMA_PORT = int(os.getenv("OLLAMA_PORT", "11434"))
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")

def _http_post_json(host: str, port: int, path: str, payload: dict, timeout: int = 60) -> dict:
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    conn.request("POST", path, body=json.dumps(payload), headers={"Content-Type": "application/json"})
    res = conn.getresponse()
    data = res.read()
    if res.status != 200:
        raise HTTPException(status_code=503, detail=f"Ollama error {res.status}: {data.decode('utf-8','ignore')}")
    try:
        return json.loads(data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Ollama bad JSON: {e}")

def _strip_fences(s: str) -> str:
    """
    Entfernt typische Code-Fences (``` / ```json), Leading/Trailing Backticks/Spaces.
    """
    t = s.strip()
    if t.startswith("```"):
        t = t.strip("` \n\r")
        if t.lower().startswith("json"):
            t = t[4:].lstrip()
    # Heuristik: auf ersten '{' und letzten '}' beschneiden
    l = t.find("{")
    r = t.rfind("}")
    if l >= 0 and r > l:
        t = t[l:r+1]
    return t

def ollama_generate_raw(prompt: str, model: str = OLLAMA_MODEL) -> str:
    """Klassischer /api/generate Call (kein JSON erzwungen)."""
    data = _http_post_json(OLLAMA_HOST, OLLAMA_PORT, "/api/generate", {
        "model": model,
        "prompt": prompt,
        "stream": False
    })
    return data.get("response", "") or ""

def ollama_generate_json(prompt: str, model: str = OLLAMA_MODEL) -> dict:
    """
    Erzwungene JSON-Antwort: /api/generate mit format='json'.
    Falls das Modell trotzdem Fences liefert, werden diese entfernt.
    """
    data = _http_post_json(OLLAMA_HOST, OLLAMA_PORT, "/api/generate", {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1}
    })
    raw = data.get("response", "") or ""
    raw = _strip_fences(raw)
    try:
        return json.loads(raw)
    except Exception:
        # letzter Versuch: harte Klammer-Suche
        try:
            l = raw.find("{"); r = raw.rfind("}")
            if l >= 0 and r > l:
                return json.loads(raw[l:r+1])
        except Exception:
            pass
    raise HTTPException(status_code=500, detail="KI-Ausgabe nicht als JSON parsebar.")


# =========================
# Parse (Text -> Items)
# =========================

@router.post("/parse_meal", response_model=ParseResp)
def parse_meal(req: ParseReq):
    """
    Extrahiert aus deutschem Freitext (z.B. '80 g Hafer + 250 g Quark') strukturierte Items.
    Antwort wird strikt als JSON erzwungen; robust gegen Fences.
    """
    prompt = f"""
Du bist ein Parser. Extrahiere aus dem deutschen Text Lebensmittel mit Grammangaben.
Gib NUR JSON im Format:
{{"items":[{{"name":"...", "grams":123}}], "confidence":0.xx}}

Regeln:
- Verwende metrische Einheiten (g). Falls ml vorkommen, wandle 1 ml ≈ 1 g grob ab, außer es ist Öl (0.9 g/ml).
- Fasse gleichartige Angaben zusammen (z.B. "2x 30 g Mandeln" → 60 g).
- Runde Gramm auf ganze Zahlen.
- Keine Erklärtexte außerhalb des JSON.

Text:
{req.text}
"""
    try:
        data = ollama_generate_json(prompt)
    except HTTPException:
        # Fallback: non-JSON Modus + eigenständiges Parsen
        raw = ollama_generate_raw(prompt)
        raw = _strip_fences(raw)
        try:
            data = json.loads(raw)
        except Exception:
            data = {"items": [], "confidence": None}

    items = []
    for i in data.get("items", []):
        try:
            name = (i.get("name") or "").strip()
            grams = float(i.get("grams"))
        except Exception:
            continue
        if not name or grams <= 0:
            continue
        # harte Rundung, wie im Prompt gefordert
        items.append(ParsedItem(name=name, grams=round(grams)))

    return ParseResp(items=items, confidence=data.get("confidence"))


# =========================
# Komfort: Audio -> Parse (1 Call)
# =========================

@router.post("/parse_meal_audio", response_model=ParseFromAudioResp)
async def parse_meal_audio(file: UploadFile = File(...)):
    """
    Einfache Pipeline: Audio -> Transcribe -> Parse (gleicher Parser wie /parse_meal).
    """
    # 1) Transcribe
    tr = await transcribe(file)

    # 2) Parse
    parsed = parse_meal(ParseReq(text=tr.text))

    return ParseFromAudioResp(text=tr.text, parsed=parsed)


# =========================
# Transcribe (Audio -> Text)
# =========================

@router.post("/transcribe", response_model=TranscribeResp)
async def transcribe(request: Request, file: UploadFile | None = File(None)):
    """
    Akzeptiert:
    - multipart/form-data mit Feldname 'file' (UploadFile)
    - oder einen "rohen" Request-Body (application/octet-stream, audio/*),
      z.B. via PowerShell -InFile.
    """
    try:
        from faster_whisper import WhisperModel
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Faster-Whisper nicht installiert: {e}")

    # 1) Bytes beziehen (multipart ODER raw)
    raw_bytes: bytes | None = None
    filename_hint = None
    if file is not None:
        raw_bytes = await file.read()
        filename_hint = file.filename
    else:
        raw_bytes = await request.body()
        # Content-Type auslesen als Hint
        ct = request.headers.get("content-type", "")
        if not raw_bytes:
            raise HTTPException(status_code=400, detail="Kein Audio im Request-Body gefunden.")
        # primitive Dateiendungs-Vermutung
        if "audio/m4a" in ct or "audio/mp4" in ct:
            filename_hint = "upload.m4a"
        elif "audio/wav" in ct:
            filename_hint = "upload.wav"
        elif "audio/mpeg" in ct or "audio/mp3" in ct:
            filename_hint = "upload.mp3"
        else:
            filename_hint = "upload.wav"

    # 2) Bytes temporär speichern (Suffix anhand filename_hint)
    suffix = os.path.splitext(filename_hint or "")[1] or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(raw_bytes)
        tmp.flush()
        path = tmp.name

    # 3) Transkribieren
    try:
        model_name = os.getenv("WHISPER_MODEL", "small")
        device = os.getenv("WHISPER_DEVICE", "auto")
        model = WhisperModel(model_name, device=device, compute_type="int8")
        # Hinweis: Für m4a/mp3 braucht das System ffmpeg im PATH
        segments, info = model.transcribe(path, vad_filter=True, beam_size=1, language="de")
        text = " ".join([s.text.strip() for s in segments]).strip()
        return TranscribeResp(text=text, language=getattr(info, "language", None))
    finally:
        try:
            os.remove(path)
        except Exception:
            pass
