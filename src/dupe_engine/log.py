from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

# Fields that must never appear in log output (key names, normalized to lower_snake_case).
_REDACTED_KEYS = frozenset({
    "api_key", "openai_api_key", "dupe_openai_api_key",
    "authorization", "bearer", "secret", "password", "token",
    "access_key", "aws_access_key_id", "aws_secret_access_key",
    "session_token", "x_api_key", "private_key", "client_secret",
})

# Patterns in string values that indicate a leaked credential.
_CREDENTIAL_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|[A-Za-z0-9+/]{40}={0,2})",
)


def _scrub_string(value: str) -> str:
    """Replace credential-like substrings in a string value with [REDACTED]."""
    return _CREDENTIAL_RE.sub("[REDACTED]", value)


def log(level: str, event: str, **fields: Any) -> None:
    """Emit a single JSON log line to stdout.

    Redacts any field whose name (case-insensitive) is in _REDACTED_KEYS,
    and scrubs credential patterns from string field values.
    Never logs raw document text (callers must not pass page content here).
    """
    safe_fields: dict[str, Any] = {}
    for key, value in fields.items():
        if key.lower().replace("-", "_") in _REDACTED_KEYS:
            safe_fields[key] = "[REDACTED]"
        elif isinstance(value, str):
            safe_fields[key] = _scrub_string(value)
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
