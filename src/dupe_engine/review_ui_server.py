from __future__ import annotations

import argparse
import collections
import json
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default as email_default_policy
import mimetypes
import os
import posixpath
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
import webbrowser
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from . import job_status as _job_status_module
from . import job_queue as _job_queue_module
from . import artifact_store as _artifact_store_module
from .log import log as _log

ALLOWED_REVIEW_LABELS = {
    "duplicate",
    "likely_duplicate",
    "possible_duplicate",
    "partial_overlap",
    "not_duplicate",
    "needs_review",
}

REQUIRED_RUN_FILES = [
    "run_manifest.json",
    "pages.json",
    "candidates.json",
    "capabilities.json",
    "metrics.json",
    "review_decisions.json",
]

STATIC_DIR = Path(__file__).with_name("review_ui_static")
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024
MAX_JSON_BODY_BYTES = 1 * 1024 * 1024  # 1 MB — review decisions are small JSON
PDF_SUFFIX = ".pdf"

# Rate limiting: max concurrent uploads per source IP.
MAX_CONCURRENT_UPLOADS_PER_IP = 3
_active_uploads: dict[str, int] = collections.defaultdict(int)
_uploads_lock = threading.Lock()

# Internal job record fields that must not be returned to API clients.
_INTERNAL_JOB_FIELDS = frozenset({
    "job_dir", "input_dir", "work_dir", "run_dir", "results_path",
})


class ReviewUiError(RuntimeError):
    """Raised when a review UI request cannot be served safely."""


@dataclass
class UploadPart:
    name: str
    filename: str | None
    payload: bytes


def _aws_mode() -> bool:
    """True when DynamoDB table is configured — use persistent job store."""
    return bool(os.environ.get("DUPE_DYNAMO_TABLE", ""))


def _sqs_mode() -> bool:
    """True when SQS queue URL is configured — UI enqueues instead of running engine inline."""
    return bool(os.environ.get("DUPE_SQS_QUEUE_URL", ""))


def _s3_mode() -> bool:
    """True when S3 bucket is configured — inputs are uploaded to S3 before enqueueing."""
    return bool(os.environ.get("DUPE_S3_BUCKET", ""))


def _allowed_origin() -> str:
    """Return the single origin permitted for CORS. Defaults to localhost."""
    return os.environ.get("DUPE_UI_ALLOWED_ORIGIN", "http://localhost:8765")


def _sanitize_job_for_api(job: dict[str, Any]) -> dict[str, Any]:
    """Strip internal filesystem paths before sending a job record to a client."""
    return {k: v for k, v in job.items() if k not in _INTERNAL_JOB_FIELDS}


