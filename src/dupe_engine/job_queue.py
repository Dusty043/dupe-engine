from __future__ import annotations

import json
import os
import queue
import threading
import uuid
from typing import Any


def _sqs_queue_url() -> str:
    return os.environ.get("DUPE_SQS_QUEUE_URL", "")


def _aws_region() -> str:
    return os.environ.get("DUPE_AWS_REGION", "us-east-1")


def _aws_mode() -> bool:
    return bool(_sqs_queue_url())


# ---------------------------------------------------------------------------
# Local in-process queue (used when DUPE_SQS_QUEUE_URL is unset)
# ---------------------------------------------------------------------------

_local_queue: queue.Queue[tuple[dict[str, Any], str]] = queue.Queue()
_local_receipts: dict[str, dict[str, Any]] = {}
_local_lock = threading.Lock()


def _local_send(message: dict[str, Any]) -> str:
    receipt = uuid.uuid4().hex
    with _local_lock:
        _local_receipts[receipt] = message
    _local_queue.put((message, receipt))
    return receipt


def _local_receive(wait_seconds: int = 5) -> tuple[dict[str, Any], str] | None:
    try:
        item = _local_queue.get(timeout=wait_seconds)
        return item
    except queue.Empty:
        return None


def _local_delete(receipt_handle: str) -> None:
    with _local_lock:
        _local_receipts.pop(receipt_handle, None)


def _local_extend(receipt_handle: str, seconds: int) -> None:
    pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_job(message: dict[str, Any]) -> str:
    """Enqueue a job message. Returns the message ID or receipt handle."""
    if not _aws_mode():
        return _local_send(message)

    import boto3
    client = boto3.client("sqs", region_name=_aws_region())
    response = client.send_message(
        QueueUrl=_sqs_queue_url(),
        MessageBody=json.dumps(message),
    )
    return response["MessageId"]


def receive_job(wait_seconds: int = 20) -> tuple[dict[str, Any], str] | None:
    """Poll for one job message. Returns (message_dict, receipt_handle) or None."""
    if not _aws_mode():
        return _local_receive(wait_seconds)

    import boto3
    client = boto3.client("sqs", region_name=_aws_region())
    response = client.receive_message(
        QueueUrl=_sqs_queue_url(),
        MaxNumberOfMessages=1,
        WaitTimeSeconds=min(wait_seconds, 20),
        AttributeNames=["All"],
    )
    messages = response.get("Messages") or []
    if not messages:
        return None
    msg = messages[0]
    try:
        body = json.loads(msg["Body"])
    except (json.JSONDecodeError, KeyError):
        body = {"raw": msg.get("Body", "")}
    return body, msg["ReceiptHandle"]


def delete_job(receipt_handle: str) -> None:
    """Delete a job message from the queue after successful processing."""
    if not _aws_mode():
        _local_delete(receipt_handle)
        return

    import boto3
    client = boto3.client("sqs", region_name=_aws_region())
    client.delete_message(
        QueueUrl=_sqs_queue_url(),
        ReceiptHandle=receipt_handle,
    )


def extend_visibility(receipt_handle: str, seconds: int = 300) -> None:
    """Extend visibility timeout for a message that is still being processed."""
    if not _aws_mode():
        _local_extend(receipt_handle, seconds)
        return

    import boto3
    client = boto3.client("sqs", region_name=_aws_region())
    client.change_message_visibility(
        QueueUrl=_sqs_queue_url(),
        ReceiptHandle=receipt_handle,
        VisibilityTimeout=seconds,
    )
