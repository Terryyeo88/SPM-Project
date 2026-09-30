"""
Shared pytest fixtures.

Unit tests must never touch a real database or the network. `app` and
`client` build a Flask app via config_override, so no real Supabase
credentials are ever required. `signing_key` gives each test its own
throwaway EC keypair plus a `make_token()` factory, and points
app.auth.jwt's JWKS cache at that keypair instead of the real network --
no test here ever talks to Supabase's actual JWKS endpoint.

Anything that genuinely needs a real database is marked
`@pytest.mark.integration` (registered in pytest.ini). Integration tests
run ONLY against a local Supabase (see pytest_collection_modifyitems at
the bottom): they're skipped when SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY
are absent (CI), and ALSO skipped when SUPABASE_URL points anywhere
non-local -- which is what the repo-root .env does on a teammate's machine
-- unless the explicit opt-in below is set.

"Unit tests never touch a database" is ENFORCED, not just intended: see
_forbid_database_in_unit_tests below. Every test not marked integration
runs with the shared Supabase client rigged to raise
UnitTestDatabaseAccessError the moment anything touches it.
"""

from __future__ import annotations

import base64
import ipaddress
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

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
from app.extensions import _LazySupabaseClient  # noqa: E402


class _TestConfig(Config):
    SUPABASE_URL = None
    SUPABASE_SERVICE_ROLE_KEY = None
    SUPABASE_JWT_SECRET = None
    TESTING = True


class UnitTestDatabaseAccessError(BaseException):
    """A unit test reached for the real Supabase client.

    Deliberately a BaseException, not an Exception. App code has broad
    `except Exception` handlers (e.g. /health/db turns any failure into a
    503, and create_app's error handler turns any Exception into a 500
    JSON response). An Exception raised here could be caught there, and a
    test asserting on that 500 or 503 would pass without ever noticing it
    had tried to reach the database. A BaseException passes through
    `except Exception` and Flask's handlers alike, and fails the test with
    this message.
    """


@pytest.fixture(autouse=True)
def _forbid_database_in_unit_tests(request, monkeypatch):
    """Autouse: applies to EVERY test, and there's nothing to opt into or forget.

    Integration tests are exempt, since reaching a real database is their
    whole point. Every other test gets the shared client's one entry point,
    _LazySupabaseClient._get_client, replaced with one that raises. The
    patch is on the CLASS because every app module holds a reference to
    the same `supabase` instance, taken at import time. Rebinding
    app.extensions.supabase would reach none of them, and blanking
    SUPABASE_URL wouldn't help once the client is cached. A test that
    swaps a module's `supabase` for its own fake is unaffected. Only a call
    that reaches the REAL client, i.e. an incomplete fake, trips this.
    """
    if request.node.get_closest_marker("integration"):
        return

    def _refuse(self):
        raise UnitTestDatabaseAccessError(
            f"This unit test tried to reach the database: {request.node.nodeid}. "
            "Unit tests must not touch Supabase -- some code path it exercises uses the real "
            "`supabase` client that the test's fakes/monkeypatches don't cover. Fake that call "
            "(or mark the test @pytest.mark.integration if it genuinely needs a database)."
        )

    monkeypatch.setattr(_LazySupabaseClient, "_get_client", _refuse)


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
        iat_delta_seconds: int = 0,
        kid: str | None = None,
        omit_session_id: bool = False,
        omit_kid: bool = False,
        omit_sub: bool = False,
        private_key=None,
    ) -> str:
        now = int(time.time())
        payload = {
            "sub": sub,
            "iss": issuer,
            "aud": audience,
            "iat": now + iat_delta_seconds,
            "exp": now + exp_delta_seconds,
        }
        if omit_sub:
            del payload["sub"]
        if not omit_session_id:
            payload["session_id"] = session_id
        headers = {} if omit_kid else {"kid": kid or self.kid}
        return pyjwt.encode(
            payload,
            private_key or self._private_key,
            algorithm="ES256",
            headers=headers,
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


# -- where integration tests may run -----------------------------------------
# Integration tests create and delete real rows (users, events, audit log).
# Against the shared project, that's the database the team demos from, so
# they refuse any non-local SUPABASE_URL unless this is set to EXACTLY the
# value below. Deliberately long and specific: it can't be set by accident,
# and anyone reading a shell history can see what was agreed to.
REMOTE_OPT_IN_VAR = "INTEGRATION_TESTS_WRITE_TO_REMOTE_SUPABASE"
REMOTE_OPT_IN_VALUE = "yes-write-test-data-to-the-shared-project"

_HOW_TO_RUN_LOCALLY = (
    "start a local stack (npx supabase start && npx supabase db reset) and export its "
    "API_URL/SERVICE_ROLE_KEY as SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY -- see README 'Running tests'"
)


def _supabase_host(url: str) -> str | None:
    try:
        return urlsplit(url).hostname
    except ValueError:  # e.g. an unfilled .env.example placeholder
        return None


def is_local_supabase(url: str) -> bool:
    """True only for `localhost` or a loopback IP literal (127.0.0.0/8, ::1) --
    what `npx supabase status` reports (http://127.0.0.1:<port>). Matched on
    the URL's HOST because that is exactly where requests (and so writes)
    go. Anything else, including a hostname we can't parse, counts as
    non-local: fail safe."""
    host = _supabase_host(url)
    if not host:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def integration_skip_reason(environ) -> str | None:
    """None if integration tests may run in this environment, else why not."""
    url, key = environ.get("SUPABASE_URL"), environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not (url and key):
        return f"no SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY set. To run integration tests, {_HOW_TO_RUN_LOCALLY}."
    if is_local_supabase(url):
        return None
    opt_in = environ.get(REMOTE_OPT_IN_VAR)
    if opt_in == REMOTE_OPT_IN_VALUE:
        return None
    host = _supabase_host(url) or "an unparseable URL"
    ignored = f" ({REMOTE_OPT_IN_VAR} is set, but not to the exact required value.)" if opt_in else ""
    return (
        f"SUPABASE_URL points at {host}, which is not a local Supabase. Integration tests write real "
        f"data, so they refuse a non-local database by default.{ignored} To run them, {_HOW_TO_RUN_LOCALLY}. "
        f"To run against {host} deliberately: {REMOTE_OPT_IN_VAR}={REMOTE_OPT_IN_VALUE}"
    )


def pytest_report_header(config):
    reason = integration_skip_reason(os.environ)
    host = _supabase_host(os.environ.get("SUPABASE_URL") or "") or "none"
    if reason is None:
        where = "local" if is_local_supabase(os.environ.get("SUPABASE_URL") or "") else "REMOTE (opted in)"
        return f"integration tests: RUN against {host} [{where}]"
    return f"integration tests: SKIPPED (target: {host})"


def pytest_collection_modifyitems(config, items):
    reason = integration_skip_reason(os.environ)
    if reason is None:
        return
    skip_integration = pytest.mark.skip(reason=reason)
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)