class ReviewJobStore:
    """Job registry — backed by DynamoDB when DUPE_DYNAMO_TABLE is set, in-memory otherwise."""

    def __init__(self, *, workspace_dir: Path, current_run_dir: Path | None = None) -> None:
        self.workspace_dir = workspace_dir.expanduser().resolve()
        self.workspace_dir.mkdir(parents=True, exist_ok=True)
        self.current_run_dir = current_run_dir.expanduser().resolve() if current_run_dir else None
        # In-memory fallback store (used when DUPE_DYNAMO_TABLE is unset)
        self._mem_jobs: dict[str, dict[str, Any]] = {}
        self.lock = threading.RLock()

    def set_current_run(self, run_dir: Path | None) -> None:
        with self.lock:
            self.current_run_dir = run_dir.expanduser().resolve() if run_dir else None

    def get_current_run(self) -> Path | None:
        with self.lock:
            return self.current_run_dir

    def create_job_record(self, *, job_dir: Path, received_files: list[str], ere_files: list[str], settings: dict[str, Any]) -> dict[str, Any]:
        job_id = job_dir.name
        now = utc_now()
        record = {
            "job_id": job_id,
            "status": "queued",
            "stage": "queued",
            "created_at": now,
            "updated_at": now,
            "finished_at": None,
            "received_files": received_files,
            "ere_files": ere_files,
            "settings": settings,
            "job_dir": str(job_dir),
            "input_dir": str(job_dir / "input"),
            "work_dir": str(job_dir / "work"),
            "run_dir": str(job_dir / "run"),
            "results_path": str(job_dir / "results.json"),
            "stdout_tail": "",
            "stderr_tail": "",
            "error": None,
            "command": [],
        }
        if _aws_mode():
            _job_status_module.put_job(record)
        else:
            with self.lock:
                self._mem_jobs[job_id] = record
        return dict(record)

    def update_job(self, job_id: str, **updates: Any) -> dict[str, Any]:
        if _aws_mode():
            _job_status_module.update_job(job_id, **updates)
            record = _job_status_module.get_job(job_id) or {}
            return record
        with self.lock:
            if job_id not in self._mem_jobs:
                raise ReviewUiError(f"Unknown job: {job_id}")
            self._mem_jobs[job_id].update(updates)
            self._mem_jobs[job_id]["updated_at"] = utc_now()
            return dict(self._mem_jobs[job_id])

    def get_job(self, job_id: str) -> dict[str, Any]:
        if _aws_mode():
            record = _job_status_module.get_job(job_id)
            if record is None:
                raise ReviewUiError(f"Unknown job: {job_id}")
            return record
        with self.lock:
            if job_id not in self._mem_jobs:
                raise ReviewUiError(f"Unknown job: {job_id}")
            return dict(self._mem_jobs[job_id])

    def list_jobs(self) -> list[dict[str, Any]]:
        if _aws_mode():
            return _job_status_module.list_jobs(limit=100)
        with self.lock:
            return sorted((dict(job) for job in self._mem_jobs.values()), key=lambda item: item.get("created_at", ""), reverse=True)


def serve_review_ui(args: argparse.Namespace) -> None:
    run_dir_arg = getattr(args, "run_dir", None)
    run_dir = Path(run_dir_arg).expanduser().resolve() if run_dir_arg else None
    if run_dir:
        validate_run_dir(run_dir)

    workspace_dir = Path(getattr(args, "workspace", "output/review_ui_jobs")).expanduser().resolve()
    store = ReviewJobStore(workspace_dir=workspace_dir, current_run_dir=run_dir)

    host = getattr(args, "host", "127.0.0.1")
    port = int(getattr(args, "port", 8765))
    open_browser = not bool(getattr(args, "no_browser", False))

    handler = build_handler(store=store, static_dir=STATIC_DIR)
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{server.server_address[1]}"

    print("Medical Records Sorter Assist review UI")
    if run_dir:
        print(f"[DEBUG MODE] --run-dir is set: {run_dir}")
        print("[DEBUG MODE] This pre-loads a run on startup. Omit --run-dir in production.")
    print(f"Upload/job workspace: {workspace_dir}")
    print(f"Open: {url}")
    print("Press Ctrl+C to stop.")

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped review UI.")
    finally:
        server.server_close()


def validate_run_dir(run_dir: Path) -> None:
    if not run_dir.exists() or not run_dir.is_dir():
        raise ReviewUiError(f"Run folder does not exist: {run_dir}")
    missing = [name for name in REQUIRED_RUN_FILES if not (run_dir / name).exists()]
    if missing:
        raise ReviewUiError(f"Run folder is missing required UI artifact files: {', '.join(missing)}")
    if not STATIC_DIR.exists():
        raise ReviewUiError(f"Review UI static assets are missing: {STATIC_DIR}")


