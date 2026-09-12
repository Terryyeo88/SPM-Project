"""
Tests for app.auth.jwt.verify_token -- signature and claims verification
against a JWKS, entirely in-memory via the `signing_key` fixture
(conftest.py). No network call, no real Supabase key anywhere here.
"""

from __future__ import annotations

import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app.auth.jwt import verify_token
from app.shared.errors import AuthenticationError


def test_valid_token_verifies_and_returns_claims(signing_key):
    token = signing_key.make_token(sub="user-1", session_id="sess-1")
    claims = verify_token(f"Bearer {token}")
    assert claims["sub"] == "user-1"
    assert claims["session_id"] == "sess-1"


@pytest.mark.parametrize(
    "make_header,expected_code",
    [
        (lambda key: None, "auth_missing_token"),
        (lambda key: "Basic abc", "auth_malformed_token"),
        (lambda key: "Bearer not-a-jwt", "auth_malformed_token"),
        (lambda key: f"Bearer {key.make_token(kid='unknown-kid')}", "auth_unknown_key"),
        (lambda key: f"Bearer {key.make_token(exp_delta_seconds=-10)}", "auth_token_expired"),
        (lambda key: f"Bearer {key.make_token(audience='wrong-audience')}", "auth_wrong_audience"),
        (
            lambda key: f"Bearer {key.make_token(issuer='https://evil.supabase.co/auth/v1')}",
            "auth_wrong_audience",
        ),
        (lambda key: f"Bearer {key.make_token(omit_session_id=True)}", "auth_malformed_token"),
    ],
    ids=[
        "missing header",
        "wrong scheme",
        "unparseable token",
        "unknown kid",
        "expired",
        "wrong audience",
        "wrong issuer",
        "missing session_id claim",
    ],
)
def test_rejection_cases_produce_specific_codes(signing_key, make_header, expected_code):
    header = make_header(signing_key)
    with pytest.raises(AuthenticationError) as excinfo:
        verify_token(header)
    assert excinfo.value.code == expected_code


def test_small_clock_skew_on_iat_is_tolerated(signing_key):
    """Regression test for a real bug found running against the live
    project: PyJWT rejects an `iat` that appears to be in the future
    with zero tolerance by default, and ordinary clock skew between this
    machine and Supabase's server intermittently put real, otherwise-
    valid tokens a few seconds into the "future" by the verifying
    machine's clock. verify_token must tolerate small skew (see
    _CLOCK_SKEW_LEEWAY_SECONDS in app/auth/jwt.py)."""
    token = signing_key.make_token(iat_delta_seconds=5)
    claims = verify_token(f"Bearer {token}")
    assert claims["sub"] == "user-1"


def test_large_clock_skew_on_iat_is_still_rejected(signing_key):
    """The leeway is a tolerance for real clock skew, not a blank
    exemption -- an `iat` far in the future must still fail."""
    token = signing_key.make_token(iat_delta_seconds=3600)
    with pytest.raises(AuthenticationError) as excinfo:
        verify_token(f"Bearer {token}")
    assert excinfo.value.code == "auth_malformed_token"


def test_token_missing_kid_header_is_rejected(signing_key):
    token = signing_key.make_token(omit_kid=True)
    with pytest.raises(AuthenticationError) as excinfo:
        verify_token(f"Bearer {token}")
    assert excinfo.value.code == "auth_malformed_token"


def test_token_missing_required_claim_falls_through_to_malformed(signing_key):
    """A claim PyJWT itself requires (here: sub) being absent raises
    MissingRequiredClaimError, a subclass of InvalidTokenError that
    isn't ExpiredSignatureError/InvalidAudienceError/InvalidIssuerError/
    InvalidSignatureError -- exercises verify_token's generic
    `except jwt.InvalidTokenError` fallback specifically, not one of the
    named branches above it."""
    token = signing_key.make_token(omit_sub=True)
    with pytest.raises(AuthenticationError) as excinfo:
        verify_token(f"Bearer {token}")
    assert excinfo.value.code == "auth_malformed_token"


def test_bad_signature_is_rejected(signing_key):
    # Signed by a DIFFERENT, unrelated private key, but claiming the same
    # kid -- this is what a forged token looks like: right shape, wrong
    # signature.
    forger_key = ec.generate_private_key(ec.SECP256R1())
    forged = signing_key.make_token(private_key=forger_key)

    with pytest.raises(AuthenticationError) as excinfo:
        verify_token(f"Bearer {forged}")
    assert excinfo.value.code == "auth_invalid_signature"


def test_unknown_kid_triggers_exactly_one_refetch(signing_key, monkeypatch):
    """The refetch-on-unknown-kid path exists for key rotation: confirm
    it actually refetches (picks up a key added after the first fetch)
    rather than just failing fast on a stale cache."""
    import app.auth.jwt as jwt_module

    fetch_calls = []

    def fetch(url):
        fetch_calls.append(url)
        if len(fetch_calls) == 1:
            return {"keys": []}  # first fetch: rotation hasn't "happened" yet
        return {"keys": [signing_key.jwk]}  # refetch: now it's there

    monkeypatch.setattr(jwt_module, "_http_get_json", fetch)
    jwt_module._jwks_cache.reset()

    token = signing_key.make_token()
    claims = verify_token(f"Bearer {token}")

    assert claims["sub"] == "user-1"
    assert len(fetch_calls) == 2  # the initial fetch, plus exactly one refetch
