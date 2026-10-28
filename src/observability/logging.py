"""Structured JSON logging with correlation ID propagation (Requirement D5)."""

import contextvars
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Context variable holding the correlation ID for the active request / task
correlation_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("correlation_id", default="")
run_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("run_id", default="")


class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as structured machine-parseable JSON."""

    def format(self, record: logging.LogRecord) -> str:
        log_payload: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": correlation_id_ctx.get() or getattr(record, "correlation_id", ""),
            "run_id": run_id_ctx.get() or getattr(record, "run_id", ""),
            "file": f"{record.filename}:{record.lineno}",
        }

        # Include custom extra fields if provided
        if hasattr(record, "extra_fields") and isinstance(record.extra_fields, dict):
            log_payload.update(record.extra_fields)

        if record.exc_info:
            log_payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_payload)


class StructuredLoggerAdapter(logging.LoggerAdapter):
    """Adapter to seamlessly support extra_fields kwarg."""

    def process(self, msg, kwargs):
        extra = kwargs.get("extra", {})
        if "extra_fields" in kwargs:
            extra["extra_fields"] = kwargs.pop("extra_fields")
        kwargs["extra"] = extra
        return msg, kwargs


def get_logger(name: str) -> StructuredLoggerAdapter:
    base_logger = logging.getLogger(name)
    if not base_logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(StructuredJsonFormatter())
        base_logger.addHandler(handler)
        base_logger.setLevel(logging.INFO)
        base_logger.propagate = False
    return StructuredLoggerAdapter(base_logger, {})


def set_request_context(correlation_id: str, run_id: Optional[str] = None):
    correlation_id_ctx.set(correlation_id)
    if run_id:
        run_id_ctx.set(run_id)
