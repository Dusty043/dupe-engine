"""HIPAA remediation smoke-tests.

Covers the key HIPAA §164.312(a)/(b)/(d) controls added in the
security + HIPAA hardening pass:

 - Phase 0/4: Bearer-token auth (security.auth_required)
 - Phase 1: BAA endpoint assertion (security.assert_baa_endpoint)
 - Phase 2/8: PHI redaction in logs (log.log / log.log_exception)
 - Phase 5: Audit trail (audit.record_event)
 - Phase 6: S3 SSE-KMS args (artifact_store._sse_extra_args)
 - Phase 3: Server-side text-preview gate (review_ui_server.parse_job_settings)
 - Phase 4: Auth gate in HTTP handler (build_handler)
 - Phase 8: PHI sanitization in API job records (_sanitize_job_for_api)
"""
from __future__ import annotations

import io
import json
import os
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _setenv(env: dict[str, str]):
    """Context manager: set env vars, restore on exit."""
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        old = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            yield
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
    return _ctx()


# ---------------------------------------------------------------------------
# Phase 0/4 — auth_required
# ---------------------------------------------------------------------------

class TestAuthRequired(unittest.TestCase):
    def setUp(self):
        os.environ.pop("DUPE_UI_AUTH_TOKEN", None)

    def tearDown(self):
        os.environ.pop("DUPE_UI_AUTH_TOKEN", None)

    def test_dev_mode_loopback_no_token(self):
        from dupe_engine.security import auth_required
        # Local dev: loopback + no token → allow
        self.assertTrue(auth_required("127.0.0.1", None))
        self.assertTrue(auth_required("localhost", None))
        self.assertTrue(auth_required("::1", None))

    def test_no_token_open_access(self):
        from dupe_engine.security import auth_required
        # No token configured → open access; network-level control via Tailscale/VPN
        self.assertTrue(auth_required("0.0.0.0", None))
        self.assertTrue(auth_required("10.0.0.1", None))

    def test_correct_token_passes(self):
        from dupe_engine.security import auth_required
        os.environ["DUPE_UI_AUTH_TOKEN"] = "secret123"
        self.assertTrue(auth_required("0.0.0.0", "Bearer secret123"))
        self.assertTrue(auth_required("127.0.0.1", "Bearer secret123"))

    def test_wrong_token_denied(self):
        from dupe_engine.security import auth_required
        os.environ["DUPE_UI_AUTH_TOKEN"] = "secret123"
        self.assertFalse(auth_required("0.0.0.0", "Bearer wrong"))
        self.assertFalse(auth_required("0.0.0.0", None))

    def test_missing_bearer_scheme_denied(self):
        from dupe_engine.security import auth_required
        os.environ["DUPE_UI_AUTH_TOKEN"] = "secret123"
        self.assertFalse(auth_required("0.0.0.0", "Basic secret123"))

    def test_timing_safe_compare(self):
        # Even with a correct token, a wrong token must not pass
        from dupe_engine.security import auth_required
        os.environ["DUPE_UI_AUTH_TOKEN"] = "aaaaaaaaaa"
        self.assertFalse(auth_required("127.0.0.1", "Bearer aaaaaaaaab"))


# ---------------------------------------------------------------------------
# Phase 1 — assert_baa_endpoint
# ---------------------------------------------------------------------------

