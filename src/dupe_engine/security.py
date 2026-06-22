from __future__ import annotations

import hmac
import os
import warnings
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    from .config import EngineConfig


_TRUTHY = {"1", "true", "yes", "y", "on"}


def _demo_mode() -> bool:
    """DUPE_DEMO_MODE=true demotes all compliance hard-stops to logged warnings.

    Use only on synthetic/test data. Never set in production or on real PHI.
    """
    return os.environ.get("DUPE_DEMO_MODE", "").strip().lower() in _TRUTHY


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

    In local dev (loopback host + no token configured), auth is bypassed so
    existing dev workflows are unaffected. On any non-loopback interface a
    token is always required — no token configured means deny (defense in depth
    on top of the startup TLS guard).

    DUPE_DEMO_MODE=true also bypasses auth — use only on synthetic/test data.
    """
    if _demo_mode():
        return True
    token = _auth_token()
    if not token and is_loopback_host(host):
        return True  # dev mode: no token, loopback only — allow
    if not token:
        return False  # non-loopback + no token configured → deny
    return check_bearer_token(authorization_header)


# ---------------------------------------------------------------------------
# TLS / bind guard
# ---------------------------------------------------------------------------

def require_tls_or_loopback(host: str) -> None:
    """Refuse to continue if host is non-loopback and TLS is not acknowledged.

    Set DUPE_TLS_TERMINATED=true to acknowledge that a reverse proxy or ALB
    terminates TLS before PHI reaches this process.

    DUPE_DEMO_MODE=true downgrades this to a warning — use only on synthetic/test data.
    """
    if is_loopback_host(host):
        return
    tls_ok = os.environ.get("DUPE_TLS_TERMINATED", "").strip().lower() in _TRUTHY
    if not tls_ok:
        msg = (
            "Review UI is bound to a non-loopback interface without TLS. "
            "Do not use with real PHI. "
            "Set DUPE_TLS_TERMINATED=true when a reverse proxy terminates TLS."
        )
        if _demo_mode():
            warnings.warn(f"DEMO MODE — {msg}", stacklevel=2)
            return
        raise SystemExit(f"FATAL: {msg}")


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
    """Raise SystemExit if any configured AI endpoint is not in the BAA allow-list.

    Mirrors the exact URL-resolution precedence used by providers.py so this
    check is always in sync with the actual call sites.

    DUPE_DEMO_MODE=true downgrades this to a warning — use only on synthetic/test data.
    """
    allowed = _baa_allowed_hosts()

    # OCR endpoint (providers.py line 158)
    ocr_host = _effective_host(config.openai_ocr_base_url or config.openai_base_url)
    # Embeddings endpoint (providers.py line 236)
    emb_host = _effective_host(config.embeddings_base_url or config.openai_base_url)

    blocked = []
    if ocr_host not in allowed:
        blocked.append(f"openai_ocr → {ocr_host!r}")
    if config.enable_embeddings and emb_host not in allowed:
        blocked.append(f"embeddings → {emb_host!r}")

    if blocked:
        msg = (
            f"The following AI endpoints are not in the BAA allow-list "
            f"({', '.join(sorted(allowed))}): {'; '.join(blocked)}. "
            "Set DUPE_OPENAI_BAA_ALLOWED_HOSTS or DUPE_OPENAI_BASE_URL to point "
            "at the approved endpoint."
        )
        if _demo_mode():
            warnings.warn(f"DEMO MODE — {msg}", stacklevel=2)
            return
        raise SystemExit(f"FATAL: {msg}")
