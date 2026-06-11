#!/bin/sh
set -eu

exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload --reload-dir /app/app --reload-dir /app/scripts
