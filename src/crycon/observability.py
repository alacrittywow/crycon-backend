"""Small structured logging boundary with an explicit safe-field contract."""

from datetime import datetime, timezone
import json
import logging
from typing import Any


_BLOCKED_FIELD_PARTS = (
    "authorization",
    "credential",
    "key",
    "message",
    "password",
    "payload",
    "query",
    "secret",
    "token",
)


def event_json(event: str, **fields: Any) -> str:
    """Return one JSON log line; reject fields likely to contain sensitive data."""
    for name in fields:
        lowered = name.lower()
        if any(part in lowered for part in _BLOCKED_FIELD_PARTS):
            raise ValueError(f"unsafe structured log field: {name}")
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **{name: value for name, value in fields.items() if value is not None},
    }
    return json.dumps(record, separators=(",", ":"), sort_keys=True)


def emit_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    logger.info(event_json(event, **fields))
