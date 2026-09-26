"""Structured JSON logs with the case id on every line (PRD 9.15).

The case id travels in a ContextVar, so background tasks created while handling a
case (attestation, analyst) inherit it automatically.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

case_id_var: ContextVar[str | None] = ContextVar("sekisho_case_id", default=None)

_STD_ATTRS = set(
    logging.LogRecord("", 0, "", 0, "", None, None).__dict__.keys()
) | {"message", "asctime", "case_id", "color_message"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.%fZ"
            ),
            "level": record.levelname,
            "logger": record.name,
            "case_id": getattr(record, "case_id", None) or case_id_var.get(),
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STD_ATTRS and not key.startswith("_"):
                line[key] = value
        if record.exc_info:
            line["exc"] = self.formatException(record.exc_info)
        return json.dumps(line, default=str, ensure_ascii=False)


def setup_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # Route uvicorn's own loggers through the JSON handler; the gate logs requests
    # itself (with the case id), so the plain access log is silenced.
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers[:] = []
        lg.propagate = True
    access = logging.getLogger("uvicorn.access")
    access.handlers[:] = []
    access.propagate = False
    for noisy in ("httpx", "httpcore", "httpx2", "httpcore2", "anthropic", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
