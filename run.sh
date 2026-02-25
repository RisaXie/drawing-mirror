#!/bin/bash
# Start Drawing Mirror development server
# Run from the drawing-mirror project root directory
cd "$(dirname "$0")"
PYTHONPATH="$(pwd)/backend" python3 -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
