# backend/app/main.py
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).resolve().parents[1] / ".env")  # lädt .env beim Start

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy import inspect
from fastapi import Response
from .db import init_db, engine

# Kernrouter (immer laden)
from .routers import health, wearables, foods, summary, meals, advisor, demo_ui, meals_ingest, foods_lookup

app = FastAPI(title="NutriTrack API", version="0.1.0", docs_url="/docs")

@app.middleware("http")
async def enforce_utf8_json(request, call_next):
    resp = await call_next(request)
    if resp.headers.get("content-type","").startswith("application/json"):
        resp.headers["content-type"] = "application/json; charset=utf-8"
    return resp

@app.get("/favicon.ico")
def favicon():
    return Response(status_code=204)  # kein Inhalt, kein Fehler

# Router registrieren (Kern)
app.include_router(health.router, tags=["health"])
app.include_router(wearables.router, prefix="/wearables", tags=["wearables"])
app.include_router(foods.router)
app.include_router(summary.router)
app.include_router(meals.router)
app.include_router(advisor.router)
app.include_router(demo_ui.router)
app.include_router(meals_ingest.router)
app.include_router(foods_lookup.router)

# Optionale Schwergewichte weich laden
try:
    from .routers import nlp  # braucht python-multipart
    app.include_router(nlp.router)
except Exception as e:
    print("[WARN] NLP routes deaktiviert:", e)

try:
    from .routers import ingest  # braucht faster-whisper/ffmpeg
    app.include_router(ingest.router)
except Exception as e:
    print("[WARN] Speech ingest deaktiviert:", e)

# Komfort: Root -> Swagger
@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse("/docs")

# Debug-Route: zeigt alle registrierten Pfade
@app.get("/__routes", include_in_schema=False)
def __routes():
    return sorted([f"{r.path}  [{','.join(r.methods)}]" for r in app.router.routes])

@app.get("/__dbcheck", include_in_schema=False)
def __dbcheck():
    return {"tables": inspect(engine).get_table_names()}

@app.on_event("startup")
def _startup():
    init_db()
