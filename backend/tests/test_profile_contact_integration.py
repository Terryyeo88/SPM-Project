"""Live Supabase integration tests for IS-68's profile columns
(20261030000000_profile_contact_preferences.sql, tightened by
20261031000000_profile_contact_rules.sql) -- what the unit tests'
in-memory fake can't prove:

- EXISTING PROFILES: a profile written the way every profile was before
  IS-68 (id, name, email only) -- and every seeded one -- gets the column
  defaults (email on, SMS off, no phone), still loads and still saves
- the table's own checks: +65 phone format, at least one preference, SMS
  needs a phone -- refused by Postgres even when the app is bypassed
- the update is scoped to the caller's row, against Postgres
- organisation is not writable through the service, but registration's
  organisation copy still reads it
- RLS: a signed-in user can't write profiles directly; and, logged as an
  open question, CAN still read another user's phone directly

Needs a local stack (`npx supabase start && npx supabase db reset`), like
every other integration test.
"""

from __future__ import annotations

import os
import uuid

import pytest
from postgrest.exceptions import APIError
from supabase import create_client

import app.me.profile_service as service
from app.extensions import supabase
from app.registrations.registration_service import _db_profile_organisation
from app.shared.errors import ValidationError

pytestmark = pytest.mark.integration

_PASSWORD = "Password123!-throwaway-test-account"

DEFAULTS = {"phone": None, "organisation": None, "notify_email": True, "notify_sms": False}


def _create_user() -> str:
    """Exactly how a profile was written before IS-68: id, name, email."""
    email = f"profile-test-{uuid.uuid4()}@example.com"
    created = supabase.auth.admin.create_user({"email": email, "password": _PASSWORD, "email_confirm": True})
    user_id = created.user.id
    supabase.table("profiles").insert({"id": user_id, "name": "Profile Test User", "email": email}).execute()
    return user_id


def _delete_user(user_id: str) -> None:
    supabase.table("profiles").delete().eq("id", user_id).execute()
    supabase.auth.admin.delete_user(user_id)


def _row(user_id: str) -> dict:
    return supabase.table("profiles").select("*").eq("id", user_id).single().execute().data


def _signed_in_as(user_id: str):
    """Own client instance signed in as this user, so RLS applies (see
    test_notifications_integration.py)."""
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    client.auth.sign_in_with_password({"email": _row(user_id)["email"], "password": _PASSWORD})
    return client


@pytest.fixture
def users():
    created: list[str] = []

    def make():
        created.append(_create_user())
        return created[-1]

    try:
        yield make
    finally:
        for user_id in created:
            _delete_user(user_id)


# -- existing profiles -------------------------------------------------------------


def test_every_seeded_profile_satisfies_the_rules():
    """The seed inserts id, name, email only -- the pre-IS-68 shape. After
    the migrations every row has both preferences set, at least one on,
    and no SMS without a phone."""
    rows = supabase.table("profiles").select("email, phone, notify_email, notify_sms").execute().data

    assert rows
    for row in rows:
        assert row["notify_email"] is not None and row["notify_sms"] is not None, row["email"]
        assert row["notify_email"] or row["notify_sms"], row["email"]
        assert row["phone"] or not row["notify_sms"], row["email"]


def test_a_profile_inserted_the_old_way_gets_the_defaults(users):
    alice = users()

    assert service.get_contact(alice) == DEFAULTS
    # The auth context's own profile read (every request) is unchanged.
    from app.auth.context import _load_profile_with_roles

    assert _load_profile_with_roles(alice)[:2] == ("Profile Test User", _row(alice)["email"])


def test_an_existing_profile_still_saves(users):
    alice = users()
    before = _row(alice)

    saved = service.update_own_profile(alice, {"phone": "+65 9123 4567"})

    assert saved == {**DEFAULTS, "phone": "+6591234567"}
    after = _row(alice)
    for unchanged in ("name", "email", "created_at"):
        assert after[unchanged] == before[unchanged], unchanged
    # Rewritten by the app. Not compared with >=: it is set from the app's
    # clock and created_at from the database's, which can differ slightly.
    assert after["updated_at"] != before["updated_at"]