def build_handler(*, store: ReviewJobStore, static_dir: Path) -> type[BaseHTTPRequestHandler]:
    class ReviewUiRequestHandler(BaseHTTPRequestHandler):
        server_version = "DupeEngineReviewUI/0.9.8"

        def log_message(self, fmt: str, *args: Any) -> None:
            print(f"{self.address_string()} - {fmt % args}")

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            path = parsed.path
            try:
                if path == "/api/health":
                    self.send_json({"ok": True, "workspace_dir": str(store.workspace_dir), "has_run": bool(store.get_current_run())})
                    return
                if path == "/api/run":
                    run_dir = store.get_current_run()
                    if run_dir is None:
                        self.send_json({
                            "schema_version": "dupe_engine_review_ui_payload_v0_9_5",
                            "has_run": False,
                            "workspace_dir": str(store.workspace_dir),
                            "jobs": [_sanitize_job_for_api(j) for j in store.list_jobs()],
                        })
                        return
                    validate_run_dir(run_dir)
                    payload = load_run_payload(run_dir)
                    payload["has_run"] = True
                    payload["jobs"] = [_sanitize_job_for_api(j) for j in store.list_jobs()]
                    self.send_json(payload)
                    return
                if path == "/api/jobs":
                    self.send_json({"jobs": [_sanitize_job_for_api(j) for j in store.list_jobs()]})
                    return
                if path.startswith("/api/jobs/"):
                    job_id = path.removeprefix("/api/jobs/").strip("/")
                    job = store.get_job(job_id)
                    run_dir_path = Path(job["run_dir"]) if job.get("run_dir") else None
                    progress = load_job_progress(run_dir_path) if run_dir_path else None
                    public_job = _sanitize_job_for_api(job)
                    public_job["progress"] = progress
                    self.send_json(public_job)
                    return
                if path == "/api/review-decisions":
                    self.send_json(load_review_decisions(require_current_run(store)))
                    return
                if path.startswith("/run-artifacts/"):
                    rel = path.removeprefix("/run-artifacts/")
                    self.send_file_from_base(require_current_run(store), rel)
                    return
                self.send_static(path, static_dir)
            except ReviewUiError as exc:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            except FileNotFoundError:
                self.send_error_json(HTTPStatus.NOT_FOUND, "File not found")
            except Exception as exc:  # pragma: no cover - defensive server boundary
                _log("error", "unhandled_get_error", path=self.path, error=str(exc), trace=traceback.format_exc())
                self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "An internal error occurred")

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                if parsed.path == "/api/review-decisions":
                    payload = self.read_json_body()
                    decisions = upsert_review_decisions(require_current_run(store), payload)
                    self.send_json(decisions)
                    return
                if parsed.path == "/api/jobs":
                    job = create_upload_job_from_request(self, store)
                    self.send_json(job, status=HTTPStatus.ACCEPTED)
                    return
                if parsed.path == "/api/clear-run":
                    store.set_current_run(None)
                    self.send_json({"ok": True, "has_run": False})
                    return
                self.send_error_json(HTTPStatus.NOT_FOUND, "Unknown API route")
            except ReviewUiError as exc:
                self.send_error_json(HTTPStatus.BAD_REQUEST, str(exc))
            except Exception as exc:  # pragma: no cover - defensive server boundary
                _log("error", "unhandled_post_error", path=parsed.path, error=str(exc), trace=traceback.format_exc())
                self.send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "An internal error occurred")

        def do_OPTIONS(self) -> None:  # noqa: N802
            origin = _allowed_origin()
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def read_json_body(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or "0")
            if length <= 0:
                return {}
            if length > MAX_JSON_BODY_BYTES:
                raise ReviewUiError(f"JSON request body exceeds {MAX_JSON_BODY_BYTES // 1024} KB limit")
            raw = self.rfile.read(length).decode("utf-8")
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ReviewUiError(f"Invalid JSON request body: {exc}") from exc
            if not isinstance(data, dict):
                raise ReviewUiError("JSON request body must be an object")
            return data

        def send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", _allowed_origin())
            self.end_headers()
            self.wfile.write(body)

        def send_error_json(self, status: HTTPStatus, message: str) -> None:
            self.send_json({"ok": False, "error": message}, status=status)

        def send_static(self, request_path: str, base_dir: Path) -> None:
            rel = "index.html" if request_path in {"/", ""} else request_path.lstrip("/")
            self.send_file_from_base(base_dir, rel)

        def send_file_from_base(self, base_dir: Path, rel_path: str) -> None:
            target = safe_child_path(base_dir, rel_path)
            if target.is_dir():
                target = target / "index.html"
            if not target.exists() or not target.is_file():
                raise FileNotFoundError(str(target))
            content_type, _ = mimetypes.guess_type(str(target))
            content_type = content_type or "application/octet-stream"
            body = target.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            if target.suffix.lower() in {".html", ".js", ".css", ".json"}:
                self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

    return ReviewUiRequestHandler


