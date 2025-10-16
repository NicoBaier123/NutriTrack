# backend/app/routers/foods_lookup.py
from __future__ import annotations

from typing import Optional, List, Literal
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from pydantic import ConfigDict  # Pydantic v2
from sqlmodel import Session, select

from app.db import get_session
from app.models.foods import Food
from app.models.foods_extra import FoodSource, FoodSynonym

import os
import requests

router = APIRouter(prefix="/foods", tags=["foods"])

# -------------------- Konfiguration --------------------
def _fdc_cfg() -> dict:
    # Key ggf. von Anführungszeichen/Whitespace befreien
    key = (os.getenv("FDC_API_KEY") or "").strip().strip('"').strip("'")
    base = (os.getenv("FDC_BASE_URL") or "https://api.nal.usda.gov/fdc").strip().rstrip("/")
    return {"api_key": key, "base": base}

def _http_session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False  # keine Proxy-Envvariablen übernehmen
    s.headers.update({
        "Accept": "application/json",
        "User-Agent": "NutriTrack/0.1",
    })
    return s

# -------------------- FDC (FoodData Central) --------------------
def _fdc_search(query: str, limit: int = 5) -> dict:
    cfg = _fdc_cfg()
    if not cfg["api_key"]:
        raise HTTPException(status_code=503, detail="FDC_API_KEY not configured")

    url = f'{cfg["base"]}/v1/foods/search'
    params = {"api_key": cfg["api_key"], "query": query, "pageSize": limit}

    sess = _http_session()
    try:
        r = sess.get(url, params=params, timeout=10)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"FDC request error: {e}")

    # Debug hilft bei 403 etc.
    print("[FDC/_search]", "status=", r.status_code, "url=", r.url, "body_prefix=", (r.text or "")[:120])

    if r.status_code != 200:
        # 403/401/… → nach außen 502, wir fallen im Lookup auf OFF zurück
        raise HTTPException(status_code=502, detail=f"FDC search failed: HTTP {r.status_code}")
    try:
        return r.json()
    except Exception:
        raise HTTPException(status_code=502, detail="FDC invalid JSON")

def _fdc_details(fdc_id: str) -> dict:
    cfg = _fdc_cfg()
    if not cfg["api_key"]:
        raise HTTPException(status_code=503, detail="FDC_API_KEY not configured")

    url = f'{cfg["base"]}/v1/food/{fdc_id}'
    params = {"api_key": cfg["api_key"]}

    sess = _http_session()
    try:
        r = sess.get(url, params=params, timeout=10)
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"FDC request error: {e}")

    print("[FDC/_details]", "status=", r.status_code, "url=", r.url, "body_prefix=", (r.text or "")[:120])

    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"FDC details failed: HTTP {r.status_code}")
    try:
        return r.json()
    except Exception:
        raise HTTPException(status_code=502, detail="FDC invalid JSON")

def _nutrients_from_fdc(food_json: dict):
    # Details-Endpunkt: foodNutrients -> nutrient.name/amount
    byname = {str(n.get("nutrient", {}).get("name", "")).lower(): n for n in food_json.get("foodNutrients", [])}
    def get(name, fallback=None):
        n = byname.get(name)
        return n.get("amount") if n and n.get("amount") is not None else fallback
    kcal  = get("energy", get("energy (atwater general factors)"))
    prot  = get("protein")
    carbs = get("carbohydrate, by difference")
    fat   = get("total lipid (fat)")
    return kcal, prot, carbs, fat

# -------------------- Open Food Facts (Fallback, ohne Key) --------------------
def _off_search(query: str, limit: int = 5) -> dict:
    url = "https://world.openfoodfacts.org/cgi/search.pl"
    params = {
        "search_terms": query,
        "search_simple": 1,
        "json": 1,
        "page_size": limit,
        "fields": "code,product_name,nutriments,brands,countries",
    }
    sess = _http_session()
    r = sess.get(url, params=params, timeout=10)
    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"OFF search failed: HTTP {r.status_code}")
    return r.json()

