#!/bin/sh
# Serve the admission form on all network interfaces.
cd "$(dirname "$0")"
if [ -f .venv/bin/activate ]; then
  # shellcheck disable=SC1091
  . .venv/bin/activate
fi
PORT=$(python -c "from config import settings; print(settings().port)")
exec gunicorn --bind "0.0.0.0:${PORT}" --workers 2 --timeout 60 app:app
