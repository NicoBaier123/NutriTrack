from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["demo"])

HTML_PATH = Path(__file__).resolve().parents[1] / "web" / "templates" / "demo.html"
HTML_CONTENT = HTML_PATH.read_text(encoding="utf-8")


@router.get("/demo", response_class=HTMLResponse)
def demo_page() -> str:
    return HTML_CONTENT
