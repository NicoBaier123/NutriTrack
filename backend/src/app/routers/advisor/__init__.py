from __future__ import annotations

from fastapi import APIRouter

from .routes import chat, compose, gaps, recommendations

router = APIRouter(prefix="/advisor", tags=["advisor"])

router.include_router(gaps.router)
router.include_router(recommendations.router)
router.include_router(chat.router)
router.include_router(compose.router)

__all__ = ["router"]

