"""
Integration test for app.auth.jwt.verify_token against the REAL project
-- no monkeypatching of _http_get_json at all, unlike every test in
test_auth_jwt.py. That file proves the verification LOGIC is correct
against a synthetic JWKS; this proves the real HTTP fetch against
Supabase's actual .well-known/jwks.json and a real, live-signed token
both still work together, end to end. This was done manually once, live,
during the Phase 3 end-to-end proof (and again surfaced the JWKS
signing-key type to confirm against) but had no automated regression
test until the Phase 5 criterion audit found the gap.

IMPORTANT, discovered writing this: calling sign_in_with_password on the
shared app.extensions.supabase singleton mutates ITS session state --
every subsequent call through that same client then acts as the
signed-in user, not service_role, which breaks RLS-gated writes for the
rest of the process (it broke test_session_activity_integration.py the
first time this test existed, by running before it in the same pytest
session). This test signs in through its OWN throwaway client instance
instead, specifically so the shared singleton other tests depend on is
never touched.

Skipped automatically (see conftest.py's pytest_collection_modifyitems)
unless SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are both set -- never
true in CI.
"""

from __future__ import annotations

import os

import pytest
from supabase import create_client

from app.auth.jwt import verify_token
from app.extensions import supabase

pytestmark = pytest.mark.integration

_SEED_EMAIL = "coordinator1@example.com"
_SEED_PASSWORD = "Password123!"


def test_verify_token_against_real_jwks_and_a_real_signed_in_user():
    result = supabase.table("profiles").select("id").eq("email", _SEED_EMAIL).execute()
    if not result.data:
        pytest.skip(f"seed data not present ({_SEED_EMAIL} not found)")
    expected_user_id = result.data[0]["id"]

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    throwaway_client = create_client(url, key)

    session = throwaway_client.auth.sign_in_with_password(
        {"email": _SEED_EMAIL, "password": _SEED_PASSWORD}
    )
    token = session.session.access_token

    claims = verify_token(f"Bearer {token}")

    assert claims["sub"] == expected_user_id
    assert claims.get("session_id")
