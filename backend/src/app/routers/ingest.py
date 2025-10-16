from fastapi import APIRouter, UploadFile, File, HTTPException, Query, Depends
from pydantic import BaseModel
from sqlmodel import Session
from datetime import date
import tempfile, os, http.client, json

from app.db import get_session
from app.models.foods import Food
from app.models.meals import Meal, MealItem, MealType
from faster_whisper import WhisperModel

router = APIRouter(prefix="/ingest", tags=["ingest"])

# global whisper model (re-use aus vorher)
whisper_model = WhisperModel("small", device="cpu", compute_type="int8")

# ---- Helper: call Ollama ----
def ollama_generate(prompt: str, model: str = "llama3.1") -> str:
    conn = http.client.HTTPConnection("127.0.0.1", 11434, timeout=60)
    body = json.dumps({"model": model, "prompt": prompt, "stream": False})
    conn.request("POST", "/api/generate", body=body, headers={"Content-Type": "application/json"})
    res = conn.getresponse()
    data = json.loads(res.read())
    return data.get("response", "")

# ---- Models ----
class VoiceMealResponse(BaseModel):
    text: str
    parsed: list[dict]
    saved_items: list[dict]


@router.post("/voice_meal", response_model=VoiceMealResponse)
async def voice_meal(
    file: UploadFile = File(...),
    day: date = Query(...),
    meal_type: MealType = Query(...),
    session: Session = Depends(get_session),
):
    # 1️⃣ Transkribieren
    suffix = os.path.splitext(file.filename or "")[1] or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        audio_path = tmp.name
        tmp.write(await file.read())

    try:
        segments, info = whisper_model.transcribe(audio_path, language="de", vad_filter=True)
        text = "".join(seg.text for seg in segments).strip()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")
    finally:
        try: os.unlink(audio_path)
        except OSError: pass

    if not text:
        raise HTTPException(status_code=400, detail="Kein Text erkannt")

    # 2️⃣ KI-Parsing mit Llama
    prompt = f"""
    Du bist ein Parser. Extrahiere aus dem deutschen Text Lebensmittel mit Grammangaben.
    Gib NUR JSON:
    {{"items":[{{"name":"...", "grams":123}}]}}
    Text: {text}
    """

    raw = ollama_generate(prompt)
    start, end = raw.find("{"), raw.rfind("}")
    parsed_json = {}
    if start >= 0 and end > start:
        try:
            parsed_json = json.loads(raw[start:end+1])
        except Exception:
            parsed_json = {}
    items = parsed_json.get("items", [])

    if not items:
        raise HTTPException(status_code=400, detail=f"Keine Lebensmittel erkannt: {raw}")

    # 3️⃣ Foods mappen + speichern
    saved_items = []
    for it in items:
        name, grams = it["name"].strip(), float(it["grams"])
        # Suche Food
        food_stmt = session.exec(Food.select().where(Food.name.ilike(f"%{name}%"))).first()
        if not food_stmt:
            continue
        # Hole/Erstelle Meal für Tag+Typ
        meal_stmt = session.exec(
            Meal.select().where(Meal.day == day, Meal.type == meal_type)
        ).first()
        if not meal_stmt:
            meal_stmt = Meal(day=day, type=meal_type)
            session.add(meal_stmt)
            session.commit()
            session.refresh(meal_stmt)
        # Item hinzufügen
        item = MealItem(meal_id=meal_stmt.id, food_id=food_stmt.id, grams=grams)
        session.add(item)
        session.commit()
        session.refresh(item)
        saved_items.append({
            "food": food_stmt.name,
            "grams": grams,
            "meal_id": meal_stmt.id,
            "item_id": item.id,
        })

    return VoiceMealResponse(text=text, parsed=items, saved_items=saved_items)
