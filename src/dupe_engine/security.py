from __future__ import annotations

import hmac
import os
import warnings
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from .config import EngineConfig

_TRUTHY = {"1", "true", "yes", "y", "on"}


def _strict_mode() -> bool:
    """DUPE_STRICT_COMPLIANCE=true upgrades compliance warnings to hard stops.

    Off by default. Enable in production environments where a misconfiguration
    should prevent the server from starting rather than log a warning.
    """
    return os.environ.get("DUPE_STRICT_COMPLIANCE", "").strip().lower() in _TRUTHY


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _auth_token() -> str:
    return os.environ.get("DUPE_UI_AUTH_TOKEN", "")


def is_loopback_host(host: str) -> bool:
    # Strip IPv6 brackets and port: [::1]:8080 → ::1, 127.0.0.1:8080 → 127.0.0.1
    h = host.strip("[]")
    if ":" in h and not h.startswith("::") and not h.count(":") > 1:
        h = h.split(":")[0]
    return h.lower() in {"127.0.0.1", "::1", "localhost"}


def check_bearer_token(authorization_header: str | None) -> bool:
    """Return True if the Authorization header carries the configured token."""
    expected = _auth_token()
    if not expected:
        return True  # token not configured — caller must check host guard
    if not authorization_header:
        return False
    scheme, _, provided = authorization_header.partition(" ")
    if scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(expected.strip(), provided.strip())


def auth_required(host: str, authorization_header: str | None) -> bool:
    """Return True when the request is authenticated (or auth is not needed).

    On loopback with no token configured: open (dev/local default).
    On non-loopback with a token configured: token required.
    On non-loopback with no token: denied (set DUPE_UI_AUTH_TOKEN).
    """
    token = _auth_token()
    if not token and is_loopback_host(host):
        return True  # loopback + no token → open for local/dev use
    if not token:
        return False  # non-loopback + no token → deny
    return check_bearer_token(authorization_header)


# ---------------------------------------------------------------------------
# TLS / bind guard
# ---------------------------------------------------------------------------

def require_tls_or_loopback(host: str) -> None:
    """Warn (or hard-stop in strict mode) when binding to a non-loopback interface
    without TLS acknowledgement.

    Default: logs a warning and continues — the system is built to process PHI
    and the operator is responsible for their network setup.

    Set DUPE_TLS_TERMINATED=true to silence the warning (acknowledges that a
    reverse proxy or ALB terminates TLS before this process).

    Set DUPE_STRICT_COMPLIANCE=true to make this a hard stop instead of a warning.
    """
    if is_loopback_host(host):
        return
    tls_ok = os.environ.get("DUPE_TLS_TERMINATED", "").strip().lower() in _TRUTHY
    if tls_ok:
        return
    msg = (
        "Review UI is bound to a non-loopback interface without TLS acknowledgement. "
        "Set DUPE_TLS_TERMINATED=true to confirm a reverse proxy handles TLS, "
        "or bind to 127.0.0.1 for local-only access."
    )
    if _strict_mode():
        raise SystemExit(f"FATAL: {msg}")
    warnings.warn(msg, stacklevel=2)


# ---------------------------------------------------------------------------
# BAA-covered OpenAI endpoint assertion
# ---------------------------------------------------------------------------

_DEFAULT_OPENAI_HOST = "api.openai.com"


def _baa_allowed_hosts() -> frozenset[str]:
    raw = os.environ.get("DUPE_OPENAI_BAA_ALLOWED_HOSTS", _DEFAULT_OPENAI_HOST)
    return frozenset(h.strip().lower() for h in raw.split(",") if h.strip())


def _effective_host(url: str) -> str:
    url = url.strip()
    if not url:
        return _DEFAULT_OPENAI_HOST
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return urlparse(url).hostname or _DEFAULT_OPENAI_HOST


def assert_baa_endpoint(config: "EngineConfig") -> None:
    """Warn (or hard-stop in strict mode) if AI endpoints are outside the BAA allow-list.

    Default: logs a warning and continues — the system processes PHI by design
    and the operator is responsible for ensuring their OpenAI endpoint is BAA-covered.

    Set DUPE_STRICT_COMPLIANCE=true to make this a hard stop instead.
    """
    allowed = _baa_allowed_hosts()

    ocr_host = _effective_host(config.openai_ocr_base_url or config.openai_base_url)
    emb_host = _effective_host(config.embeddings_base_url or config.openai_base_url)

    outside = []
    if ocr_host not in allowed:
        outside.append(f"openai_ocr → {ocr_host!r}")
    if config.enable_embeddings and emb_host not in allowed:
        outside.append(f"embeddings → {emb_host!r}")

    if outside:
        msg = (
            f"AI endpoints outside the BAA allow-list "
            f"({', '.join(sorted(allowed))}): {'; '.join(outside)}. "
            "Set DUPE_OPENAI_BAA_ALLOWED_HOSTS to include your BAA-covered endpoint, "
            "or set DUPE_OPENAI_BASE_URL to point at the approved gateway."
        )
        if _strict_mode():
            raise SystemExit(f"FATAL: {msg}")
        warnings.warn(msg, stacklevel=2)