def require_current_run(store: ReviewJobStore) -> Path:
    run_dir = store.get_current_run()
    if run_dir is None:
        raise ReviewUiError("No active run is loaded. Upload Received and ERE PDFs, or start review-ui with --run-dir.")
    return run_dir


def create_upload_job_from_request(handler: BaseHTTPRequestHandler, store: ReviewJobStore) -> dict[str, Any]:
    client_ip = handler.client_address[0] if handler.client_address else "unknown"
    with _uploads_lock:
        if _active_uploads[client_ip] >= MAX_CONCURRENT_UPLOADS_PER_IP:
            raise ReviewUiError(
                f"Too many concurrent uploads from this address (max {MAX_CONCURRENT_UPLOADS_PER_IP})"
            )
        _active_uploads[client_ip] += 1
    try:
        return _create_upload_job_inner(handler, store, client_ip)
    finally:
        with _uploads_lock:
            _active_uploads[client_ip] = max(0, _active_uploads[client_ip] - 1)


def _create_upload_job_inner(handler: BaseHTTPRequestHandler, store: ReviewJobStore, client_ip: str) -> dict[str, Any]:
    content_length = int(handler.headers.get("Content-Length") or "0")
    if content_length <= 0:
        raise ReviewUiError("Upload request is empty")
    if content_length > MAX_UPLOAD_BYTES:
        raise ReviewUiError("Upload is too large for the local review UI server")
    content_type = handler.headers.get("Content-Type") or ""
    if not content_type.lower().startswith("multipart/form-data"):
        raise ReviewUiError("Expected multipart/form-data upload")

    job_id = make_job_id()
    job_dir = store.workspace_dir / job_id
    received_dir = job_dir / "input" / "received_records"
    ere_dir = job_dir / "input" / "ere_records"
    received_dir.mkdir(parents=True, exist_ok=True)
    ere_dir.mkdir(parents=True, exist_ok=True)

    form = parse_multipart_form(handler, content_type=content_type, content_length=content_length)
    settings = parse_job_settings(form)
    received_files = save_upload_group(form, "received_files", received_dir)
    ere_files = save_upload_group(form, "ere_files", ere_dir)
    if not received_files:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise ReviewUiError("Upload at least one Received Medical Records PDF")
    if not ere_files:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise ReviewUiError("Upload at least one ERE Medical Records PDF")

    job = store.create_job_record(
        job_dir=job_dir,
        received_files=[path.name for path in received_files],
        ere_files=[path.name for path in ere_files],
        settings=settings,
    )

    _log("info", "job_upload_received", job_id=job_id, client_ip=client_ip,
         received_count=len(received_files), ere_count=len(ere_files))

    if _sqs_mode():
        _dispatch_job_via_sqs(job_id=job_id, job_dir=job_dir, settings=settings)
    else:
        thread = threading.Thread(target=run_engine_job, args=(store, job_id), daemon=True)
        thread.start()

    return _sanitize_job_for_api(job)


