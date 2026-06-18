from __future__ import annotations

import os
import re
import shutil
import sys
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import artifact_store, job_queue, job_status
from .capabilities import build_capability_report
from .config import EngineConfig
from .engine import run_ab_compare
from .fallback_audit import build_fallback_audit, write_fallback_audit_json
from .log import log
from .reporting import build_report, write_json
from .ui_artifacts import write_ui_run_artifacts


ENGINE_VERSION = "v0.10.9"

# How often to extend SQS visibility while the job is running (seconds).
# Should be well under the queue's visibility timeout.
_EXTEND_INTERVAL = 60
# How much to extend by each heartbeat.
_EXTEND_BY = 300

# job_id must be a safe filesystem component — no path separators or traversal.
_JOB_ID_RE = re.compile(r'^[A-Za-z0-9_-]{8,80}$')

_VALID_RERANKER_ACTIONS = frozenset({"demote", "drop"})


def _workdir_base() -> Path:
    return Path(os.environ.get("DUPE_WORKER_WORKDIR", "/tmp/dupe-worker"))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def run_worker_loop() -> None:
    """Long-polling SQS worker loop. Runs until KeyboardInterrupt or SIGTERM."""
    log("info", "worker_started", engine_version=ENGINE_VERSION)
    try:
        while True:
            _poll_once()
    except KeyboardInterrupt:
        log("info", "worker_stopped", reason="keyboard_interrupt")


def _poll_once() -> None:
    result = job_queue.receive_job(wait_seconds=20)
    if result is None:
        return

    message, receipt_handle = result
    job_id = message.get("job_id") or ""
    if not job_id:
        log("error", "sqs_message_missing_job_id", receipt_handle=receipt_handle)
        job_queue.delete_job(receipt_handle)
        return
    if not _JOB_ID_RE.fullmatch(job_id):
        log("error", "sqs_message_invalid_job_id", job_id=job_id, receipt_handle=receipt_handle)
        job_queue.delete_job(receipt_handle)
        return

    log("info", "job_received", job_id=job_id, engine_version=ENGINE_VERSION)

    stop_event = threading.Event()
    heartbeat = threading.Thread(
        target=_visibility_heartbeat,
        args=(receipt_handle, stop_event),
        daemon=True,
    )
    heartbeat.start()

    success = False
    try:
        success = _process_job(message, receipt_handle)
    except Exception as exc:
        log("error", "job_unhandled_exception", job_id=job_id, error=str(exc), trace=traceback.format_exc())
        _mark_failed(job_id, str(exc))
    finally:
        stop_event.set()

    if success:
        try:
            job_queue.delete_job(receipt_handle)
            log("info", "sqs_message_deleted", job_id=job_id)
        except Exception as exc:
            log("error", "sqs_delete_failed", job_id=job_id, error=str(exc))


def _visibility_heartbeat(receipt_handle: str, stop: threading.Event) -> None:
    while not stop.wait(timeout=_EXTEND_INTERVAL):
        try:
            job_queue.extend_visibility(receipt_handle, _EXTEND_BY)
        except Exception as exc:
            log("warn", "visibility_extend_failed", error=str(exc))


def _validate_s3_prefix(prefix: str, field: str) -> None:
    """Reject prefixes that point at a different bucket than DUPE_S3_BUCKET."""
    if not prefix:
        return
    expected_bucket = os.environ.get("DUPE_S3_BUCKET", "")
    if not expected_bucket:
        return
    try:
        bucket, _ = artifact_store.parse_s3_uri(prefix)
    except ValueError as exc:
        raise ValueError(f"Invalid S3 URI in {field}: {prefix!r}") from exc
    if bucket != expected_bucket:
        raise ValueError(
            f"S3 prefix in {field} targets unexpected bucket {bucket!r} "
            f"(expected {expected_bucket!r})"
        )


