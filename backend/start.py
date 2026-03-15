"""Startup wrapper — catches import/startup errors and prints them to logs."""

import os
import sys
import traceback

try:
    print(f"Python {sys.version}", flush=True)
    print(f"PORT={os.environ.get('PORT', 'unset')}", flush=True)
    print(f"DATABASE_URL={'set' if os.environ.get('DATABASE_URL') else 'unset'}", flush=True)

    from app.main import app
    print("App import OK", flush=True)

    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
except Exception as e:
    print(f"FATAL STARTUP ERROR: {e}", flush=True)
    traceback.print_exc()
    sys.exit(1)
