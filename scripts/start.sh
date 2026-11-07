#!/usr/bin/env bash
# Start the CQA server at http://localhost:8000
cd "$(dirname "$0")/.." && exec .venv/bin/uvicorn app.main:app --port 8000
