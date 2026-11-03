"""Live Supabase integration tests for Notification (Attendees) (IS-22) --
what the unit tests' in-memory fake can't prove:

- the real register_attendee / withdraw_registration functions: who ends
  up confirmed, waitlisted (and in which place) and moved up, and that the
  id withdraw_registration returns finds the promoted attendee
- recipients read from real registrations (only that session's confirmed
  and waitlisted attendees)
- "changed since the last confirmation" against real event_status_log
  rows written by transitions.transition(), real event_logs rows, and real
  venue_bookings / venue_booking_status_log rows -- column names, the
  status filter, and Postgres's own timestamp format

Needs a local stack (`npx supabase start && npx supabase db reset`), like
every other integration test.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import app.notifications.notification_service as service
from app.events.transitions import transition
from app.extensions import supabase
from app.registrations.registration_service import register, withdraw

pytestmark = pytest.mark.integration

DETAILS = {"email": "attendee@example.com", "phone": "91234567", "notify_email": True, "notify_sms": False}

_PASSWORD = "Password123!-throwaway-test-account"


def _create_user(roles: list[str]) -> str:
    email = f"attendee-notification-test-{uuid.uuid4()}@example.com"
    created = supabase.auth.admin.create_user({"email": email, "password": _PASSWORD, "email_confirm": True})
    user_id = created.user.id
    supabase.table("profiles").insert({"id": user_id, "name": "Attendee Notification Test", "email": email}).execute()
    for role in roles:
        supabase.table("user_roles").insert({"user_id": user_id, "role": role}).execute()
    return user_id


def _delete_user(user_id: str) -> None:
    # Their notifications go with the profile (on delete cascade).
    supabase.table("user_roles").delete().eq("user_id", user_id).execute()
    supabase.table("profiles").delete().eq("id", user_id).execute()
    supabase.auth.admin.delete_user(user_id)


def _types(user_id: str) -> list[str]:
    rows = supabase.table("notifications").select("type, created_at").eq("recipient_id", user_id).execute().data
    return [row["type"] for row in sorted(rows, key=lambda row: row["created_at"])]


def _messages(user_id: str) -> list[str]:
    rows = supabase.table("notifications").select("message").eq("recipient_id", user_id).execute().data
    return [row["message"] for row in rows]


@pytest.fixture
def world():
    organizer = _create_user(["event_organizer"])
    coordinator = _create_user(["event_coordinator"])
    attendees = [_create_user(["attendee"]) for _ in range(3)]
    event_ids: list[str] = []
    venue_ids: list[str] = []
    now = datetime.now(UTC)

    def session(capacity=1, **overrides):
        row = {
            "name": f"Attendee Notification Test {uuid.uuid4()}",
            "organizer_id": organizer,
            "coordinator_id": coordinator,
            "status": "confirmed",
            "registration_needs": True,
            "expected_attendance": capacity,
            "preferred_start_date": (now + timedelta(days=30)).date().isoformat(),
            "preferred_start_time": "14:00:00",
            "registration_start_datetime": (now - timedelta(days=1)).isoformat(),
            "registration_end_datetime": (now + timedelta(days=1)).isoformat(),
            **overrides,
        }
        created = supabase.table("events").insert(row).execute().data[0]
        event_ids.append(created["id"])
        return SimpleNamespace(**created)

    def venue():
        created = (
            supabase.table("venues")
            .insert({"name": f"Attendee Notification Venue {uuid.uuid4()}", "location": "Test", "capacity": 100})
            .execute()
            .data[0]
        )
        venue_ids.append(created["id"])
        return created["id"]

    try:
        yield SimpleNamespace(
            session=session, venue=venue, organizer=organizer, coordinator=coordinator, attendees=attendees, now=now
        )
    finally:
        for event_id in event_ids:
            # event_logs keep their request id (event_id is set null), so go by it.
            supabase.table("event_logs").delete().eq("shared_event_id", event_id).execute()
            # registrations, bookings (and their log) and status history cascade.
            supabase.table("events").delete().eq("id", event_id).execute()
        for venue_id in venue_ids:
            supabase.table("venues").delete().eq("id", venue_id).execute()
        for user_id in [organizer, coordinator, *attendees]:
            _delete_user(user_id)


def _first_confirmation(event_id: str, actor: str) -> None:
    """The session was confirmed once before the test begins (inserted as
    confirmed, so transition() never wrote that history row)."""
    supabase.table("event_status_log").insert(
        {"event_id": event_id, "from_status": "safety_review", "to_status": "confirmed", "changed_by": actor}
    ).execute()


def _back_to_planning_and_confirmed_again(event_id: str, actor: str) -> None:
    """A change sends the session back to planning; it goes through its
    safety check again and is confirmed again -- through the real
    transition(), which writes the real history rows."""
    transition(event_id, "planning", actor, reason="Change after confirmation", expected_from="confirmed")
    transition(event_id, "safety_review", actor, expected_from="planning")
    transition(event_id, "confirmed", actor, expected_from="safety_review")


def _log_change(event, changes: dict, actor: str) -> None:
    supabase.table("event_logs").insert(
        {
            "shared_event_id": event.shared_event_id or event.id,
            "event_id": event.id,
            "changes": changes,
            "significance": "significant",
            "changed_by": actor,
        }
    ).execute()


def _book(event, venue_id: str, actor: str, status: str) -> str:
    start = datetime(2099, 1, 1, tzinfo=UTC) + timedelta(minutes=uuid.uuid4().int % 500_000)
    booking = (
        supabase.table("venue_bookings")
        .insert(
            {
                "event_id": event.id,
                "venue_id": venue_id,
                "status": status,
                "requested_by": actor,
                "setup_minutes": 30,
                "turnaround_minutes": 30,
                "booking_start": start.isoformat(),
                "booking_end": (start + timedelta(hours=2)).isoformat(),
            }
        )
        .execute()
        .data[0]
    )
    supabase.table("venue_booking_status_log").insert(
        {"booking_id": booking["id"], "from_status": None, "to_status": status, "changed_by": actor}
    ).execute()
    return booking["id"]


def _cancel_booking(booking_id: str, actor: str) -> None:
    supabase.table("venue_bookings").update({"status": "cancelled"}).eq("id", booking_id).execute()
    supabase.table("venue_booking_status_log").insert(
        {"booking_id": booking_id, "from_status": "confirmed", "to_status": "cancelled", "changed_by": actor,
         "reason": "Venue unavailable"}
    ).execute()


# -- AC1-AC4: registering and withdrawing --------------------------------------------


def test_registering_and_withdrawing_notify_the_right_attendees(world):
    event = world.session(capacity=1)
    a1, a2, a3 = world.attendees
    for attendee in (a1, a2, a3):
        register(event, attendee, DETAILS)

    assert _types(a1) == [service.REGISTRATION_CONFIRMED]
    assert _types(a2) == [service.REGISTRATION_WAITLISTED]
    assert _types(a3) == [service.REGISTRATION_WAITLISTED]
    assert _messages(a2)[0].endswith("You are number 1 on the waiting list.")
    assert _messages(a3)[0].endswith("You are number 2 on the waiting list.")

    assert withdraw(event.id, a1) == {"withdrawn": True, "promoted": True}

    assert _types(a1) == [service.REGISTRATION_CONFIRMED, service.REGISTRATION_WITHDRAWN]
    assert _types(a2) == [service.REGISTRATION_WAITLISTED, service.REGISTRATION_PROMOTED]
    assert _types(a3) == [service.REGISTRATION_WAITLISTED]


# -- AC8 / AC10: cancellation ---------------------------------------------------------


def test_cancelling_notifies_only_current_attendees(world):
    event = world.session(capacity=1)
    other = world.session(capacity=5)
    a1, a2, a3 = world.attendees
    register(event, a1, DETAILS)
    register(event, a2, DETAILS)  # waitlisted
    register(other, a3, DETAILS)  # a different session

    transition(event.id, "cancelled", world.coordinator, reason="No venue", expected_from="confirmed")
    service.event_cancelled(event.id)

    assert service.EVENT_CANCELLED in _types(a1)
    assert service.EVENT_CANCELLED in _types(a2)
    assert service.EVENT_CANCELLED not in _types(a3)
    cancelled = supabase.table("notifications").select("*").eq("type", service.EVENT_CANCELLED).eq(
        "recipient_id", a1
    ).execute().data[0]
    assert (cancelled["entity_type"], cancelled["entity_id"]) == (None, None)


# -- AC5 / AC7: confirmed again -----------------------------------------------------------


def test_a_time_change_is_told_when_the_session_is_confirmed_again(world):
    event = world.session(capacity=5)
    a1, a2, _ = world.attendees
    register(event, a1, DETAILS)
    register(event, a2, DETAILS)
    _first_confirmation(event.id, world.coordinator)

    _log_change(event, {"preferred_start_time": {"from": "14:00:00", "to": "15:00:00"}}, world.coordinator)
    _back_to_planning_and_confirmed_again(event.id, world.coordinator)
    service.event_reconfirmed(event.id)

    for attendee in (a1, a2):
        assert _types(attendee)[-1] == service.EVENT_DETAILS_UPDATED
    updated = supabase.table("notifications").select("*").eq("type", service.EVENT_DETAILS_UPDATED).eq(
        "recipient_id", a1
    ).execute().data[0]
    assert (updated["entity_type"], updated["entity_id"]) == (service.ENTITY_ATTENDEE_EVENT, event.id)


def test_an_irrelevant_change_or_an_organiser_request_tells_nobody(world):
    event = world.session(capacity=5)
    a1 = world.attendees[0]
    register(event, a1, DETAILS)
    _first_confirmation(event.id, world.coordinator)

    _log_change(event, {"description": {"from": "a", "to": "b"}}, world.coordinator)
    _log_change(event, {"preferred_start_time": {"from": "14:00:00", "to": "16:00:00"}}, world.organizer)
    _back_to_planning_and_confirmed_again(event.id, world.coordinator)
    service.event_reconfirmed(event.id)

    assert _types(a1) == [service.REGISTRATION_CONFIRMED]


def test_a_venue_swap_is_told_and_rebooking_the_same_venue_is_not(world):
    swapped, rebooked = world.session(capacity=5), world.session(capacity=5)
    a1, a2, _ = world.attendees
    register(swapped, a1, DETAILS)
    register(rebooked, a2, DETAILS)
    hall_a, hall_b = world.venue(), world.venue()

    first_swapped = _book(swapped, hall_a, world.coordinator, "confirmed")
    first_rebooked = _book(rebooked, hall_a, world.coordinator, "confirmed")
    _first_confirmation(swapped.id, world.coordinator)
    _first_confirmation(rebooked.id, world.coordinator)

    _cancel_booking(first_swapped, world.coordinator)
    _book(swapped, hall_b, world.coordinator, "confirmed")
    _cancel_booking(first_rebooked, world.coordinator)
    _book(rebooked, hall_a, world.coordinator, "confirmed")
    for event in (swapped, rebooked):
        _back_to_planning_and_confirmed_again(event.id, world.coordinator)
        service.event_reconfirmed(event.id)

    assert _types(a1)[-1] == service.EVENT_DETAILS_UPDATED
    assert _types(a2) == [service.REGISTRATION_CONFIRMED]
