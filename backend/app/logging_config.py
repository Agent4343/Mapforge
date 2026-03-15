"""Structured logging configuration."""

import logging
import sys


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure application-wide logging."""
    logger = logging.getLogger("mapforge")
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger


log = setup_logging()
