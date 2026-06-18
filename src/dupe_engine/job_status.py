from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _dynamo_table() -> str:
    return os.environ.get("DUPE_DYNAMO_TABLE", "")


def _aws_region() -> str:
    return os.environ.get("DUPE_AWS_REGION", "us-east-1")


def _aws_mode() -> bool:
    return bool(_dynamo_table())


def _local_store_dir() -> Path:
    base = os.environ.get("DUPE_LOCAL_STATUS_DIR", "output/job_status")
    return Path(base)


# ---------------------------------------------------------------------------
# Local file-based fallback (when DUPE_DYNAMO_TABLE is unset)
# ---------------------------------------------------------------------------

_local_lock = threading.Lock()


def _local_put(record: dict[str, Any]) -> None:
    store = _local_store_dir()
    store.mkdir(parents=True, exist_ok=True)
    path = store / f"{record['job_id']}.json"
    _write_json_atomic(path, record)


def _local_get(job_id: str) -> dict[str, Any] | None:
    path = _local_store_dir() / f"{job_id}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _local_list(limit: int = 50) -> list[dict[str, Any]]:
    store = _local_store_dir()
    if not store.exists():
        return []
    records = []
    for path in sorted(store.glob("*.json"), reverse=True)[:limit]:
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    return sorted(records, key=lambda r: r.get("created_at", ""), reverse=True)


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def put_job(record: dict[str, Any]) -> None:
    """Create or fully replace a job record."""
    if not _aws_mode():
        _local_put(record)
        return

    import boto3
    dynamo = boto3.resource("dynamodb", region_name=_aws_region())
    table = dynamo.Table(_dynamo_table())
    table.put_item(Item=_dynamo_serialize(record))


def get_job(job_id: str) -> dict[str, Any] | None:
    """Retrieve a job record by job_id. Returns None if not found."""
    if not _aws_mode():
        return _local_get(job_id)

    import boto3
    dynamo = boto3.resource("dynamodb", region_name=_aws_region())
    table = dynamo.Table(_dynamo_table())
    response = table.get_item(Key={"job_id": job_id})
    item = response.get("Item")
    return _dynamo_deserialize(item) if item else None


def update_job(job_id: str, **updates: Any) -> None:
    """Partially update a job record. Always sets updated_at."""
    updates["updated_at"] = _utc_now()

    if not _aws_mode():
        existing = _local_get(job_id) or {}
        existing.update(updates)
        existing["job_id"] = job_id
        _local_put(existing)
        return

    import boto3
    from boto3.dynamodb.conditions import Attr  # noqa: F401
    dynamo = boto3.resource("dynamodb", region_name=_aws_region())
    table = dynamo.Table(_dynamo_table())

    set_parts = []
    expr_names: dict[str, str] = {}
    expr_values: dict[str, Any] = {}
    for idx, (key, value) in enumerate(updates.items()):
        placeholder = f"#k{idx}"
        value_placeholder = f":v{idx}"
        expr_names[placeholder] = key
        expr_values[value_placeholder] = value
        set_parts.append(f"{placeholder} = {value_placeholder}")

    table.update_item(
        Key={"job_id": job_id},
        UpdateExpression="SET " + ", ".join(set_parts),
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=_dynamo_serialize_values(expr_values),
    )


def list_jobs(limit: int = 50) -> list[dict[str, Any]]:
    """Return recent jobs, newest first."""
    if not _aws_mode():
        return _local_list(limit)

    import boto3
    dynamo = boto3.resource("dynamodb", region_name=_aws_region())
    table = dynamo.Table(_dynamo_table())
    response = table.scan(Limit=limit)
    items = [_dynamo_deserialize(item) for item in (response.get("Items") or [])]
    return sorted(items, key=lambda r: r.get("created_at", ""), reverse=True)[:limit]


# ---------------------------------------------------------------------------
# Minimal DynamoDB type helpers
# ---------------------------------------------------------------------------

def _dynamo_serialize(record: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in record.items() if v is not None}


def _dynamo_serialize_values(values: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in values.items() if v is not None}


def _dynamo_deserialize(item: dict[str, Any]) -> dict[str, Any]:
    return dict(item)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
