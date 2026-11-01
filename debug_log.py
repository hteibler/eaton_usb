"""Opt-in traffic logging; credentials and connection settings are never recorded."""

import json
import logging
from logging.handlers import RotatingFileHandler

LOG = logging.getLogger("eaton.traffic")
LOG.propagate = False
LOG.setLevel(logging.INFO)


def configure_debug(enabled, path="debug.log"):
    value = enabled.strip().lower()
    if value not in ("true", "false"):
        raise ValueError("DEBUG must be true or false")
    for handler in LOG.handlers[:]:
        LOG.removeHandler(handler)
        handler.close()
    LOG.disabled = value != "true"
    if not LOG.disabled:
        handler = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024,
                                      backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
        LOG.addHandler(handler)


def traffic(source, payload, **metadata):
    if LOG.disabled or not LOG.handlers:
        return
    if isinstance(payload, bytes):
        metadata["hex"] = payload.hex(" ").upper()
        metadata["payload"] = payload.decode("utf-8", errors="backslashreplace")
    else:
        metadata["payload"] = payload
    LOG.info("%s %s", source, json.dumps(metadata, ensure_ascii=False))
