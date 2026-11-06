"""Live Supabase integration test for the events.registration_needs
NOT NULL + default false migration (IS-21,
20261106000000_events_registration_needs_not_null.sql)."""

from __future__ import annotations

import uuid

import pytest
from postgrest.exceptions import APIError

from app.events.event_service import create_draft_request
from app.extensions import supabase

pytestmark = pytest.mark.integration

_PASSWORD = "Password123!-throwaway-test-account"


@pytest.fixture
def organizer():
    """A throwaway organiser. Every event it owns is deleted afterwards,
    then the account itself."""
    email = f"registration-needs-{uuid.uuid4()}@example.com"
    user_id = supabase.auth.admin.create_user(
        {"email": email, "password": _PASSWORD, "email_confirm": True}
    ).user.id
    try:
        supabase.table("profiles").insert(
            {"id": user_id, "name": "Registration Needs Test Organizer", "email": email}
        ).execute()
        supabase.table("user_roles").insert({"user_id": user_id, "role": "event_organizer"}).execute()
        yield user_id
    finally:
        supabase.table("events").delete().eq("organizer_id", user_id).execute()
        supabase.table("user_roles").delete().eq("user_id", user_id).execute()
        supabase.table("profiles").delete().eq("id", user_id).execute()
        supabase.auth.admin.delete_user(user_id)


def _only_session(created: dict) -> dict:
    [session] = created["sessions"]
    return supabase.table("events").select("id, registration_needs").eq("id", session["id"]).execute().data[0]


def test_a_draft_saved_without_registration_needs_stores_false(organizer):
    """The default: a half-filled draft that never set the field is "no
    registration", not NULL (and not a failed save)."""
    created = create_draft_request(organizer, {"name": "Half-filled draft", "sessions": [{}]})
    assert _only_session(created)["registration_needs"] is False


def test_registration_needs_cannot_be_set_to_null(organizer):
    """The constraint: the value old sessions had, which blocked their
    change requests, can't be written again."""
    created = create_draft_request(organizer, {"name": "Draft", "sessions": [{"registration_needs": True}]})
    row = _only_session(created)
    assert row["registration_needs"] is True

    with pytest.raises(APIError) as exc_info:
        supabase.table("events").update({"registration_needs": None}).eq("id", row["id"]).execute()
    assert exc_info.value.code == "23502"  # not_null_violation
