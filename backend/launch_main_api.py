#!/usr/bin/env python3
"""Launch the main API server."""
import sys
from pathlib import Path

# Add src to path
BACKEND_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_ROOT / "src"))

if __name__ == "__main__":
    import uvicorn
    
    print("=" * 60)
    print("Starting Main API Server on http://127.0.0.1:8000")
    print("Press Ctrl+C to stop")
    print("=" * 60)
    print()
    
    uvicorn.run(
        "app.main:app",
        app_dir="src",
        host="127.0.0.1",
        port=8000,
        reload=True
    )
