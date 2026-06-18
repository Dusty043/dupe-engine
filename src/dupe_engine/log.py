from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from typing import Any

# Fields that must never appear in log output.
_REDACTED_KEYS = frozenset({
    "api_key", "openai_api_key", "dupe_openai_api_key",
    "authorization", "bearer", "secret", "password", "token",
})


def log(level: str, event: str, **fields: Any) -> None:
    """Emit a single JSON log line to stdout.

    Redacts any field whose name (case-insensitive) is in _REDACTED_KEYS.
    Never logs raw document text (callers must not pass page content here).
    """
    safe_fields: dict[str, Any] = {}
    for key, value in fields.items():
        if key.lower().replace("-", "_") in _REDACTED_KEYS:
            safe_fields[key] = "[REDACTED]"
        else:
            safe_fields[key] = value

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "level": level,
        "event": event,
        **safe_fields,
    }
    try:
        line = json.dumps(record, default=str)
    except Exception:
        line = json.dumps({"ts": record["ts"], "level": "error", "event": "log_serialization_failed", "original_event": event})

    print(line, flush=True)
