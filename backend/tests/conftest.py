"""
Shared pytest fixtures.

Unit tests must never touch a real database or the network. `app` and
`client` build a Flask app via config_override, so no real Supabase
credentials are ever required. `signing_key` gives each test its own
throwaway EC keypair plus a `make_token()` factory, and points
app.auth.jwt's JWKS cache at that keypair instead of the real network --
no test here ever talks to Supabase's actual JWKS endpoint.

Anything that genuinely needs a live database is marked
`@pytest.mark.integration` (registered in pytest.ini) and is skipped
automatically unless SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are both
set in the environment -- never true in CI (Phase 6).
"""

from __future__ import annotations

import base64
import os
import sys
import time
from pathlib import Path

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

# backend/ (parent of this tests/ directory) needs to be importable as
# the root for `app`, `seed`, etc. Pytest's own import-mode sys.path
# insertion only guarantees tests/ itself is on sys.path, not its
# parent -- this is the flat-backend/-no-src-layout equivalent of
# `pip install -e .`, done without an actual package install.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app.auth.jwt as jwt_module  # noqa: E402
from app import create_app  # noqa: E402
from app.config import Config  # noqa: E402


class _TestConfig(Config):
    SUPABASE_URL = None
    SUPABASE_SERVICE_ROLE_KEY = None
    SUPABASE_JWT_SECRET = None
    TESTING = True


@pytest.fixture
def app():
    return create_app(config_override=_TestConfig)


@pytest.fixture
def client(app):
    return app.test_client()


def _b64url(number: int, length: int = 32) -> str:
    return base64.urlsafe_b64encode(number.to_bytes(length, "big")).rstrip(b"=").decode()


class SigningKey:
    """A throwaway EC keypair standing in for Supabase's real signing
    key, plus a factory for tokens signed with it. Tests never come
    anywhere near the real project's private key -- we only ever have
    its PUBLIC key (see app/auth/jwt.py's docstring) -- so this generates
    its own, unrelated, keypair."""

    def __init__(self, kid: str = "test-kid"):
        self.kid = kid
        self._private_key = ec.generate_private_key(ec.SECP256R1())
        public_numbers = self._private_key.public_key().public_numbers()
        self.jwk = {
            "kty": "EC",
            "crv": "P-256",
            "alg": "ES256",
            "use": "sig",
            "kid": kid,
            "x": _b64url(public_numbers.x),
            "y": _b64url(public_numbers.y),
        }

    def make_token(
        self,
        *,
        sub: str = "user-1",
        session_id: str = "session-1",
        issuer: str = "https://test-project.supabase.co/auth/v1",
        audience: str = "authenticated",
        exp_delta_seconds: int = 3600,
        kid: str | None = None,
        omit_session_id: bool = False,
        private_key=None,
    ) -> str:
        now = int(time.time())
        payload = {
            "sub": sub,
            "iss": issuer,
            "aud": audience,
            "iat": now,
            "exp": now + exp_delta_seconds,
        }
        if not omit_session_id:
            payload["session_id"] = session_id
        return pyjwt.encode(
            payload,
            private_key or self._private_key,
            algorithm="ES256",
            headers={"kid": kid or self.kid},
        )


@pytest.fixture
def signing_key(monkeypatch):
    """Installs a fresh throwaway signing key as the "JWKS" app.auth.jwt
    will see, and points SUPABASE_URL at a fake project matching the
    tokens this fixture signs -- all in-memory, no network."""
    key = SigningKey()
    monkeypatch.setenv("SUPABASE_URL", "https://test-project.supabase.co")
    monkeypatch.setattr(jwt_module, "_http_get_json", lambda url: {"keys": [key.jwk]})
    jwt_module._jwks_cache.reset()
    return key


def pytest_collection_modifyitems(config, items):
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_ROLE_KEY"):
        return
    skip_integration = pytest.mark.skip(reason="requires SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