def test_saving_phone_and_preferences_and_reading_them_back(users):
    alice = users()

    service.update_own_profile(alice, {"phone": "+65 9123 4567", "notify_email": False, "notify_sms": True})

    assert service.get_contact(alice) == {
        "phone": "+6591234567", "organisation": None, "notify_email": False, "notify_sms": True,
    }


def test_clearing_the_phone_stores_null(users):
    alice = users()
    service.update_own_profile(alice, {"phone": "+65 9123 4567"})

    service.update_own_profile(alice, {"phone": "  "})

    assert _row(alice)["phone"] is None


def test_a_refused_update_leaves_the_row_unchanged(users):
    alice = users()
    service.update_own_profile(alice, {"phone": "+65 9123 4567", "notify_sms": True})
    before = _row(alice)

    with pytest.raises(ValidationError):
        service.update_own_profile(alice, {"phone": None})

    assert _row(alice) == before


def test_the_update_touches_only_the_callers_row(users):
    alice, bob = users(), users()
    service.update_own_profile(bob, {"phone": "+65 8000 0000"})

    service.update_own_profile(alice, {"phone": "+65 9123 4567"})

    assert _row(bob)["phone"] == "+6580000000"


# -- the table's own checks -----------------------------------------------------------


@pytest.mark.parametrize(
    "change",
    [
        {"phone": ""},
        {"phone": "91234567"},
        {"phone": "+65 9123 4567"},  # stored form has no spaces
        {"phone": "+659123456"},
        {"notify_email": False, "notify_sms": False},
        {"notify_sms": True},  # no phone
        {"notify_email": None},
    ],
)
def test_the_database_refuses_rule_breaking_rows(users, change):
    alice = users()

    with pytest.raises(APIError) as refused:
        supabase.table("profiles").update(change).eq("id", alice).execute()

    # check_violation, or not_null_violation for the NULL preference
    assert refused.value.code in ("23514", "23502")


# -- organisation: read-only, still copied into registrations ---------------------------


def test_organisation_cannot_be_written_through_the_service(users):
    alice = users()

    with pytest.raises(ValidationError) as refused:
        service.update_own_profile(alice, {"organisation": "SMU"})

    assert refused.value.code == "profile_field_not_editable"
    assert _row(alice)["organisation"] is None


def test_the_registration_organisation_copy_reads_the_profile(users):
    """registration_service._db_profile_organisation (Justin's, select "*")
    reads the column. Organisation arrives from outside the system, so
    the test sets it directly."""
    alice = users()

    assert _db_profile_organisation(alice) is None

    supabase.table("profiles").update({"organisation": "SMU"}).eq("id", alice).execute()
    assert _db_profile_organisation(alice) == "SMU"


# -- RLS -------------------------------------------------------------------------------


def test_a_signed_in_user_cannot_write_any_profile_directly(users):
    alice, bob = users(), users()
    client = _signed_in_as(alice)

    # No update policy: RLS matches no row, so nothing changes -- not even
    # the caller's own. Writes go through PATCH /me/profile only.
    client.table("profiles").update({"phone": "+6591234567"}).eq("id", alice).execute()
    client.table("profiles").update({"phone": "+6591234567"}).eq("id", bob).execute()

    assert _row(alice)["phone"] is None
    assert _row(bob)["phone"] is None


def test_open_question_a_signed_in_user_can_still_read_another_users_phone_directly(users):
    """NOT the desired state -- the current one, pinned so it can't change
    unnoticed. The pre-existing "authenticated read profiles" policy lets
    any signed-in user select every profile, and that now includes phone.
    Logged in docs/open-questions.md (IS-68); when that policy is narrowed,
    this test should flip to asserting the row is hidden."""
    alice, bob = users(), users()
    service.update_own_profile(bob, {"phone": "+65 8000 0000"})

    seen = _signed_in_as(alice).table("profiles").select("id, phone").eq("id", bob).execute().data

    assert seen == [{"id": bob, "phone": "+6580000000"}]