def _dispatch_job_via_sqs(*, job_id: str, job_dir: Path, settings: dict[str, Any]) -> None:
    """Upload inputs to S3 (if configured) and enqueue the SQS job message."""
    input_prefix = ""
    output_prefix = ""

    if _s3_mode():
        input_prefix = _artifact_store_module.make_input_prefix(job_id)
        output_prefix = _artifact_store_module.make_output_prefix(job_id)
        _log("info", "s3_input_upload_start", job_id=job_id, prefix=input_prefix)
        _artifact_store_module.upload_dir(job_dir / "input", input_prefix)
        _log("info", "s3_input_upload_done", job_id=job_id)

    message = {
        "job_id": job_id,
        "input_prefix": input_prefix,
        "output_prefix": output_prefix,
        "engine_version": "v0.10.9",
        "config": {
            "embedding_reranker_enabled": settings.get("embedding_reranker_enabled", True),
            "embedding_reranker_min_confidence": settings.get("embedding_reranker_min_confidence", 0.80),
            "embedding_reranker_ocr_penalty": settings.get("embedding_reranker_ocr_penalty", 0.01),
            "embedding_reranker_same_doc_bonus": settings.get("embedding_reranker_same_doc_bonus", 0.03),
            "embedding_reranker_tesseract_bonus": settings.get("embedding_reranker_tesseract_bonus", 0.02),
            "embedding_reranker_action": settings.get("embedding_reranker_action", "demote"),
        },
    }
    _job_queue_module.send_job(message)
    _log("info", "job_enqueued", job_id=job_id, queue_url=os.environ.get("DUPE_SQS_QUEUE_URL", "local"))


def parse_job_settings(form: dict[str, list[UploadPart]]) -> dict[str, Any]:
    dpi_raw = form_value(form, "dpi", "150")
    try:
        dpi = int(dpi_raw)
    except ValueError as exc:
        raise ReviewUiError("DPI must be a number") from exc
    dpi = max(72, min(300, dpi))
    profiles = form_value(form, "tesseract_profiles", "standard").strip() or "standard"
    if not re.fullmatch(r"[A-Za-z0-9_, -]+", profiles):
        raise ReviewUiError("Tesseract profiles may only contain letters, numbers, comma, space, underscore, and hyphen")
    max_pages_raw = form_value(form, "openai_ocr_max_pages", "50")
    try:
        max_pages = int(max_pages_raw)
    except ValueError as exc:
        raise ReviewUiError("OpenAI fallback budget must be a number") from exc
    max_pages = max(1, min(500, max_pages))
    selection_mode = form_value(form, "openai_ocr_selection_mode", "weak_pages_or_vision_expected").strip() or "weak_pages_or_vision_expected"
    allowed_modes = {"candidate_based", "weak_pages", "vision_expected", "weak_pages_or_vision_expected"}
    if selection_mode not in allowed_modes:
        raise ReviewUiError("Unsupported OpenAI OCR fallback selection mode")
    return {
        "dpi": dpi,
        "ocr": True,
        "require_ocr": True,
        "openai_ocr": True,
        "require_openai_ocr": True,
        "openai_ocr_live": True,
        "openai_ocr_max_pages": max_pages,
        "openai_ocr_selection_mode": selection_mode,
        "tesseract_profiles": profiles.replace(" ", ""),
        "multipass_visual_all_pages": parse_bool(form_value(form, "multipass_visual_all_pages", "false")),
        "include_text_preview": parse_bool(form_value(form, "include_text_preview", "false")),
    }


def parse_multipart_form(handler: BaseHTTPRequestHandler, *, content_type: str, content_length: int) -> dict[str, list[UploadPart]]:
    raw_body = handler.rfile.read(content_length)
    header = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
    message = BytesParser(policy=email_default_policy).parsebytes(header + raw_body)
    if not message.is_multipart():
        raise ReviewUiError("Upload body is not multipart")
    form: dict[str, list[UploadPart]] = {}
    for part in message.iter_parts():
        if part.get_content_disposition() != "form-data":
            continue
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        form.setdefault(str(name), []).append(UploadPart(name=str(name), filename=filename, payload=payload))
    return form


