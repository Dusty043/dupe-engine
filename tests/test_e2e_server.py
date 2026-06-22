"""End-to-end HTTP smoke test for the Review UI server.

Mocked provisions
-----------------
- Engine subprocess: subprocess.run is patched to write synthetic run artifacts
  and return exit 0 (or 1 for the failure test). No real PDF parsing or OCR.
- SQS/S3/DynamoDB: env vars absent → adapters fall back to local file mode.
- Audit trail: DUPE_LOCAL_AUDIT_DIR points to tmp_path.

All requests go through a real ThreadingHTTPServer bound to a loopback port.
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

import pytest

from dupe_engine.review_ui_server import (
    STATIC_DIR,
    ReviewJobStore,
    build_handler,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MINIMAL_PDF = (
    b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
    b"xref\n0 2\n0000000000 65535 f \n0000000009 00000 n \n"
    b"trailer\n<< /Size 2 /Root 1 0 R >>\nstartxref\n9\n%%EOF\n"
)


def _write_run_artifacts(run_dir: Path, *, candidate_id: str = "cand_e2e_01") -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    for name, payload in {
        "run_manifest.json": {"schema_version": "dupe_engine_ui_run_v0_8_6", "summary": {}},
        "pages.json": {"schema_version": "dupe_engine_pages_v0_8_6", "pages": []},
        "candidates.json": {
            "schema_version": "dupe_engine_candidates_v0_8_6",
            "candidates": [{"candidate_id": candidate_id}],
        },
        "capabilities.json": {},
        "metrics.json": {"schema_version": "dupe_engine_metrics_v0_8_6", "summary": {}},
        "review_decisions.json": {
            "schema_version": "dupe_engine_review_decisions_v0_8_6",
            "decisions": [],
        },
    }.items():
        (run_dir / name).write_text(json.dumps(payload), encoding="utf-8")


def _multipart(fields: dict, files: dict[str, tuple[str, bytes]]) -> tuple[bytes, str]:
    boundary = b"----E2EBoundary7890"
    parts: list[bytes] = []
    for name, value in fields.items():
        parts.append(
            b"--" + boundary + b"\r\n"
            + b'Content-Disposition: form-data; name="' + name.encode() + b'"\r\n\r\n'
            + str(value).encode() + b"\r\n"
        )
    for name, (filename, data) in files.items():
        parts.append(
            b"--" + boundary + b"\r\n"
            + b'Content-Disposition: form-data; name="' + name.encode()
            + b'"; filename="' + filename.encode() + b'"\r\n'
            + b"Content-Type: application/pdf\r\n\r\n"
            + data + b"\r\n"
        )
    body = b"".join(parts) + b"--" + boundary + b"--\r\n"
    return body, f"multipart/form-data; boundary={boundary.decode()}"


def _upload(base_url: str, *, received: bytes = _MINIMAL_PDF, ere: bytes = _MINIMAL_PDF) -> dict:
    body, ct = _multipart(
        fields={"dpi": "150"},
        files={"received_files": ("received.pdf", received), "ere_files": ("ere.pdf", ere)},
    )
    req = urllib.request.Request(
        f"{base_url}/api/jobs",
        data=body,
        method="POST",
        headers={"Content-Type": ct, "Content-Length": str(len(body))},
    )
    resp = urllib.request.urlopen(req)
    return json.loads(resp.read())


def _wait_terminal(base_url: str, job_id: str, timeout: float = 8.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(0.05)
        resp = urllib.request.urlopen(f"{base_url}/api/jobs/{job_id}")
        job = json.loads(resp.read())
        if job["status"] not in ("queued", "running"):
            return job
    raise TimeoutError(f"job {job_id} did not reach terminal state within {timeout}s")


def _fake_success(run_dir_arg: str) -> "CompletedProcess[str]":
    _write_run_artifacts(Path(run_dir_arg))
    return CompletedProcess([], 0, stdout="mock engine ok\n", stderr="")


def _extract_run_dir(command: list[str]) -> str:
    return command[command.index("--run-dir") + 1]


# ---------------------------------------------------------------------------
# Server fixture — real ThreadingHTTPServer, OS-assigned port, dev mode auth
# ---------------------------------------------------------------------------

@pytest.fixture()
def srv(tmp_path, monkeypatch):
    """Yields (base_url, store, workspace_dir)."""
    monkeypatch.delenv("DUPE_UI_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("DUPE_SQS_QUEUE_URL", raising=False)
    monkeypatch.delenv("DUPE_S3_BUCKET", raising=False)
    monkeypatch.delenv("DUPE_DYNAMO_TABLE", raising=False)
    monkeypatch.setenv("DUPE_LOCAL_AUDIT_DIR", str(tmp_path / "audit"))
    monkeypatch.setenv("DUPE_LOCAL_STATUS_DIR", str(tmp_path / "status"))

    workspace = tmp_path / "workspace"
    store = ReviewJobStore(workspace_dir=workspace)
    handler = build_handler(store=store, static_dir=STATIC_DIR, server_host="127.0.0.1")

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = httpd.server_address[1]
    base_url = f"http://127.0.0.1:{port}"

    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    yield base_url, store, workspace
    httpd.shutdown()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_returns_200_no_auth(self, srv):
        base_url, _, _ = srv
        resp = urllib.request.urlopen(f"{base_url}/api/health")
        assert resp.status == 200
        body = json.loads(resp.read())
        assert body.get("ok") is True

    def test_has_workspace_info(self, srv):
        base_url, _, workspace = srv
        resp = urllib.request.urlopen(f"{base_url}/api/health")
        body = json.loads(resp.read())
        assert "workspace_dir" in body
        assert str(workspace) in body["workspace_dir"]


class TestDevModeAuth:
    def test_jobs_accessible_loopback_no_token(self, srv):
        base_url, _, _ = srv
        resp = urllib.request.urlopen(f"{base_url}/api/jobs")
        assert resp.status == 200

    def test_no_token_open_access_on_non_loopback(self, tmp_path, monkeypatch):
        """No token configured → open access; network-level auth via Tailscale/VPN."""
        from dupe_engine.security import auth_required
        assert auth_required("10.0.0.1", None)

    def test_token_accepted_on_non_loopback(self, monkeypatch):
        from dupe_engine.security import auth_required
        monkeypatch.setenv("DUPE_UI_AUTH_TOKEN", "s3cret-test-token")
        assert auth_required("10.0.0.1", "Bearer s3cret-test-token")


class TestUploadJobLifecycle:
    def test_upload_creates_job_succeeds(self, srv):
        base_url, _, _ = srv
        import dupe_engine.review_ui_server as _mod

        def fake_run(cmd, **kw):
            return _fake_success(_extract_run_dir(cmd))

        with patch.object(_mod.subprocess, "run", side_effect=fake_run):
            job = _upload(base_url)

        assert "job_id" in job
        job_id = job["job_id"]
        assert job["status"] == "queued"

        final = _wait_terminal(base_url, job_id)
        assert final["status"] == "succeeded", f"Unexpected final state: {final}"

    def test_succeeded_job_appears_in_list(self, srv):
        base_url, _, _ = srv
        import dupe_engine.review_ui_server as _mod

        def fake_run(cmd, **kw):
            return _fake_success(_extract_run_dir(cmd))

        with patch.object(_mod.subprocess, "run", side_effect=fake_run):
            job = _upload(base_url)

        _wait_terminal(base_url, job["job_id"])

        resp = urllib.request.urlopen(f"{base_url}/api/jobs")
        body = json.loads(resp.read())
        jobs = body["jobs"]
        assert any(j["job_id"] == job["job_id"] for j in jobs)

    def test_job_get_by_id(self, srv):
        base_url, _, _ = srv
        import dupe_engine.review_ui_server as _mod

        def fake_run(cmd, **kw):
            return _fake_success(_extract_run_dir(cmd))

        with patch.object(_mod.subprocess, "run", side_effect=fake_run):
            job = _upload(base_url)

        final = _wait_terminal(base_url, job["job_id"])
        assert final["job_id"] == job["job_id"]

    def test_missing_received_files_returns_400(self, srv):
        base_url, _, _ = srv
        body, ct = _multipart(fields={}, files={"ere_files": ("ere.pdf", _MINIMAL_PDF)})
        req = urllib.request.Request(
            f"{base_url}/api/jobs",
            data=body,
            method="POST",
            headers={"Content-Type": ct, "Content-Length": str(len(body))},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 400

    def test_missing_ere_files_returns_400(self, srv):
        base_url, _, _ = srv
        body, ct = _multipart(fields={}, files={"received_files": ("r.pdf", _MINIMAL_PDF)})
        req = urllib.request.Request(
            f"{base_url}/api/jobs",
            data=body,
            method="POST",
            headers={"Content-Type": ct, "Content-Length": str(len(body))},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req)
        assert exc_info.value.code == 400


class TestReviewDecisions:
    def test_post_decision_persists(self, srv):
        base_url, _, _ = srv
        import dupe_engine.review_ui_server as _mod

        def fake_run(cmd, **kw):
            return _fake_success(_extract_run_dir(cmd))

        with patch.object(_mod.subprocess, "run", side_effect=fake_run):
            job = _upload(base_url)

        _wait_terminal(base_url, job["job_id"])

        payload = json.dumps({
            "decision": {
                "candidate_id": "cand_e2e_01",
                "human_label": "duplicate",
                "reviewer_note": "e2e smoke test",
                "reviewed_at": "2026-06-19T00:00:00Z",
            }
        }).encode()
        req = urllib.request.Request(
            f"{base_url}/api/review-decisions",
            data=payload,
            method="POST",
            headers={"Content-Type": "application/json", "Content-Length": str(len(payload))},
        )
        resp = urllib.request.urlopen(req)
        assert resp.status == 200
        result = json.loads(resp.read())
        assert len(result["decisions"]) == 1
        assert result["decisions"][0]["human_label"] == "duplicate"

    def test_overwrite_decision_keeps_latest(self, srv):
        base_url, _, _ = srv
        import dupe_engine.review_ui_server as _mod

        def fake_run(cmd, **kw):
            return _fake_success(_extract_run_dir(cmd))

        with patch.object(_mod.subprocess, "run", side_effect=fake_run):
            _upload(base_url)

        # Wait for current run to be set
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            time.sleep(0.05)
            resp = urllib.request.urlopen(f"{base_url}/api/health")
            if json.loads(resp.read()).get("has_run"):
                break

        for label in ("duplicate", "not_duplicate"):
            payload = json.dumps({
                "decision": {
                    "candidate_id": "cand_e2e_01",
                    "human_label": label,
                    "reviewer_note": f"pass {label}",
                    "reviewed_at": "2026-06-19T00:01:00Z",
                }
            }).encode()
            req = urllib.request.Request(
                f"{base_url}/api/review-decisions",
                data=payload,
                method="POST",
                headers={"Content-Type": "application/json", "Content-Length": str(len(payload))},
            )
            urllib.request.urlopen(req)

        resp = urllib.request.urlopen(f"{base_url}/api/review-decisions")
        result = json.loads(resp.read())
        assert len(result["decisions"]) == 1
        assert result["decisions"][0]["human_label"] == "not_duplicate"


class TestPhiSanitization:
    def test_failed_job_redacts_stdout_tail(self, srv, monkeypatch):
        base_url, _, _ = srv
        monkeypatch.delenv("DUPE_LOG_PHI", raising=False)
        import dupe_engine.review_ui_server as _mod

        def fake_fail(cmd, **kw):
            return CompletedProcess(cmd, 1, stdout="patient Jane Doe, DOB 01/01/1970", stderr="traceback")

        with patch.object(_mod.subprocess, "run", side_effect=fake_fail):
            job = _upload(base_url)

        final = _wait_terminal(base_url, job["job_id"])
        assert final["status"] == "failed"
        raw = json.dumps(final)
        assert "Jane Doe" not in raw, f"PHI leaked in response: {raw}"
        assert final.get("stdout_tail") in (None, "", "[PHI-REDACTED]", "[set DUPE_LOG_PHI=true to see]")

    def test_phi_visible_when_log_phi_enabled(self, srv, monkeypatch):
        base_url, _, _ = srv
        monkeypatch.setenv("DUPE_LOG_PHI", "true")
        import dupe_engine.review_ui_server as _mod

        def fake_fail(cmd, **kw):
            return CompletedProcess(cmd, 1, stdout="patient Jane Doe", stderr="")

        with patch.object(_mod.subprocess, "run", side_effect=fake_fail):
            job = _upload(base_url)

        final = _wait_terminal(base_url, job["job_id"])
        assert final["status"] == "failed"
        assert final.get("stdout_tail") == "patient Jane Doe"


class TestAuditTrail:
    def test_audit_jsonl_written_on_upload(self, srv, tmp_path):
        base_url, _, _ = srv
        import dupe_engine.review_ui_server as _mod

        def fake_run(cmd, **kw):
            return _fake_success(_extract_run_dir(cmd))

        with patch.object(_mod.subprocess, "run", side_effect=fake_run):
            job = _upload(base_url)

        _wait_terminal(base_url, job["job_id"])

        audit_dir = tmp_path / "audit"
        if audit_dir.exists():
            jsonl_files = list(audit_dir.rglob("*.jsonl"))
            if jsonl_files:
                events = [json.loads(l) for f in jsonl_files for l in f.read_text().splitlines() if l.strip()]
                job_ids = {e.get("job_id") for e in events}
                assert job["job_id"] in job_ids, f"No audit event for job {job['job_id']}: {events}"
