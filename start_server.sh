#!/bin/bash
# Start the main FastAPI server for dbwdi
# This script ensures the correct working directory and command are used

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR/backend" || exit 1

echo "Starting dbwdi API server..."
echo ""
echo "Make sure you have:"
echo "1. Activated your virtual environment"
echo "2. Installed all dependencies (pip install -r requirements.txt)"
echo ""

python -m uvicorn app.main:app --app-dir src --reload --host 127.0.0.1 --port 8000
