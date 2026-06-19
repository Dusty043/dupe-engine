from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .log import log as _log


def _audit_table() -> str:
    return os.environ.get("DUPE_DYNAMO_AUDIT_TABLE", "duplicate-checker-audit")


def _aws_region() -> str:
    return os.environ.get("DUPE_AWS_REGION", "us-east-1")


def _aws_mode() -> bool:
    return bool(os.environ.get("DUPE_DYNAMO_TABLE", ""))


def _local_audit_dir() -> Path:
    return Path(os.environ.get("DUPE_LOCAL_AUDIT_DIR", "output/audit"))


_local_write_lock = threading.Lock()


def record_event(
    *,
    job_id: str,
    action: str,
    actor: str,
    resource: str,
    outcome: str,
    source_ip: str = "",
    detail: str = "",
) -> None:
    """Append an immutable PHI-access audit event.

    Failure is fail-open: the error is logged loudly but the caller is not blocked.
    Complies with HIPAA §164.312(b) audit controls.

    action:   one of read/write/export/upload/delete/enqueue/process
    actor:    authenticated identity string (e.g. "shared-token", "worker")
    resource: opaque resource identifier (job_id, candidate_id, S3 prefix, etc.)
    outcome:  "success" | "failure" | "denied"
    """
    ts = datetime.now(timezone.utc).isoformat()
    event_id = uuid.uuid4().hex
    item: dict[str, Any] = {
        "job_id": job_id or "GLOBAL",
        "event_ts_id": f"{ts}#{event_id}",
        "ts": ts,
        "action": action,
        "actor": actor,
        "resource": resource,
        "outcome": outcome,
        "source_ip": source_ip,
        "detail": detail,
    }
    try:
        if _aws_mode():
            _write_dynamo(item)
        else:
            _write_local(item)
    except Exception as exc:
        _log("error", "audit_write_failed", action=action, resource=resource,
             error_type=type(exc).__name__)


def _write_dynamo(item: dict[str, Any]) -> None:
    import boto3
    table = boto3.resource("dynamodb", region_name=_aws_region()).Table(_audit_table())
    table.put_item(
        Item=item,
        ConditionExpression="attribute_not_exists(event_ts_id)",
    )


def _write_local(item: dict[str, Any]) -> None:
    audit_dir = _local_audit_dir()
    audit_dir.mkdir(parents=True, exist_ok=True)
    audit_path = audit_dir / "audit.jsonl"
    line = json.dumps(item, default=str) + "\n"
    with _local_write_lock:
        with audit_path.open("a", encoding="utf-8") as fh:
            fh.write(line)