def form_value(form: dict[str, list[UploadPart]], name: str, default: str = "") -> str:
    parts = form.get(name) or []
    if not parts:
        return default
    payload = parts[-1].payload
    if not payload:
        return default
    return payload.decode("utf-8", errors="replace")


def parse_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def save_upload_group(form: dict[str, list[UploadPart]], field_name: str, target_dir: Path) -> list[Path]:
    raw_items = form.get(field_name) or []
    saved: list[Path] = []
    used_names: set[str] = set()
    for item in raw_items:
        if not item.filename:
            continue
        filename = sanitize_upload_filename(item.filename)
        filename = dedupe_filename(filename, used_names)
        target = target_dir / filename
        target.write_bytes(item.payload)
        if target.stat().st_size <= 0:
            target.unlink(missing_ok=True)
            continue
        saved.append(target)
    return saved


def sanitize_upload_filename(filename: str) -> str:
    name = Path(str(filename).replace("\\", "/")).name.strip()
    if not name:
        raise ReviewUiError("Uploaded file is missing a filename")
    safe = re.sub(r"[^A-Za-z0-9._() -]+", "_", name)
    safe = safe.strip(" ._") or "upload.pdf"
    if Path(safe).suffix.lower() != PDF_SUFFIX:
        raise ReviewUiError(f"Only PDF uploads are supported: {name}")
    return safe


def dedupe_filename(filename: str, used_names: set[str]) -> str:
    candidate = filename
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    counter = 2
    while candidate.lower() in used_names:
        candidate = f"{stem}_{counter}{suffix}"
        counter += 1
    used_names.add(candidate.lower())
    return candidate


