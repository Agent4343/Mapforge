"""Startup wrapper — catches import/startup errors and prints them to logs."""

import logging
import os
import sys
import traceback

log = logging.getLogger("mapforge.startup")
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

try:
    log.info("Python %s", sys.version)
    log.info("PORT=%s", os.environ.get("PORT", "unset"))
    log.info("DATABASE_URL=%s", "set" if os.environ.get("DATABASE_URL") else "unset")

    # Refuse to start without SECRET_KEY in production (Railway sets RAILWAY_PUBLIC_DOMAIN)
    if not os.environ.get("SECRET_KEY"):
        if os.environ.get("RAILWAY_PUBLIC_DOMAIN"):
            log.critical("SECRET_KEY not set — refusing to start in production. Set SECRET_KEY in your environment.")
            sys.exit(1)
        else:
            log.warning("SECRET_KEY not set — using empty key. Set SECRET_KEY before deploying!")

    from app.main import app
    log.info("App import OK")

    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port, timeout_keep_alive=65)
except Exception as e:
    log.critical("FATAL STARTUP ERROR: %s", e)
    traceback.print_exc()
    sys.exit(1)
