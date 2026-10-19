"""
Live Supabase integration tests for IS-9 Update Event Information During
Planning -- what the unit tests' in-memory fakes can't prove:

  - 20261019300000_venue_booking_cancel.sql: the 'cancelled' booking status
    exists, cancelling one booking leaves the session's others as they were,
    and a cancelled booking stops holding the venue (the IS-16 exclusion
    constraint covers confirmed rows only);
  - the PostgREST embeds the code relies on: venues(name) on a session's
    bookings, events(...) on a single booking (for Venue Staff), and the
    venue name in the preview's touched arrangements;
  - 20261019400000_event_logs_session.sql: event_logs.event_id is written
    with the session a change was made on, the Change History labels it,
    and the entry outlives a deleted session (ON DELETE SET NULL).

Same fixture/cleanup shape as test_venue_bookings_integration.py: every test
creates its own throwaway users/venues/events and removes them afterwards.
Skipped automatically without a local Supabase (see conftest.py).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.events.event_log import list_event_logs
from app.events.event_update import preview_event_update, update_event
from app.extensions import supabase
from app.venues.booking_service import (
    BOOKING_EVENT_FIELDS,
    cancel_booking,
    confirm_booking,
    create_booking_request,
    get_booking,
    list_bookings_for_event,
)

pytestmark = pytest.mark.integration

_PASSWORD = "Password123!-throwaway-test-account"


class _Fixtures:
    def __init__(self):
        self.shared_event_ids: list[str] = []
        self.booking_ids: list[str] = []
        self.event_ids: list[str] = []
        self.venue_ids: list[str] = []
        self.user_ids: list[str] = []

    def create_user(self, name: str, role: str) -> str:
        email = f"is9-test-{uuid.uuid4()}@example.com"
        created = supabase.auth.admin.create_user({"email": email, "password": _PASSWORD, "email_confirm": True})
        user_id = created.user.id
        self.user_ids.append(user_id)
        supabase.table("profiles").insert({"id": user_id, "name": name, "email": email}).execute()
        supabase.table("user_roles").insert({"user_id": user_id, "role": role}).execute()
        return user_id

    def create_venue(self, name: str) -> dict:
        venue = (
            supabase.table("venues")
            .insert(
                {
                    "name": f"{name} {uuid.uuid4()}",
                    "location": "Test Wing",
                    "capacity": 200,
                    "facilities": [],
                    "accessibility_features": [],
                    "supported_layouts": ["theatre"],
                    "status": "available",
                    "setup_minutes": 0,
                    "turnaround_minutes": 0,
                }
            )
            .execute()
            .data[0]
        )
        self.venue_ids.append(venue["id"])
        return venue

    def create_session(self, organizer: str, coordinator: str, shared_event_id: str, days_ahead: int, **fields):
        day = (date.today() + timedelta(days=days_ahead)).isoformat()
        row = {
            "name": "IS-9 Integration Event",
            "description": "integration test event -- safe to delete",
            "purpose": "testing",
            "organizer_id": organizer,
            "coordinator_id": coordinator,
            "status": "planning",
            "shared_event_id": shared_event_id,
            "preferred_start_date": day,
            "preferred_end_date": day,
            "preferred_start_time": "09:00",
            "preferred_end_time": "12:00",
            "expected_attendance": 50,
            "room_layout": "theatre",
            "registration_needs": False,
            "equipment_needed": {"equipment": []},
        }
        row.update(fields)
        event = supabase.table("events").insert(row).execute().data[0]
        self.event_ids.append(event["id"])
        if shared_event_id not in self.shared_event_ids:
            self.shared_event_ids.append(shared_event_id)
        return event

    def book(self, event: dict, venue: dict, coordinator: str) -> dict:
        booking = create_booking_request(SimpleNamespace(**event), venue["id"], coordinator)
        self.booking_ids.append(booking["id"])
        return booking

    def cleanup(self) -> None:
        for shared_event_id in self.shared_event_ids:
            supabase.table("event_logs").delete().eq("shared_event_id", shared_event_id).execute()
        for booking_id in self.booking_ids:  # their status log rows cascade
            supabase.table("venue_bookings").delete().eq("id", booking_id).execute()
        for event_id in self.event_ids:
            supabase.table("events").delete().eq("id", event_id).execute()
        for venue_id in self.venue_ids:
            supabase.table("venues").delete().eq("id", venue_id).execute()
        for user_id in self.user_ids:
            supabase.table("user_roles").delete().eq("user_id", user_id).execute()
            supabase.table("profiles").delete().eq("id", user_id).execute()
            supabase.auth.admin.delete_user(user_id)


@pytest.fixture
def fixtures():
    f = _Fixtures()
    yield f
    f.cleanup()


@pytest.fixture
def people(fixtures):
    return SimpleNamespace(
        organizer=fixtures.create_user("IS-9 Organiser", "event_organizer"),
        coordinator=fixtures.create_user("IS-9 Coordinator", "event_coordinator"),
        staff=fixtures.create_user("IS-9 Venue Staff", "venue_staff"),
    )


def _status(booking_id: str) -> str:
    return supabase.table("venue_bookings").select("status").eq("id", booking_id).execute().data[0]["status"]


def _confirm(booking: dict, staff: str) -> dict:
    return confirm_booking(booking["id"], SimpleNamespace(**booking), staff)


# -- cancelling one venue booking ----------------------------------------------


def test_cancelling_one_booking_leaves_the_sessions_other_bookings_in_place(fixtures, people):
    session = fixtures.create_session(people.organizer, people.coordinator, str(uuid.uuid4()), 40)
    hall = _confirm(fixtures.book(session, fixtures.create_venue("Main Hall"), people.coordinator), people.staff)
    room = _confirm(fixtures.book(session, fixtures.create_venue("Breakout Room"), people.coordinator), people.staff)
    pending = fixtures.book(session, fixtures.create_venue("Overflow Room"), people.coordinator)

    cancelled = cancel_booking(hall["id"], SimpleNamespace(**hall), people.coordinator, "Moved to the auditorium.")

    assert cancelled["status"] == "cancelled"
    assert _status(hall["id"]) == "cancelled"
    assert _status(room["id"]) == "confirmed"
    assert _status(pending["id"]) == "pending"
    session_status = supabase.table("events").select("status").eq("id", session["id"]).execute().data[0]["status"]
    assert session_status == "planning"

    [log] = (
        supabase.table("venue_booking_status_log")
        .select("*")
        .eq("booking_id", hall["id"])
        .eq("to_status", "cancelled")
        .execute()
        .data
    )
    assert log["from_status"] == "confirmed"
    assert log["changed_by"] == people.coordinator
    assert log["reason"] == "Moved to the auditorium."
    assert log["changed_at"]


def test_a_cancelled_booking_frees_the_venue_for_another_event(fixtures, people):
    """The no-overlap exclusion constraint covers confirmed rows only, so
    once a booking is cancelled an overlapping booking can be confirmed."""
    venue = fixtures.create_venue("Shared Hall")
    first = fixtures.create_session(people.organizer, people.coordinator, str(uuid.uuid4()), 41)
    second = fixtures.create_session(people.organizer, people.coordinator, str(uuid.uuid4()), 41)
    held = _confirm(fixtures.book(first, venue, people.coordinator), people.staff)
    waiting = fixtures.book(second, venue, people.coordinator)

    cancel_booking(held["id"], SimpleNamespace(**held), people.coordinator, "Not needed.")

    assert _confirm(waiting, people.staff)["status"] == "confirmed"


def test_the_coordinator_sees_each_booking_with_its_venue_and_why_one_was_cancelled(fixtures, people):
    session = fixtures.create_session(people.organizer, people.coordinator, str(uuid.uuid4()), 42)
    hall_venue = fixtures.create_venue("Main Hall")
    hall = fixtures.book(session, hall_venue, people.coordinator)
    fixtures.book(session, fixtures.create_venue("Breakout Room"), people.coordinator)
    cancel_booking(hall["id"], SimpleNamespace(**hall), people.coordinator, "Moved.")

    bookings = {row["id"]: row for row in list_bookings_for_event(session["id"])}

    assert len(bookings) == 2
    assert bookings[hall["id"]]["venues"]["name"] == hall_venue["name"]
    assert bookings[hall["id"]]["cancellation"]["reason"] == "Moved."
    assert bookings[hall["id"]]["cancellation"]["cancelled_by"] == "IS-9 Coordinator"


# -- Venue Staff read the booking's event details through the booking ------------


def test_a_booking_carries_exactly_the_event_details_its_review_needs(fixtures, people):
    session = fixtures.create_session(people.organizer, people.coordinator, str(uuid.uuid4()), 43)
    booking = fixtures.book(session, fixtures.create_venue("Review Hall"), people.coordinator)

    fetched = get_booking(booking["id"])

    expected = {field.strip() for field in BOOKING_EVENT_FIELDS.split(",")}
    assert set(fetched["event"]) == expected
    assert fetched["event"]["id"] == session["id"]
    assert fetched["event"]["expected_attendance"] == 50
    assert "organizer_id" not in fetched["event"]
    assert "events" not in fetched


# -- the preview presents what a change touches ---------------------------------


def test_the_preview_names_the_booked_venue_a_change_touches(fixtures, people):
    session = fixtures.create_session(people.organizer, people.coordinator, str(uuid.uuid4()), 44)
    venue = fixtures.create_venue("Preview Hall")
    booking = fixtures.book(session, venue, people.coordinator)

    preview = preview_event_update(SimpleNamespace(**session), {"expected_attendance": 80})

    assert preview["arrangements"] == [
        {
            "area": "venue",
            "id": booking["id"],
            "title": f"Venue booking: {venue['name']}",
            "status": "pending",
            "fields": ["expected_attendance"],
        }
    ]
    stored = supabase.table("events").select("expected_attendance").eq("id", session["id"]).execute().data[0]
    assert stored["expected_attendance"] == 50  # the preview writes nothing


# -- the change history names the session ----------------------------------------


def test_an_update_is_logged_against_its_session_and_labelled_in_the_history(fixtures, people):
    group = str(uuid.uuid4())
    fixtures.create_session(people.organizer, people.coordinator, group, 45)
    later = fixtures.create_session(people.organizer, people.coordinator, group, 46)

    update_event(SimpleNamespace(**later), {"expected_attendance": 60}, people.coordinator)

    [stored] = supabase.table("event_logs").select("*").eq("shared_event_id", group).execute().data
    assert stored["event_id"] == later["id"]
    [entry] = list_event_logs(SimpleNamespace(**later))
    assert entry["session"] == {"id": later["id"], "number": 2, "label": "Session 2"}
    assert entry["profiles"]["name"] == "IS-9 Coordinator"


def test_a_history_entry_outlives_its_deleted_session(fixtures, people):
    group = str(uuid.uuid4())
    session = fixtures.create_session(people.organizer, people.coordinator, group, 47)
    update_event(SimpleNamespace(**session), {"expected_attendance": 60}, people.coordinator)

    supabase.table("events").delete().eq("id", session["id"]).execute()

    [stored] = supabase.table("event_logs").select("*").eq("shared_event_id", group).execute().data
    assert stored["event_id"] is None
    assert stored["changes"] == {"expected_attendance": {"from": 50, "to": 60}}


# -- AC2 / AC4 / AC10 against the real tables ---------------------------------------


def test_a_change_to_a_confirmed_event_is_logged_significant_and_sends_it_back_to_planning(fixtures, people):
    """The coordinator's own update (not only an approved change request):
    the stored log entry carries significance, and the revert goes through
    transition(), so event_status_log records who, when and why."""
    group = str(uuid.uuid4())
    session = fixtures.create_session(people.organizer, people.coordinator, group, 48, status="confirmed")

    updated = update_event(SimpleNamespace(**session), {"expected_attendance": 70}, people.coordinator)

    assert updated["status"] == "planning"
    stored = supabase.table("events").select("status, expected_attendance").eq("id", session["id"]).execute().data[0]
    assert stored == {"status": "planning", "expected_attendance": 70}

    [entry] = supabase.table("event_logs").select("*").eq("shared_event_id", group).execute().data
    assert entry["significance"] == "significant"
    assert entry["changed_by"] == people.coordinator
    assert entry["changed_at"]

    [revert] = (
        supabase.table("event_status_log")
        .select("*")
        .eq("event_id", session["id"])
        .eq("to_status", "planning")
        .execute()
        .data
    )
    assert revert["from_status"] == "confirmed"
    assert revert["changed_by"] == people.coordinator
    assert "expected attendance" in revert["reason"]


def test_an_ordinary_change_is_stored_as_ordinary(fixtures, people):
    group = str(uuid.uuid4())
    session = fixtures.create_session(people.organizer, people.coordinator, group, 49)

    update_event(SimpleNamespace(**session), {"special_requests": "Vegetarian lunch."}, people.coordinator)

    [entry] = supabase.table("event_logs").select("significance").eq("shared_event_id", group).execute().data
    assert entry["significance"] == "ordinary"
