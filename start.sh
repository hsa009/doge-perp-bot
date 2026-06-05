#!/bin/bash
set -e
echo "=== STARTUP ==="
python3 -c "
import sys, traceback
try:
    from bot.main import app
    print('Import OK', flush=True)
except Exception:
    traceback.print_exc()
    sys.exit(1)
"
echo "=== RUNNING GUNICORN ==="
exec gunicorn --bind 0.0.0.0:7860 --workers 1 --threads 2 --error-logfile - --access-logfile - bot.main:app