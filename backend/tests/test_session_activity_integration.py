"""
Integration tests for app.auth.context's Supabase-facing functions --
_get_last_active and _touch_session_activity against the REAL
session_activity table. These exist because the unit tests in
test_auth_context.py monkeypatch both functions entirely, which caught
every behavioural bug in the idle/debounce logic but NONE in how those
two functions talk to postgrest-py -- a real run against the live
project found that `.maybe_single().execute()` returns None itself (not
a response object with `.data = None`) on zero rows, which
_get_last_active's first version got wrong and crashed on. These tests
exist so that class of bug can't silently come back.

Also covers _load_profile_with_roles -- found uncovered entirely (not
just by unit tests, by ANY test) during the Phase 5 criterion audit. It
was exercised manually once, live, during the Phase 3 end-to-end proof,
but had no automated regression test; its nested-relationship select
(`user_roles(role)`) is exactly the kind of postgrest-py-specific
behaviour the maybe_single() bug above already showed unit mocks can't
verify.

Skipped automatically (see conftest.py's pytest_collection_modifyitems)
unless SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are both set -- never
true in CI.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.auth.context import _get_last_active, _load_profile_with_roles, _touch_session_activity
from app.extensions import supabase

pytestmark = pytest.mark.integration


@pytest.fixture
def real_coordinator_id():
    result = (
        supabase.table("profiles").select("id").eq("email", "coordinator1@example.com").execute()
    )
    if not result.data:
        pytest.skip("seed data not present (coordinator1@example.com not found)")
    return result.data[0]["id"]


@pytest.fixture
def throwaway_session_id():
    session_id = str(uuid.uuid4())
    yield session_id
    supabase.table("session_activity").delete().eq("session_id", session_id).execute()


def test_get_last_active_returns_none_for_unknown_session(throwaway_session_id):
    assert _get_last_active(throwaway_session_id) is None


def test_touch_then_get_round_trips(real_coordinator_id, throwaway_session_id):
    now = datetime.now(timezone.utc)
    _touch_session_activity(throwaway_session_id, real_coordinator_id, now)

    last_active = _get_last_active(throwaway_session_id)

    assert last_active is not None
    assert abs((last_active - now).total_seconds()) < 2


def test_touch_twice_upserts_rather_than_duplicating(real_coordinator_id, throwaway_session_id):
    first = datetime.now(timezone.utc)
    _touch_session_activity(throwaway_session_id, real_coordinator_id, first)
    second = datetime.now(timezone.utc)
    _touch_session_activity(throwaway_session_id, real_coordinator_id, second)

    rows = (
        supabase.table("session_activity")
        .select("session_id")
        .eq("session_id", throwaway_session_id)
        .execute()
    )
    assert len(rows.data) == 1

    last_active = _get_last_active(throwaway_session_id)
    assert abs((last_active - second).total_seconds()) < 2


def test_load_profile_with_roles_against_real_seeded_coordinator():
    result = (
        supabase.table("profiles").select("id").eq("email", "coordinator1@example.com").execute()
    )
    if not result.data:
        pytest.skip("seed data not present (coordinator1@example.com not found)")
    user_id = result.data[0]["id"]

    name, email, roles = _load_profile_with_roles(user_id)

    assert name == "Alice Tan"
    assert email == "coordinator1@example.com"
    assert "event_coordinator" in roles
