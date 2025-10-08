from fastapi import FastAPI
from fastapi.responses import RedirectResponse, JSONResponse
from .db import init_db
from .routers import health, wearables
from sqlalchemy import inspect
from .db import engine
from .routers import foods, wearables, health, summary, meals, ingest, nlp, advisor, demo_ui

app = FastAPI(title="NutriTrack API", version="0.1.0", docs_url="/docs")

@app.on_event("startup")
def on_startup():
    init_db()

@app.middleware("http")
async def enforce_utf8_json(request, call_next):
    resp = await call_next(request)
    if resp.headers.get("content-type","").startswith("application/json"):
        resp.headers["content-type"] = "application/json; charset=utf-8"
    return resp

# Router registrieren
app.include_router(health.router, tags=["health"])
app.include_router(wearables.router, prefix="/wearables", tags=["wearables"])
app.include_router(foods.router)
app.include_router(summary.router)
app.include_router(meals.router)
app.include_router(ingest.router)
app.include_router(nlp.router)
app.include_router(advisor.router)
app.include_router(demo_ui.router)

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