def _process_job(message: dict[str, Any], receipt_handle: str) -> bool:
    """Download, run engine, upload. Returns True on success."""
    job_id = message["job_id"]
    input_prefix = message.get("input_prefix", "")
    output_prefix = message.get("output_prefix", "")
    config_overrides: dict[str, Any] = message.get("config") or {}

    _validate_s3_prefix(input_prefix, "input_prefix")
    _validate_s3_prefix(output_prefix, "output_prefix")

    job_status.update_job(job_id, status="running", started_at=_utc_now())
    log("info", "job_started", job_id=job_id, input_prefix=input_prefix, output_prefix=output_prefix)

    workdir = _workdir_base() / job_id
    input_dir = workdir / "input"
    run_dir = workdir / "run"
    run_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Stage inputs
        if input_prefix:
            log("info", "s3_download_start", job_id=job_id, prefix=input_prefix)
            artifact_store.download_prefix(input_prefix, input_dir)
            log("info", "s3_download_done", job_id=job_id)
        else:
            log("warn", "no_input_prefix", job_id=job_id)

        received_dir = input_dir / "received_records"
        ere_dir = input_dir / "ere_records"

        if not received_dir.exists() or not any(received_dir.iterdir()):
            raise RuntimeError(f"No received_records found under input prefix: {input_prefix}")
        if not ere_dir.exists() or not any(ere_dir.iterdir()):
            raise RuntimeError(f"No ere_records found under input prefix: {input_prefix}")

        # Build config
        config = _build_config(config_overrides)

        # Run the engine
        log("info", "engine_run_start", job_id=job_id)
        pages_a, pages_b, matches = run_ab_compare(received_dir, ere_dir, workdir / "work", config)
        log("info", "engine_run_done", job_id=job_id, pages=len(pages_a) + len(pages_b), matches=len(matches))

        # Build and write run artifacts
        capabilities = build_capability_report(config, used_core_layers=True)
        report = build_report(pages_a, pages_b, matches, config, mode="ab", capabilities=capabilities)

        results_path = workdir / "results.json"
        write_json(results_path, report)

        fallback_audit = build_fallback_audit(pages_a + pages_b, config)
        write_fallback_audit_json(run_dir / "fallback_audit.json", fallback_audit)

        write_ui_run_artifacts(
            run_dir,
            command_name="compare-ab",
            report=report,
            pages=pages_a + pages_b,
            matches=matches,
            config=config,
            capabilities=capabilities,
            source_args={
                "job_id": job_id,
                "engine_version": ENGINE_VERSION,
                "input_prefix": input_prefix,
                "output_prefix": output_prefix,
            },
        )

        # Upload outputs to S3
        if output_prefix:
            log("info", "s3_upload_start", job_id=job_id, prefix=output_prefix)
            artifact_store.upload_dir(run_dir, output_prefix)
            log("info", "s3_upload_done", job_id=job_id)

        job_status.update_job(
            job_id,
            status="completed",
            completed_at=_utc_now(),
            output_prefix=output_prefix,
            pages_processed=len(pages_a) + len(pages_b),
            match_count=len(matches),
        )
        log("info", "job_completed", job_id=job_id)
        return True

    except Exception as exc:
        log("error", "job_failed", job_id=job_id, error=str(exc), trace=traceback.format_exc())
        _mark_failed(job_id, str(exc))
        return False
    finally:
        _cleanup_workdir(workdir, job_id)


def _mark_failed(job_id: str, error: str) -> None:
    try:
        job_status.update_job(job_id, status="failed", failed_at=_utc_now(), error_message=error)
    except Exception as exc:
        log("error", "status_update_failed", job_id=job_id, error=str(exc))


def _cleanup_workdir(workdir: Path, job_id: str) -> None:
    try:
        if workdir.exists():
            shutil.rmtree(workdir)
    except Exception as exc:
        log("warn", "workdir_cleanup_failed", job_id=job_id, error=str(exc))


def _build_config(overrides: dict[str, Any]) -> EngineConfig:
    from dataclasses import replace
    base = EngineConfig.from_env()
    kwargs: dict[str, Any] = {}
    float_fields = {
        "embedding_reranker_min_confidence",
        "embedding_reranker_ocr_penalty",
        "embedding_reranker_same_doc_bonus",
        "embedding_reranker_tesseract_bonus",
    }
    bool_fields = {"embedding_reranker_enabled"}
    for msg_key in ("embedding_reranker_enabled", "embedding_reranker_min_confidence",
                    "embedding_reranker_ocr_penalty", "embedding_reranker_same_doc_bonus",
                    "embedding_reranker_tesseract_bonus", "embedding_reranker_action"):
        if msg_key not in overrides:
            continue
        raw = overrides[msg_key]
        if msg_key in float_fields:
            kwargs[msg_key] = float(raw)
        elif msg_key in bool_fields:
            kwargs[msg_key] = bool(raw)
        elif msg_key == "embedding_reranker_action":
            action = str(raw).strip().lower()
            if action not in _VALID_RERANKER_ACTIONS:
                raise ValueError(
                    f"Invalid embedding_reranker_action {action!r}; "
                    f"must be one of {sorted(_VALID_RERANKER_ACTIONS)}"
                )
            kwargs[msg_key] = action
    if kwargs:
        return replace(base, **kwargs)
    return base
