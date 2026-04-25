"""Structured logging configuration."""

import json
import logging
import os
import sys
from contextvars import ContextVar

# Per-request correlation id. The request-id middleware sets this at
# the top of every request; log records pick it up via the filter
# below so every line for a given request shares the same tag.
_REQUEST_ID: ContextVar[str | None] = ContextVar("_REQUEST_ID", default=None)


def set_request_id(req_id: str | None):
    """Set the active request id and return a token for `reset_request_id`."""
    return _REQUEST_ID.set(req_id)


def reset_request_id(token) -> None:
    _REQUEST_ID.reset(token)


def get_request_id() -> str | None:
    return _REQUEST_ID.get()


class _RequestIdFilter(logging.Filter):
    """Attach the active request_id contextvar onto each log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _REQUEST_ID.get() or "-"
        return True


class _JsonFormatter(logging.Formatter):
    """Minimal JSON formatter for structured log aggregation.

    Deliberately hand-rolled to avoid adding a dep. Emits the fields
    common log shippers (Datadog, Loki, Grafana) recognise without
    further massaging. `exc_info` is rendered into a single string so
    tracebacks stay on one log entry.
    """

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure application-wide logging.

    Log format is plain text by default for dev ergonomics. Set
    LOG_FORMAT=json in production so Railway / Loki / Datadog ingest
    clean structured rows.
    """
    logger = logging.getLogger("mapforge")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.DEBUG)
        if os.getenv("LOG_FORMAT", "").lower() == "json":
            handler.setFormatter(_JsonFormatter())
        else:
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s [%(levelname)s] %(name)s [%(request_id)s]: %(message)s",
                    datefmt="%Y-%m-%d %H:%M:%S",
                )
            )
        handler.addFilter(_RequestIdFilter())
        logger.addHandler(handler)

    return logger


log = setup_logging()
