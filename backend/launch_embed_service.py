#!/usr/bin/env python3
"""Launch the embedding service with correct path handling."""
import sys
from pathlib import Path

# Add parent directory to path so 'backend' module can be imported
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if __name__ == "__main__":
    import uvicorn
    
    print("=" * 60)
    print("Starting Embedding Service on http://127.0.0.1:8001")
    print("Press Ctrl+C to stop")
    print("=" * 60)
    print()
    
    uvicorn.run(
        "backend.scripts.embed_service:app",
        host="127.0.0.1",
        port=8001,
        reload=False
    )