class TestBaaAssertion(unittest.TestCase):
    def _make_config(self, **kwargs) -> Any:
        from dupe_engine.config import EngineConfig
        return EngineConfig.from_env()

    def test_default_openai_allowed(self):
        from dupe_engine.security import assert_baa_endpoint
        from dupe_engine.config import EngineConfig
        cfg = EngineConfig.from_env()
        # Should not raise — api.openai.com is the default allowed host
        assert_baa_endpoint(cfg)

    def test_unknown_host_warns_by_default(self):
        import warnings
        from dupe_engine.security import assert_baa_endpoint
        from dupe_engine.config import EngineConfig
        with _setenv({"DUPE_OPENAI_BASE_URL": "https://my-proxy.internal/v1"}):
            cfg = EngineConfig.from_env()
            with self.assertWarns(UserWarning):
                assert_baa_endpoint(cfg)

    def test_unknown_host_rejected_in_strict_mode(self):
        from dupe_engine.security import assert_baa_endpoint
        from dupe_engine.config import EngineConfig
        with _setenv({
            "DUPE_OPENAI_BASE_URL": "https://my-proxy.internal/v1",
            "DUPE_STRICT_COMPLIANCE": "true",
        }):
            cfg = EngineConfig.from_env()
            with self.assertRaises(SystemExit):
                assert_baa_endpoint(cfg)

    def test_custom_allowed_host_passes(self):
        from dupe_engine.security import assert_baa_endpoint
        from dupe_engine.config import EngineConfig
        with _setenv({
            "DUPE_OPENAI_BASE_URL": "https://my-proxy.internal/v1",
            "DUPE_OPENAI_BAA_ALLOWED_HOSTS": "my-proxy.internal,api.openai.com",
        }):
            cfg = EngineConfig.from_env()
            assert_baa_endpoint(cfg)


# ---------------------------------------------------------------------------
# Phase 2/8 — PHI redaction in logs
# ---------------------------------------------------------------------------

