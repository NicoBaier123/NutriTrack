from __future__ import annotations

from fastapi import FastAPI, Response
from fastapi.responses import RedirectResponse
from sqlalchemy import inspect
from starlette.requests import Request

from app.core.config import get_settings
from app.core.database import engine, init_db
from app.routers import (
    advisor,
    demo_ui,
    foods,
    foods_lookup,
    health,
    meals,
    meals_ingest,
    summary,
    wearables,
)


CORE_ROUTERS = (
    (health.router, {"tags": ["health"]}),
    (wearables.router, {"prefix": "/wearables", "tags": ["wearables"]}),
    (foods.router, {}),
    (summary.router, {}),
    (meals.router, {}),
    (advisor.router, {}),
    (demo_ui.router, {}),
    (meals_ingest.router, {}),
    (foods_lookup.router, {}),
)


def create_app() -> FastAPI:
    settings = get_settings()
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        docs_url=settings.docs_url,
    )

    @application.middleware("http")
    async def enforce_utf8_json(request: Request, call_next):
        response = await call_next(request)
        if response.headers.get("content-type", "").startswith("application/json"):
            response.headers["content-type"] = "application/json; charset=utf-8"
        return response

    @application.get("/favicon.ico")
    def favicon():
        return Response(status_code=204)

    for router, include_kwargs in CORE_ROUTERS:
        application.include_router(router, **include_kwargs)

    try:
        from app.routers import nlp  # type: ignore  # optional dependency

        application.include_router(nlp.router)
    except Exception as exc:  # pragma: no cover - diagnostics only
        print("[WARN] NLP routes deaktiviert:", exc)

    try:
        from app.routers import ingest  # type: ignore  # optional dependency

        application.include_router(ingest.router)
    except Exception as exc:  # pragma: no cover - diagnostics only
        print("[WARN] Speech ingest deaktiviert:", exc)

    @application.get("/", include_in_schema=False)
    def root():
        target = settings.docs_url or "/docs"
        return RedirectResponse(target)

    @application.get("/__routes", include_in_schema=False)
    def routes_snapshot():
        return sorted(f"{route.path}  [{','.join(route.methods)}]" for route in application.router.routes)

    @application.get("/__dbcheck", include_in_schema=False)
    def dbcheck():
        return {"tables": inspect(engine).get_table_names()}

    @application.on_event("startup")
    def _startup():
        init_db()

    return application


app = create_app()