def _off_to_candidates(data: dict) -> list[dict]:
    items = []
    for p in data.get("products", []) or []:
        n = p.get("nutriments", {}) or {}
        kcal = n.get("energy-kcal_100g") or n.get("energy-kcal")
        prot = n.get("proteins_100g")
        carbs= n.get("carbohydrates_100g")
        fat  = n.get("fat_100g")
        name = p.get("product_name") or "Unbekannt"
        items.append({
            "provider": "off",
            "provider_id": str(p.get("code") or ""),
            "name": name,
            "kcal_100g": float(kcal) if kcal is not None else None,
            "protein_g_100g": float(prot) if prot is not None else None,
            "carbs_g_100g": float(carbs) if carbs is not None else None,
            "fat_g_100g": float(fat) if fat is not None else None,
            "note": "OpenFoodFacts",
        })
    return items

# -------------------- Schemas --------------------
class LookupRequest(BaseModel):
    query: str = Field(..., min_length=2, description="Freitext (z. B. 'Magerquark 0.2%')")
    limit: int = Field(5, ge=1, le=10)

class LookupCandidate(BaseModel):
    provider: Literal["fdc", "off"]
    provider_id: str
    name: str
    kcal_100g: Optional[float] = None
    protein_g_100g: Optional[float] = None
    carbs_g_100g: Optional[float] = None
    fat_g_100g: Optional[float] = None
    note: Optional[str] = None

class LookupResponse(BaseModel):
    local_match_food_id: Optional[int] = None
    local_match_food_name: Optional[str] = None
    candidates: List[LookupCandidate] = []

class ConfirmRequest(BaseModel):
    provider: Literal["fdc", "off"]
    provider_id: str
    # 'as' ist Keyword in Python → Alias verwenden
    action: Literal["new_food", "synonym_of_existing"] = Field("new_food", alias="as")
    existing_food_id: Optional[int] = None
    synonym_value: Optional[str] = None  # z. B. normalisierte Rohbezeichnung
    model_config = ConfigDict(populate_by_name=True)

class ConfirmResponse(BaseModel):
    food_id: int
    created: bool
    source: str
    source_id: str

# -------------------- Endpoints --------------------
@router.post("/lookup", response_model=LookupResponse)
def foods_lookup(req: LookupRequest, session: Session = Depends(get_session)):
    q = (req.query or "").strip()
    if len(q) < 2:
        raise HTTPException(status_code=400, detail="query too short")

    # Lokale exakte Übereinstimmung (einfach)
    local = session.exec(select(Food).where(Food.name.ilike(q))).first()
    local_id = local.id if local else None
    local_name = local.name if local else None

    items: List[LookupCandidate] = []

    # 1) FDC versuchen (nur wenn Key vorhanden). Bei Fehlern/403 → still auf OFF fallen
    fdc_ok = False
    try:
        cfg = _fdc_cfg()
        if cfg.get("api_key"):
            fdc_data = _fdc_search(q, limit=req.limit)
            for r in fdc_data.get("foods", []) or []:
                fdc_id = str(r.get("fdcId"))
                desc   = r.get("description") or r.get("lowercaseDescription") or "unbekannt"
                kcal = prot = carbs = fat = None
                if r.get("foodNutrients"):
                    try:
                        byname = {str(n.get("nutrientName","")).lower(): n for n in r["foodNutrients"]}
                        kcal  = byname.get("energy, kcal", {}).get("value")
                        prot  = byname.get("protein", {}).get("value")
                        carbs = byname.get("carbohydrate, by difference", {}).get("value")
                        fat   = byname.get("total lipid (fat)", {}).get("value")
                    except Exception:
                        pass
                items.append(LookupCandidate(
                    provider="fdc",
                    provider_id=fdc_id,
                    name=(desc or "").title(),
                    kcal_100g=kcal,
                    protein_g_100g=prot,
                    carbs_g_100g=carbs,
                    fat_g_100g=fat,
                    note=r.get("dataType"),
                ))
                fdc_ok = True
    except HTTPException:
        fdc_ok = False  # 403/502 → egal, wir probieren OFF

    # 2) Wenn FDC leer/fehlerhaft → OFF-Fallback
    if not fdc_ok and len(items) == 0:
        off = _off_search(q, limit=req.limit)
        for it in _off_to_candidates(off):
            items.append(LookupCandidate(**it))

    return LookupResponse(local_match_food_id=local_id, local_match_food_name=local_name, candidates=items)

