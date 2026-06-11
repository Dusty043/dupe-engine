from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "dupe_engine_progress_v0_9_5"
PROGRESS_ENV = "DUPE_PROGRESS_DIR"


def progress_dir() -> Path | None:
    raw = os.getenv(PROGRESS_ENV, "").strip()
    if not raw:
        return None
    return Path(raw)


def initialize_progress(*, command: str, source_args: dict[str, Any] | None = None) -> None:
    emit_progress(
        stage="starting",
        message=f"Starting {command}",
        status="running",
        current=0,
        total=None,
        details={"command": command, "source_args": source_args or {}},
        reset=True,
    )


def emit_progress(
    *,
    stage: str,
    message: str = "",
    status: str = "running",
    current: int | None = None,
    total: int | None = None,
    details: dict[str, Any] | None = None,
    reset: bool = False,
) -> None:
    target_dir = progress_dir()
    if target_dir is None:
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    event = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": now,
        "status": status,
        "stage": stage,
        "message": message,
        "current": current,
        "total": total,
        "percent": progress_percent(current, total),
        "details": json_safe(details or {}),
    }
    events_path = target_dir / "progress_events.jsonl"
    if reset and events_path.exists():
        events_path.unlink()
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")

    started_at = now
    existing = load_progress(target_dir / "progress.json")
    if existing and not reset:
        started_at = existing.get("started_at") or now
    payload = {
        "schema_version": SCHEMA_VERSION,
        "started_at": started_at,
        "updated_at": now,
        "status": status,
        "stage": stage,
        "message": message,
        "current": current,
        "total": total,
        "percent": progress_percent(current, total),
        "details": json_safe(details or {}),
        "events_path": "progress_events.jsonl",
    }
    write_json_atomic(target_dir / "progress.json", payload)


def finish_progress(*, status: str, message: str = "", details: dict[str, Any] | None = None) -> None:
    emit_progress(stage="complete" if status == "succeeded" else "failed", message=message, status=status, details=details)


def progress_percent(current: int | None, total: int | None) -> float | None:
    if current is None or total is None or total <= 0:
        return None
    return round(max(0.0, min(1.0, float(current) / float(total))), 4)


def load_progress(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(json_safe(payload), indent=2), encoding="utf-8")
    tmp.replace(path)


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)
