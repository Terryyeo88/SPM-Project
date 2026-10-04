"""Live Supabase integration tests for Attendee Registration -- what the
unit tests can't prove, because the decision lives in the database
function public.register_attendee:

- capacity (expected_attendance) fills up, then registrations are waitlisted
- the registration window and "confirmed + enabled" are enforced by it
- one registration per attendee per session
- the rows the service reads back (places left, waiting-list position)

Needs a local stack (`npx supabase start && npx supabase db reset`), like
every other integration test.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.extensions import supabase
from app.registrations.registration_service import list_my_registrations, list_open_sessions, register, withdraw
from app.shared.errors import ValidationError

pytestmark = pytest.mark.integration

DETAILS = {"email": "attendee@example.com", "phone": "91234567", "notify_email": True, "notify_sms": False}

_PASSWORD = "Password123!-throwaway-test-account"


def _create_user(roles: list[str]) -> str:
    email = f"registration-test-{uuid.uuid4()}@example.com"
    created = supabase.auth.admin.create_user({"email": email, "password": _PASSWORD, "email_confirm": True})
    user_id = created.user.id
    supabase.table("profiles").insert({"id": user_id, "name": "Registration Test User", "email": email}).execute()
    for role in roles:
        supabase.table("user_roles").insert({"user_id": user_id, "role": role}).execute()
    return user_id


def _delete_user(user_id: str) -> None:
    supabase.table("user_roles").delete().eq("user_id", user_id).execute()
    supabase.table("profiles").delete().eq("id", user_id).execute()
    supabase.auth.admin.delete_user(user_id)


@pytest.fixture
def world():
    organizer = _create_user(["event_organizer"])
    attendees = [_create_user(["attendee"]) for _ in range(3)]
    event_ids: list[str] = []
    now = datetime.now(UTC)

    def session(capacity=2, opens=now - timedelta(days=1), closes=now + timedelta(days=1), **overrides):
        row = {
            "name": f"Registration Test {uuid.uuid4()}",
            "organizer_id": organizer,
            "status": "confirmed",
            "registration_needs": True,
            "expected_attendance": capacity,
            "preferred_start_date": (now + timedelta(days=30)).date().isoformat(),
            "registration_start_datetime": opens.isoformat() if opens else None,
            "registration_end_datetime": closes.isoformat() if closes else None,
            **overrides,
        }
        created = supabase.table("events").insert(row).execute().data[0]
        event_ids.append(created["id"])
        return SimpleNamespace(**created)

    try:
        yield SimpleNamespace(session=session, attendees=attendees, now=now)
    finally:
        for event_id in event_ids:  # registrations cascade with their session
            supabase.table("events").delete().eq("id", event_id).execute()
        for user_id in [organizer, *attendees]:
            _delete_user(user_id)


def test_capacity_fills_then_waitlists_first_come_first_served(world):
    event = world.session(capacity=2)
    a1, a2, a3 = world.attendees

    statuses = [register(event, attendee, DETAILS)["status"] for attendee in (a1, a2, a3)]

    assert statuses == ["confirmed", "confirmed", "waitlisted"]
    listed = next(s for s in list_open_sessions() if s["id"] == event.id)
    assert (listed["places_left"], listed["waitlist_count"]) == (0, 1)
    (mine,) = list_my_registrations(a3)
    assert (mine["status"], mine["waitlist_position"]) == ("waitlisted", 1)
    assert (mine["email"], mine["notify_email"], mine["notify_sms"]) == ("attendee@example.com", True, False)


def test_one_registration_per_attendee_per_session(world):
    event = world.session()
    register(event, world.attendees[0], DETAILS)
    with pytest.raises(ValidationError, match="already registered"):
        register(event, world.attendees[0], DETAILS)


def test_registration_only_during_the_window(world):
    not_yet = world.session(opens=world.now + timedelta(days=2))
    over = world.session(opens=world.now - timedelta(days=5), closes=world.now - timedelta(days=1))
    with pytest.raises(ValidationError, match="opens on"):
        register(not_yet, world.attendees[0], DETAILS)
    with pytest.raises(ValidationError, match="closed on"):
        register(over, world.attendees[0], DETAILS)


def test_the_database_refuses_a_session_that_is_not_confirmed(world):
    """Defence in depth: even if authz were bypassed, the function refuses."""
    planning = world.session(status="planning")
    with pytest.raises(ValidationError, match="no longer open"):
        register(planning, world.attendees[0], DETAILS)


def test_withdrawing_a_confirmed_place_moves_the_first_waitlisted_attendee_up(world):
    event = world.session(capacity=1)
    a1, a2, a3 = world.attendees
    for attendee in (a1, a2, a3):
        register(event, attendee, DETAILS)

    assert withdraw(event.id, a1) == {"withdrawn": True, "promoted": True}
    assert list_my_registrations(a2)[0]["status"] == "confirmed"
    (still_waiting,) = list_my_registrations(a3)
    assert (still_waiting["status"], still_waiting["waitlist_position"]) == ("waitlisted", 1)