@router.post("/confirm", response_model=ConfirmResponse)
def foods_confirm(req: ConfirmRequest, session: Session = Depends(get_session)):
    if req.action == "synonym_of_existing":
        if not req.existing_food_id or not req.synonym_value:
            raise HTTPException(status_code=400, detail="existing_food_id and synonym_value required")
        syn = req.synonym_value.strip().lower()
        session.add(FoodSynonym(food_id=req.existing_food_id, synonym=syn))
        session.commit()
        return ConfirmResponse(food_id=req.existing_food_id, created=False, source=req.provider, source_id=req.provider_id)

    # action == "new_food"
    if req.provider == "fdc":
        info = _fdc_details(req.provider_id)
        name = (info.get("description") or "Unbekannt").title()
        kcal, prot, carbs, fat = _nutrients_from_fdc(info)
        if any(v is None for v in [kcal, prot, carbs, fat]):
            raise HTTPException(status_code=422, detail="FDC record has incomplete macros")
        food = Food(
            name=name,
            kcal=float(kcal or 0.0),
            protein_g=float(prot or 0.0),
            carbs_g=float(carbs or 0.0),
            fat_g=float(fat or 0.0),
        )
        session.add(food); session.flush()
        session.add(FoodSource(food_id=food.id, source="fdc", source_id=str(req.provider_id)))
        session.commit()
        return ConfirmResponse(food_id=food.id, created=True, source="fdc", source_id=req.provider_id)

    elif req.provider == "off":
        # Produktdetails per Barcode laden
        url = f"https://world.openfoodfacts.org/api/v2/product/{req.provider_id}.json"
        r = _http_session().get(url, timeout=10)
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail="OFF details failed")
        pj = r.json().get("product", {}) if r.headers.get("content-type","").startswith("application/json") else {}
        n = pj.get("nutriments", {}) or {}
        name = pj.get("product_name") or "Unbekannt"
        kcal = n.get("energy-kcal_100g"); prot = n.get("proteins_100g")
        carbs= n.get("carbohydrates_100g"); fat = n.get("fat_100g")
        if any(v is None for v in [kcal, prot, carbs, fat]):
            raise HTTPException(status_code=422, detail="OFF record has incomplete macros")
        food = Food(
            name=name,
            kcal=float(kcal),
            protein_g=float(prot),
            carbs_g=float(carbs),
            fat_g=float(fat),
        )
        session.add(food); session.flush()
        session.add(FoodSource(food_id=food.id, source="off", source_id=str(req.provider_id)))
        session.commit()
        return ConfirmResponse(food_id=food.id, created=True, source="off", source_id=req.provider_id)

    else:
        raise HTTPException(status_code=400, detail="unsupported provider")

# -------------------- Debug-Endpunkte --------------------
@router.get("/lookup/debug")
def foods_lookup_debug():
    cfg = _fdc_cfg()
    return {"has_key": bool(cfg["api_key"]), "base": cfg["base"]}

@router.get("/lookup/probe")
def foods_lookup_probe(q: str = "quark", limit: int = 5):
    """Direktaufruf FDC, um Status/URL/Body zu sehen (Fehleranalyse)."""
    cfg = _fdc_cfg()
    if not cfg["api_key"]:
        return {"error": "FDC_API_KEY missing"}
    url = f'{cfg["base"]}/v1/foods/search'
    params = {"api_key": cfg["api_key"], "query": q, "pageSize": limit}
    try:
        r = _http_session().get(url, params=params, timeout=10)
    except requests.RequestException as e:
        return {"error": f"request_exception: {e!s}"}
    return {
        "status": r.status_code,
        "url": r.url,
        "resp_headers": dict(list(r.headers.items())[:10]),
        "body_prefix": (r.text or "")[:400],
    }