def run_engine_job(store: ReviewJobStore, job_id: str) -> None:
    try:
        job = store.get_job(job_id)
        job_dir = Path(job["job_dir"])
        received_dir = job_dir / "input" / "received_records"
        ere_dir = job_dir / "input" / "ere_records"
        work_dir = Path(job["work_dir"])
        run_dir = Path(job["run_dir"])
        results_path = Path(job["results_path"])
        settings = dict(job.get("settings") or {})
        command = build_engine_job_command(
            received_dir=received_dir,
            ere_dir=ere_dir,
            work_dir=work_dir,
            run_dir=run_dir,
            results_path=results_path,
            settings=settings,
        )
        _log("info", "job_started", job_id=job_id, mode="local_subprocess")
        store.update_job(job_id, status="running", stage="running_engine", command=command)
        env = os.environ.copy()
        src_root = str(Path(__file__).resolve().parents[1])
        env["PYTHONPATH"] = src_root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        completed = subprocess.run(
            command,
            cwd=str(job_dir),
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        stdout_tail = tail_text(completed.stdout)
        stderr_tail = tail_text(completed.stderr)
        if completed.returncode != 0:
            _log("error", "job_failed", job_id=job_id, returncode=completed.returncode, mode="local_subprocess")
            store.update_job(
                job_id,
                status="failed",
                stage="failed",
                finished_at=utc_now(),
                stdout_tail=stdout_tail,
                stderr_tail=stderr_tail,
                error=f"Engine exited with status {completed.returncode}",
            )
            return
        validate_run_dir(run_dir)
        store.set_current_run(run_dir)
        _log("info", "job_completed", job_id=job_id, mode="local_subprocess")
        store.update_job(
            job_id,
            status="succeeded",
            stage="completed",
            finished_at=utc_now(),
            stdout_tail=stdout_tail,
            stderr_tail=stderr_tail,
            error=None,
        )
    except Exception as exc:
        try:
            store.update_job(job_id, status="failed", stage="failed", finished_at=utc_now(), error=str(exc))
        except Exception as store_exc:
            print(f"[review-ui] ERROR: job {job_id} failed but store update also failed: {store_exc}", file=sys.stderr)


def build_engine_job_command(
    *,
    received_dir: Path,
    ere_dir: Path,
    work_dir: Path,
    run_dir: Path,
    results_path: Path,
    settings: dict[str, Any],
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "dupe_engine.cli",
        "compare-ab",
        str(received_dir),
        str(ere_dir),
        "--work-dir",
        str(work_dir),
        "--out",
        str(results_path),
        "--run-dir",
        str(run_dir),
        "--progress-dir",
        str(run_dir),
        "--dpi",
        str(settings.get("dpi") or 150),
    ]
    command.extend(["--ocr", "--require-ocr", "--openai-ocr", "--openai-ocr-live", "--require-openai-ocr"])
    command.extend(["--openai-ocr-max-pages", str(settings.get("openai_ocr_max_pages") or 50)])
    command.extend(["--openai-ocr-selection-mode", str(settings.get("openai_ocr_selection_mode") or "weak_pages_or_vision_expected")])
    profiles = str(settings.get("tesseract_profiles") or "standard")
    if profiles:
        command.extend(["--tesseract-profiles", profiles])
    if settings.get("multipass_visual_all_pages"):
        command.append("--multipass-visual-all-pages")
    if settings.get("include_text_preview"):
        command.append("--include-text-preview")
    return command


def tail_text(text: str, limit: int = 8000) -> str:
    if len(text) <= limit:
        return text
    return text[-limit:]


def make_job_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("job_%Y%m%d_%H%M%S")
    return f"{stamp}_{uuid.uuid4().hex[:8]}"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_child_path(base_dir: Path, rel_path: str) -> Path:
    rel = unquote(rel_path).replace("\\", "/")
    rel = posixpath.normpath("/" + rel).lstrip("/")
    if rel.startswith("../") or rel == "..":
        raise ReviewUiError("Path traversal is not allowed")
    target = (base_dir / rel).resolve()
    base_resolved = base_dir.resolve()
    try:
        common = os.path.commonpath([str(base_resolved), str(target)])
    except ValueError as exc:
        raise ReviewUiError("Invalid path") from exc
    if common != str(base_resolved):
        raise ReviewUiError("Path escapes the configured base folder")
    return target


def load_job_progress(run_dir: Path) -> dict[str, Any] | None:
    progress_path = run_dir / "progress.json"
    if not progress_path.exists():
        return None
    try:
        progress = load_json(progress_path)
    except Exception:
        return None
    events_path = run_dir / "progress_events.jsonl"
    events: list[dict[str, Any]] = []
    if events_path.exists():
        try:
            lines = events_path.read_text(encoding="utf-8").splitlines()[-12:]
            for line in lines:
                if line.strip():
                    events.append(json.loads(line))
        except Exception:
            events = []
    progress["events_tail"] = events
    return progress


def load_run_payload(run_dir: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": "dupe_engine_review_ui_payload_v0_9_5",
        "has_run": True,
        "run_dir_name": run_dir.name,
        "run_dir": str(run_dir),
        "manifest": load_json(run_dir / "run_manifest.json"),
        "pages": load_json(run_dir / "pages.json"),
        "candidates": load_json(run_dir / "candidates.json"),
        "capabilities": load_json(run_dir / "capabilities.json"),
        "metrics": load_json(run_dir / "metrics.json"),
        "review_decisions": load_review_decisions(run_dir),
    }
    truth_path = run_dir / "truth_eval.json"
    payload["truth_eval"] = load_json(truth_path) if truth_path.exists() else None
    candidate_pairs_path = run_dir / "candidate_pairs.json"
    payload["candidate_pairs"] = load_json(candidate_pairs_path) if candidate_pairs_path.exists() else None
    fallback_path = run_dir / "fallback_audit.json"
    payload["fallback_audit"] = load_json(fallback_path) if fallback_path.exists() else None
    payload["progress"] = load_job_progress(run_dir)
    return payload


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_review_decisions(run_dir: Path) -> dict[str, Any]:
    path = run_dir / "review_decisions.json"
    if not path.exists():
        write_json_atomic(path, {"schema_version": "dupe_engine_review_decisions_v0_8_6", "decisions": []})
    data = load_json(path)
    if not isinstance(data, dict):
        raise ReviewUiError("review_decisions.json must be a JSON object")
    data.setdefault("schema_version", "dupe_engine_review_decisions_v0_8_6")
    data.setdefault("decisions", [])
    if not isinstance(data["decisions"], list):
        raise ReviewUiError("review_decisions.json decisions must be a list")
    return data


_MAX_REVIEWER_NOTE_LEN = 2000
_MAX_REVIEWER_NAME_LEN = 200


def upsert_review_decisions(run_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    current = load_review_decisions(run_dir)

    # Load known candidate IDs for validation.
    candidates_path = run_dir / "candidates.json"
    known_candidate_ids: set[str] | None = None
    if candidates_path.exists():
        try:
            candidates_data = load_json(candidates_path)
            if isinstance(candidates_data, list):
                known_candidate_ids = {str(c.get("candidate_id", "")) for c in candidates_data if isinstance(c, dict)}
            elif isinstance(candidates_data, dict):
                items = candidates_data.get("candidates") or candidates_data.get("items") or []
                known_candidate_ids = {str(c.get("candidate_id", "")) for c in items if isinstance(c, dict)}
        except Exception:
            pass

    incoming: list[dict[str, Any]]
    if "decision" in payload:
        decision = payload["decision"]
        if not isinstance(decision, dict):
            raise ReviewUiError("decision must be an object")
        incoming = [decision]
    elif "decisions" in payload:
        decisions = payload["decisions"]
        if not isinstance(decisions, list):
            raise ReviewUiError("decisions must be a list")
        incoming = decisions
    else:
        raise ReviewUiError("Expected decision or decisions in request body")

    by_candidate: dict[str, dict[str, Any]] = {}
    for existing in current.get("decisions", []):
        if isinstance(existing, dict) and existing.get("candidate_id"):
            by_candidate[str(existing["candidate_id"])] = existing

    saved_count = 0
    for raw in incoming:
        normalized = normalize_decision(raw)
        cid = normalized["candidate_id"]
        if known_candidate_ids is not None and cid not in known_candidate_ids:
            raise ReviewUiError(f"decision.candidate_id {cid!r} not found in this run")
        by_candidate[cid] = normalized
        saved_count += 1

    updated = {
        "schema_version": current.get("schema_version", "dupe_engine_review_decisions_v0_8_6"),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "decisions": sorted(by_candidate.values(), key=lambda item: str(item.get("reviewed_at", ""))),
    }
    write_json_atomic(run_dir / "review_decisions.json", updated)
    _log("info", "review_decisions_saved",
         run_dir=run_dir.name, saved=saved_count,
         total_decisions=len(updated["decisions"]))
    return updated


def normalize_decision(raw: dict[str, Any]) -> dict[str, Any]:
    candidate_id = str(raw.get("candidate_id") or "").strip()
    if not candidate_id:
        raise ReviewUiError("decision.candidate_id is required")
    human_label = str(raw.get("human_label") or "").strip()
    if human_label not in ALLOWED_REVIEW_LABELS:
        allowed = ", ".join(sorted(ALLOWED_REVIEW_LABELS))
        raise ReviewUiError(f"decision.human_label must be one of: {allowed}")
    # Always use a server-generated timestamp — never trust client-supplied values.
    reviewed_at = datetime.now(timezone.utc).isoformat()
    reviewer_note = str(raw.get("reviewer_note") or "")[:_MAX_REVIEWER_NOTE_LEN]
    reviewer_name = str(raw.get("reviewer_name") or "")[:_MAX_REVIEWER_NAME_LEN]
    return {
        "candidate_id": candidate_id,
        "human_label": human_label,
        "reviewer_note": reviewer_note,
        "reviewer_name": reviewer_name,
        "reviewed_at": reviewed_at,
    }


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
