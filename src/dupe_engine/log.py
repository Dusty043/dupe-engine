from __future__ import annotations

import json
import os
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

# Fields that may contain PHI — redacted when DUPE_LOG_PHI is not truthy.
_PHI_KEYS = frozenset({
    "error", "error_message", "trace", "stdout_tail", "stderr_tail",
    "filename", "received_files", "ere_files", "detail",
    "reviewer_note", "reviewer_name",
})

# Patterns in string values that indicate a leaked credential.
_CREDENTIAL_RE = re.compile(
    r"(?i)(sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|[A-Za-z0-9+/]{40}={0,2})",
)

_TRUE_VALUES = {"1", "true", "yes", "y", "on"}


def _log_phi_enabled() -> bool:
    return os.environ.get("DUPE_LOG_PHI", "").strip().lower() in _TRUE_VALUES


def _scrub_string(value: str) -> str:
    """Replace credential-like substrings in a string value with [REDACTED]."""
    return _CREDENTIAL_RE.sub("[REDACTED]", value)


def log(level: str, event: str, **fields: Any) -> None:
    """Emit a single JSON log line to stdout.

    When DUPE_LOG_PHI is not set (the default), fields in _PHI_KEYS are
    replaced with "[PHI-REDACTED]" to prevent PHI leakage into CloudWatch.
    Credential key names and patterns are always redacted regardless.
    """
    phi_ok = _log_phi_enabled()
    safe_fields: dict[str, Any] = {}
    for key, value in fields.items():
        norm_key = key.lower().replace("-", "_")
        if norm_key in _REDACTED_KEYS:
            safe_fields[key] = "[REDACTED]"
        elif not phi_ok and norm_key in _PHI_KEYS:
            safe_fields[key] = "[PHI-REDACTED]"
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


def log_exception(level: str, event: str, exc: BaseException, **fields: Any) -> None:
    """Log an exception safely.

    When DUPE_LOG_PHI is off: logs exception type name only (no message/trace).
    When DUPE_LOG_PHI is on: logs full message and traceback.
    """
    import traceback as _tb
    if _log_phi_enabled():
        log(level, event, error=str(exc), trace=_tb.format_exc(), **fields)
    else:
        log(level, event, error_type=type(exc).__name__, **fields)