class TestLogPhiRedaction(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("DUPE_LOG_PHI", None)

    def _capture_log(self, **kwargs) -> dict:
        import io, sys
        from dupe_engine.log import log
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            log("info", "test_event", **kwargs)
        finally:
            sys.stdout = old_stdout
        return json.loads(buf.getvalue())

    def test_phi_keys_redacted_by_default(self):
        record = self._capture_log(filename="patient_john_doe.pdf", error="patient name here")
        self.assertEqual(record["filename"], "[PHI-REDACTED]")
        self.assertEqual(record["error"], "[PHI-REDACTED]")

    def test_phi_keys_pass_through_when_enabled(self):
        os.environ["DUPE_LOG_PHI"] = "true"
        record = self._capture_log(filename="patient.pdf", error="some error")
        self.assertEqual(record["filename"], "patient.pdf")
        self.assertEqual(record["error"], "some error")

    def test_credentials_always_redacted(self):
        record = self._capture_log(note="key is sk-ABCDEFGHIJ1234567890abcde")
        self.assertNotIn("sk-", record.get("note", ""))
        self.assertIn("[REDACTED]", record["note"])

    def test_log_exception_hides_message_by_default(self):
        import io, sys
        from dupe_engine.log import log_exception
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            try:
                raise ValueError("patient SSN: 123-45-6789")
            except ValueError as exc:
                log_exception("error", "test_exc", exc)
        finally:
            sys.stdout = old_stdout
        record = json.loads(buf.getvalue())
        self.assertNotIn("SSN", str(record))
        self.assertIn("error_type", record)
        self.assertEqual(record["error_type"], "ValueError")

    def test_log_exception_shows_message_when_phi_enabled(self):
        import io, sys
        from dupe_engine.log import log_exception
        os.environ["DUPE_LOG_PHI"] = "true"
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            try:
                raise ValueError("something went wrong")
            except ValueError as exc:
                log_exception("error", "test_exc", exc)
        finally:
            sys.stdout = old_stdout
        record = json.loads(buf.getvalue())
        self.assertEqual(record["error"], "something went wrong")


# ---------------------------------------------------------------------------
# Phase 5 — Audit trail
# ---------------------------------------------------------------------------

class TestAuditTrail(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("DUPE_DYNAMO_TABLE", None)
        os.environ.pop("DUPE_LOCAL_AUDIT_DIR", None)

    def test_local_audit_write(self, tmp_path: Path | None = None):
        import tempfile
        from dupe_engine.audit import record_event
        with tempfile.TemporaryDirectory() as d:
            os.environ["DUPE_LOCAL_AUDIT_DIR"] = d
            record_event(
                job_id="testjob123",
                action="read",
                actor="127.0.0.1",
                resource="pages.json",
                outcome="access",
            )
            audit_path = Path(d) / "audit.jsonl"
            self.assertTrue(audit_path.exists())
            entries = [json.loads(line) for line in audit_path.read_text().splitlines() if line.strip()]
            self.assertEqual(len(entries), 1)
            e = entries[0]
            self.assertEqual(e["job_id"], "testjob123")
            self.assertEqual(e["action"], "read")
            self.assertEqual(e["actor"], "127.0.0.1")
            self.assertIn("event_ts_id", e)

    def test_audit_fail_open(self):
        from dupe_engine.audit import record_event
        # No crash even if write fails
        os.environ["DUPE_DYNAMO_TABLE"] = "nonexistent-table"
        with patch("dupe_engine.audit._write_dynamo", side_effect=RuntimeError("boto3 unavailable")):
            try:
                record_event(job_id="x", action="read", actor="test", resource="r", outcome="access")
            except Exception as exc:  # pragma: no cover
                self.fail(f"audit.record_event raised: {exc}")

    def test_audit_entries_are_unique(self):
        import tempfile
        from dupe_engine.audit import record_event
        with tempfile.TemporaryDirectory() as d:
            os.environ["DUPE_LOCAL_AUDIT_DIR"] = d
            for _ in range(5):
                record_event(job_id="j", action="read", actor="a", resource="r", outcome="ok")
            lines = (Path(d) / "audit.jsonl").read_text().splitlines()
            event_ids = [json.loads(line)["event_ts_id"] for line in lines if line.strip()]
            self.assertEqual(len(event_ids), len(set(event_ids)))


# ---------------------------------------------------------------------------
# Phase 6 — S3 SSE-KMS
# ---------------------------------------------------------------------------

class TestSseKms(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("DUPE_S3_KMS_KEY_ID", None)

    def test_default_aws_kms(self):
        from dupe_engine.artifact_store import _sse_extra_args
        args = _sse_extra_args()
        self.assertEqual(args["ServerSideEncryption"], "aws:kms")
        self.assertNotIn("SSEKMSKeyId", args)

    def test_custom_kms_key(self):
        from dupe_engine.artifact_store import _sse_extra_args
        os.environ["DUPE_S3_KMS_KEY_ID"] = "arn:aws:kms:us-east-1:123456789012:key/abcd"
        args = _sse_extra_args()
        self.assertEqual(args["SSEKMSKeyId"], "arn:aws:kms:us-east-1:123456789012:key/abcd")


# ---------------------------------------------------------------------------
# Phase 3 — server-side text preview gate
# ---------------------------------------------------------------------------

class TestTextPreviewGate(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("DUPE_INCLUDE_TEXT_PREVIEW", None)

    def _form_with(self, **extra) -> dict:
        from dupe_engine.review_ui_server import UploadPart
        base = {
            "dpi": [UploadPart(name="dpi", filename=None, payload=b"150")],
            "tesseract_profiles": [UploadPart(name="tesseract_profiles", filename=None, payload=b"standard")],
            "openai_ocr_max_pages": [UploadPart(name="openai_ocr_max_pages", filename=None, payload=b"50")],
        }
        base.update(extra)
        return base

    def test_client_value_ignored(self):
        from dupe_engine.review_ui_server import UploadPart, parse_job_settings
        form = self._form_with(
            include_text_preview=[UploadPart(name="include_text_preview", filename=None, payload=b"true")]
        )
        settings = parse_job_settings(form)
        # Client sent true but server env not set → should be False
        self.assertFalse(settings["include_text_preview"])

    def test_server_env_controls_value(self):
        from dupe_engine.review_ui_server import UploadPart, parse_job_settings
        os.environ["DUPE_INCLUDE_TEXT_PREVIEW"] = "true"
        form = self._form_with(
            include_text_preview=[UploadPart(name="include_text_preview", filename=None, payload=b"false")]
        )
        settings = parse_job_settings(form)
        # Server env is true regardless of client value
        self.assertTrue(settings["include_text_preview"])


# ---------------------------------------------------------------------------
# Phase 4 — HTTP auth gate in review_ui_server
# ---------------------------------------------------------------------------

class TestHttpAuthGate(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("DUPE_UI_AUTH_TOKEN", None)

    def _make_handler_instance(self, path: str, method: str = "GET", token: str | None = None):
        """Build a minimal ReviewUiRequestHandler-like object for testing."""
        import tempfile
        from dupe_engine.review_ui_server import ReviewJobStore, build_handler
        with tempfile.TemporaryDirectory() as d:
            store = ReviewJobStore(workspace_dir=Path(d))
            HandlerClass = build_handler(
                store=store,
                static_dir=Path("/nonexistent"),
                server_host="0.0.0.0",
            )
        response_buf = io.BytesIO()
        handler = HandlerClass.__new__(HandlerClass)
        handler.path = path
        handler.command = method
        handler.client_address = ("10.0.0.1", 12345)
        handler.headers = {"Authorization": f"Bearer {token}"} if token else {}
        handler.rfile = io.BytesIO()
        # Capture response
        handler.wfile = response_buf
        handler._status = None
        handler._headers_sent = []

        def mock_send_response(code, message=None):
            handler._status = code
        def mock_send_header(k, v):
            handler._headers_sent.append((k, v))
        def mock_end_headers():
            pass

        handler.send_response = mock_send_response
        handler.send_header = mock_send_header
        handler.end_headers = mock_end_headers
        handler.send_json = lambda payload, status=None: None  # swallow
        return handler

    def test_api_route_requires_auth(self):
        os.environ["DUPE_UI_AUTH_TOKEN"] = "pilot-token"
        handler = self._make_handler_instance("/api/jobs")
        self.assertFalse(handler._is_authenticated())

    def test_api_route_passes_with_token(self):
        os.environ["DUPE_UI_AUTH_TOKEN"] = "pilot-token"
        handler = self._make_handler_instance("/api/jobs", token="pilot-token")
        self.assertTrue(handler._is_authenticated())

    def test_no_token_open_access(self):
        # No DUPE_UI_AUTH_TOKEN set → open access (network-level auth via Tailscale/VPN)
        handler = self._make_handler_instance("/api/run")
        self.assertTrue(handler._is_authenticated())


# ---------------------------------------------------------------------------
# Phase 8 — PHI sanitization in API job records
# ---------------------------------------------------------------------------

class TestJobSanitization(unittest.TestCase):
    def tearDown(self):
        os.environ.pop("DUPE_LOG_PHI", None)

    def test_phi_fields_redacted_by_default(self):
        from dupe_engine.review_ui_server import _sanitize_job_for_api
        job = {
            "job_id": "j1",
            "job_dir": "/secret/path",
            "stdout_tail": "processing patient records",
            "stderr_tail": "warning: slow",
            "error": "File not found: john_doe_2024.pdf",
        }
        result = _sanitize_job_for_api(job)
        self.assertNotIn("job_dir", result)
        self.assertEqual(result["stdout_tail"], "[set DUPE_LOG_PHI=true to see]")
        self.assertEqual(result["stderr_tail"], "[set DUPE_LOG_PHI=true to see]")
        self.assertEqual(result["error"], "[set DUPE_LOG_PHI=true to see full error]")

    def test_phi_passthrough_when_enabled(self):
        from dupe_engine.review_ui_server import _sanitize_job_for_api
        os.environ["DUPE_LOG_PHI"] = "true"
        job = {
            "job_id": "j1",
            "stdout_tail": "output text",
            "stderr_tail": "err",
            "error": "original error",
        }
        result = _sanitize_job_for_api(job)
        self.assertEqual(result["stdout_tail"], "output text")
        self.assertEqual(result["error"], "original error")

    def test_empty_fields_pass_through(self):
        from dupe_engine.review_ui_server import _sanitize_job_for_api
        job = {"job_id": "j1", "stdout_tail": "", "stderr_tail": "", "error": None}
        result = _sanitize_job_for_api(job)
        # Empty/null fields should not become [PHI-REDACTED]
        self.assertEqual(result["stdout_tail"], "")
        self.assertEqual(result["stderr_tail"], "")
        self.assertIsNone(result["error"])


if __name__ == "__main__":
    unittest.main()
