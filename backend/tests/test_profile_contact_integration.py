"""Live Supabase integration tests for IS-68's profile columns
(20261030000000_profile_contact_preferences.sql) -- what the unit tests'
in-memory fake can't prove:

- EXISTING PROFILES ARE UNAFFECTED: a profile written the way every profile
  was before IS-68 (id, name, email only) -- and every seeded one -- has
  NULL in all four new columns, still loads through GET /me's read, and
  still saves
- blank optional fields reach Postgres as NULL, and the table's own checks
  refuse '' anyway
- the update is scoped to the caller's row, against Postgres
- with nothing saved, registration_service's organisation copy (one of the
  two pieces of existing code these columns activate) still finds nothing
- RLS: a signed-in user can't write profiles directly; and, logged as an
  open question, CAN still read another user's new columns directly

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

pytestmark = pytest.mark.integration

_PASSWORD = "Password123!-throwaway-test-account"

UNSET = {"phone": None, "organisation": None, "notify_email": None, "notify_sms": None}


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


# -- existing profiles are unaffected ---------------------------------------------


def test_the_new_columns_exist_nullable_on_every_seeded_profile():
    """The seed inserts id, name, email only -- the pre-IS-68 shape. Every
    one of those rows is NULL in all four columns: nothing was backfilled."""
    rows = supabase.table("profiles").select("email, phone, organisation, notify_email, notify_sms").execute().data

    assert rows
    for row in rows:
        if row["email"].endswith("@example.com") and not row["email"].startswith("profile-test-"):
            assert {field: row[field] for field in service.CONTACT_FIELDS} == UNSET, row["email"]


def test_an_existing_profile_with_nulls_still_loads(users):
    alice = users()

    assert service.get_contact(alice) == UNSET
    # The auth context's own profile read (every request) is unchanged by
    # the new columns.
    from app.auth.context import _load_profile_with_roles

    assert _load_profile_with_roles(alice)[:2] == ("Profile Test User", _row(alice)["email"])


def test_an_existing_profile_with_nulls_still_saves(users):
    alice = users()
    before = _row(alice)

    saved = service.update_own_profile(alice, {"phone": "+65 9123 4567"})

    assert saved == {**UNSET, "phone": "+65 9123 4567"}
    after = _row(alice)
    for unchanged in ("name", "email", "created_at"):
        assert after[unchanged] == before[unchanged], unchanged
    assert (after["organisation"], after["notify_email"], after["notify_sms"]) == (None, None, None)
    # Rewritten by the app. Not compared with >=: it is set from the app's
    # clock and created_at from the database's, which can differ slightly.
    assert after["updated_at"] != before["updated_at"]


def test_saving_all_three_and_reading_them_back(users):
    alice = users()
    payload = {"phone": "9123 4567", "organisation": "SMU", "notify_email": False, "notify_sms": True}

    service.update_own_profile(alice, payload)

    assert service.get_contact(alice) == payload


def test_saving_with_the_optional_ones_blank_stores_null(users):
    alice = users()
    service.update_own_profile(alice, {"phone": "9123 4567", "organisation": "SMU", "notify_email": True})

    service.update_own_profile(alice, {"phone": "", "organisation": "  ", "notify_email": None, "notify_sms": None})

    assert {field: _row(alice)[field] for field in service.CONTACT_FIELDS} == UNSET


def test_the_update_touches_only_the_callers_row(users):
    alice, bob = users(), users()
    service.update_own_profile(bob, {"phone": "8000 0000", "organisation": "Bob Org"})

    service.update_own_profile(alice, {"phone": "9123 4567", "organisation": "Alice Org"})

    assert (_row(bob)["phone"], _row(bob)["organisation"]) == ("8000 0000", "Bob Org")


# -- the table's own checks -----------------------------------------------------------


@pytest.mark.parametrize("change", [{"phone": ""}, {"phone": "   "}, {"organisation": ""}, {"organisation": "x" * 201}])
def test_the_database_refuses_blank_or_oversized_text(users, change):
    alice = users()

    with pytest.raises(APIError) as refused:
        supabase.table("profiles").update(change).eq("id", alice).execute()

    assert refused.value.code == "23514"  # check_violation


# -- the organisation copy into registrations, with no data --------------------------


def test_with_nothing_saved_the_registration_organisation_copy_finds_nothing(users):
    """registration_service._db_profile_organisation (Justin's, select "*")
    is one of the two pieces of existing code these columns activate. With
    the column NULL it returns None -- exactly what it returned before the
    column existed -- so a registration ticking "include organisation"
    still records none."""
    alice = users()

    assert _db_profile_organisation(alice) is None

    service.update_own_profile(alice, {"organisation": "SMU"})
    assert _db_profile_organisation(alice) == "SMU"


# -- RLS -------------------------------------------------------------------------------


def test_a_signed_in_user_cannot_write_any_profile_directly(users):
    alice, bob = users(), users()
    client = _signed_in_as(alice)

    # No update policy: RLS matches no row, so nothing changes -- not even
    # the caller's own. Writes go through PATCH /me/profile only.
    client.table("profiles").update({"phone": "9123 4567"}).eq("id", alice).execute()
    client.table("profiles").update({"phone": "9123 4567"}).eq("id", bob).execute()

    assert _row(alice)["phone"] is None
    assert _row(bob)["phone"] is None


def test_open_question_a_signed_in_user_can_still_read_another_users_phone_directly(users):
    """NOT the desired state -- the current one, pinned so it can't change
    unnoticed. The pre-existing "authenticated read profiles" policy lets
    any signed-in user select every profile, and that now includes phone.
    Logged in docs/open-questions.md (IS-68); when that policy is narrowed,
    this test should flip to asserting the row is hidden."""
    alice, bob = users(), users()
    service.update_own_profile(bob, {"phone": "8000 0000"})

    seen = _signed_in_as(alice).table("profiles").select("id, phone").eq("id", bob).execute().data

    assert seen == [{"id": bob, "phone": "8000 0000"}]
