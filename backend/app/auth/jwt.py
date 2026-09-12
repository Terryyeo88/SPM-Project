"""
Verifies Supabase-issued access tokens locally against this project's
published JWKS.

This project was confirmed (by fetching
https://cbnzjcfosvgzoecekjxg.supabase.co/auth/v1/.well-known/jwks.json
directly) to be on Supabase's current asymmetric JWT signing-key system
(ES256 / EC keys), not the legacy shared HS256 secret. Per Supabase's own
guidance, a legacy-secret project should NOT be verified this way at all
-- they recommend calling the Auth server per request instead, since a
shared secret gives local verification "almost no benefit". This module
deliberately implements ONLY the asymmetric/JWKS path; there is no HS256
fallback anywhere in it.

Every rejection raises AuthenticationError (app.shared.errors) with one
of these stable, machine-readable `code` values. The frontend (Josiah,
IS-27) branches on `code`, never on the message text:

    auth_missing_token      -- no Authorization header at all
    auth_malformed_token    -- header isn't "Bearer <token>", the token
                               isn't a parseable JWT, or it's missing a
                               required claim (kid, session_id)
    auth_unknown_key        -- token's `kid` isn't in our JWKS even after
                               one refetch (see _JWKSCache below)
    auth_invalid_signature  -- signature doesn't verify against the key
                               named by `kid`
    auth_token_expired      -- `exp` has passed
    auth_wrong_audience     -- `iss` or `aud` doesn't match this project

Of these, only auth_token_expired means "the token itself was fine, it's
just old" -- every other code means the token was never valid for this
project. (auth_session_idle, the idle-timeout rejection, is NOT raised
here -- see app/auth/context.py: idle state lives in our own database,
keyed by the token's session_id claim, not in the token itself, so it's
checked after this module has already verified the signature.)

Never logs or echoes token contents here, not even truncated, not even
at debug level -- a bearer token is a live credential for its whole
lifetime.
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any

import jwt
from jwt import PyJWK

from app.shared.errors import AuthenticationError

_JWKS_PATH = "/auth/v1/.well-known/jwks.json"
_ISSUER_PATH = "/auth/v1"
_EXPECTED_AUDIENCE = "authenticated"

# PyJWT checks `iat` is not in the future using the LOCAL clock, with zero
# tolerance by default -- found live, the hard way: verifying real tokens
# from the real project intermittently raised ImmatureSignatureError ("the
# token is not yet valid (iat)") with no leeway, purely from ordinary clock
# skew between this machine and Supabase's server (the claims were otherwise
# completely valid every time it happened -- same token, re-verified a moment
# later, passed). 10 seconds is the standard tolerance for this class of
# skew; it does not weaken expiry enforcement, which is checked separately.
_CLOCK_SKEW_LEEWAY_SECONDS = 10

# Matches Supabase's own edge cache lifetime for this endpoint (per their
# docs: cached 10 minutes there, and caching longer client-side risks
# missing a legitimate key rotation for a while).
_CACHE_TTL_SECONDS = 600


def _http_get_json(url: str) -> dict[str, Any]:
    """Isolated so tests can monkeypatch just this, without needing a
    real network call or a fake HTTP server."""
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310 -- fixed https JWKS URL, not user input
        return json.loads(response.read())


class _JWKSCache:
    """Thread-safe cache of this project's JWKS, keyed by `kid`.

    Refetches on a TTL (_CACHE_TTL_SECONDS), OR once, immediately, the
    first time a token names a `kid` we don't have cached -- that second
    path is what makes key rotation survivable. Supabase publishes a new
    signing key as "standby" before any token is ever signed with it, but
    the exact moment our TTL-based cache refreshes to include it is not
    synchronised with the moment Supabase starts signing with it. Without
    an immediate refetch-on-unknown-kid, every token signed in the window
    between "key went active" and "our next scheduled refresh" would be
    wrongly rejected. The refetch happens at most once per unknown kid --
    if it's still not found after that, the kid genuinely isn't ours.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._keys: dict[str, PyJWK] = {}
        self._fetched_at: float = 0.0

    def _jwks_url(self) -> str:
        base = os.environ.get("SUPABASE_URL")
        if not base:
            raise RuntimeError("SUPABASE_URL is not set; cannot fetch JWKS to verify tokens.")
        return base.rstrip("/") + _JWKS_PATH

    def _refresh(self) -> None:
        data = _http_get_json(self._jwks_url())
        self._keys = {key["kid"]: PyJWK(key) for key in data.get("keys", [])}
        self._fetched_at = time.monotonic()

    def reset(self) -> None:
        """Drop the cache so the next get() refetches. Test-only hook --
        production code never needs to call this, the TTL/unknown-kid
        logic in get() handles refreshing on its own."""
        with self._lock:
            self._keys = {}
            self._fetched_at = 0.0

    def get(self, kid: str) -> PyJWK | None:
        with self._lock:
            stale = (time.monotonic() - self._fetched_at) > _CACHE_TTL_SECONDS
            if stale or not self._keys:
                self._refresh()
            if kid in self._keys:
                return self._keys[kid]
            # Unknown kid: refetch once, immediately -- see class docstring.
            self._refresh()
            return self._keys.get(kid)


_jwks_cache = _JWKSCache()


def verify_token(authorization_header: str | None) -> dict[str, Any]:
    """Verify a bearer token from an Authorization header and return its
    claims dict. Raises AuthenticationError (with a specific `code`; see
    module docstring) on any failure -- never returns a partially-trusted
    result."""
    if not authorization_header:
        raise AuthenticationError("Missing Authorization header.", code="auth_missing_token")

    scheme, _, token = authorization_header.partition(" ")
    token = token.strip()
    if scheme != "Bearer" or not token:
        raise AuthenticationError(
            "Authorization header must be 'Bearer <token>'.", code="auth_malformed_token"
        )

    try:
        header = jwt.get_unverified_header(token)
    except jwt.DecodeError as err:
        raise AuthenticationError("Token is not a parseable JWT.", code="auth_malformed_token") from err

    kid = header.get("kid")
    if not kid:
        raise AuthenticationError("Token is missing a 'kid' header.", code="auth_malformed_token")

    key = _jwks_cache.get(kid)
    if key is None:
        raise AuthenticationError("Token's signing key is not recognised.", code="auth_unknown_key")

    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    expected_issuer = base + _ISSUER_PATH

    try:
        claims = jwt.decode(
            token,
            key=key.key,
            algorithms=[key.algorithm_name],
            issuer=expected_issuer,
            audience=_EXPECTED_AUDIENCE,
            options={"require": ["exp", "iat", "sub"]},
            leeway=_CLOCK_SKEW_LEEWAY_SECONDS,
        )
    except jwt.ExpiredSignatureError as err:
        raise AuthenticationError("Token has expired.", code="auth_token_expired") from err
    except (jwt.InvalidAudienceError, jwt.InvalidIssuerError) as err:
        raise AuthenticationError(
            "Token issuer/audience does not match this project.", code="auth_wrong_audience"
        ) from err
    except jwt.InvalidSignatureError as err:
        raise AuthenticationError("Token signature is invalid.", code="auth_invalid_signature") from err
    except jwt.InvalidTokenError as err:
        raise AuthenticationError("Token is malformed.", code="auth_malformed_token") from err

    if not claims.get("session_id"):
        raise AuthenticationError("Token is missing required 'session_id' claim.", code="auth_malformed_token")

    return claims
