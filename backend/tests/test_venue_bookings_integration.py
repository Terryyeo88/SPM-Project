"""
Live Supabase integration tests for Venue Booking Request / Approval
(Josiah, Sprint 2) -- proves the migration
(supabase/migrations/20261004000000_venue_bookings.sql) actually applies
and app.venues.booking_service's writes/reads round-trip against a real
database, not just the in-memory fake in test_booking_service.py.

Same fixture/cleanup shape as test_coordinator_assignment_integration.py:
each test creates its own throwaway coordinator/organiser/venue/event and
deletes them afterwards, so tests are independent and re-runnable.
Skipped automatically without a local Supabase (see conftest.py).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.extensions import supabase
from app.shared.errors import ValidationError
from app.venues.booking_service import (
    confirm_booking,
    create_booking_request,
    get_booking,
    list_bookings,
    reject_booking,
)
from tests.factories import make_user

pytestmark = pytest.mark.integration

_PASSWORD = "Password123!-throwaway-test-account"


class _Fixtures:
    def __init__(self):
        self.booking_ids: list[str] = []
        self.event_ids: list[str] = []
        self.venue_ids: list[str] = []
        self.user_ids: list[str] = []

    def create_user(self, name: str, role: str) -> dict:
        email = f"test-{uuid.uuid4()}@example.com"
        created = supabase.auth.admin.create_user({"email": email, "password": _PASSWORD, "email_confirm": True})
        user_id = created.user.id
        self.user_ids.append(user_id)
        supabase.table("profiles").insert({"id": user_id, "name": name, "email": email}).execute()
        supabase.table("user_roles").insert({"user_id": user_id, "role": role}).execute()
        return {"id": user_id, "name": name, "email": email}

    def create_venue(self, **overrides) -> dict:
        payload = {
            "name": f"Integration Booking Venue {uuid.uuid4()}",
            "location": "Test Wing",
            "capacity": 100,
            "facilities": [],
            "accessibility_features": [],
            "supported_layouts": ["theatre"],
            "status": "available",
        }
        payload.update(overrides)
        result = supabase.table("venues").insert(payload).execute()
        venue = result.data[0]
        self.venue_ids.append(venue["id"])
        return venue

    def create_event(self, **fields) -> dict:
        defaults = {
            "name": f"Throwaway Booking Event {uuid.uuid4()}",
            "description": "integration test event -- safe to delete",
            "purpose": "testing",
            "expected_attendance": 10,
            "preferred_start_date": (date.today() + timedelta(days=30)).isoformat(),
            "preferred_end_date": (date.today() + timedelta(days=30)).isoformat(),
            "preferred_start_time": "09:00",
            "preferred_end_time": "17:00",
        }
        defaults.update(fields)
        result = supabase.table("events").insert(defaults).execute()
        event = result.data[0]
        self.event_ids.append(event["id"])
        return event

    def cleanup(self) -> None:
        for booking_id in self.booking_ids:
            supabase.table("venue_bookings").delete().eq("id", booking_id).execute()
        for event_id in self.event_ids:
            supabase.table("events").delete().eq("id", event_id).execute()
        for venue_id in self.venue_ids:
            supabase.table("venues").delete().eq("id", venue_id).execute()
        for user_id in self.user_ids:
            supabase.auth.admin.delete_user(user_id)


@pytest.fixture
def fixtures():
    f = _Fixtures()
    yield f
    f.cleanup()


def _event_namespace(event: dict) -> SimpleNamespace:
    return SimpleNamespace(**event)


def test_create_booking_request_persists_padded_span_and_moves_event_to_planning(fixtures):
    coordinator = fixtures.create_user("Booking Test Coordinator", "event_coordinator")
    organizer = fixtures.create_user("Booking Test Organizer", "event_organizer")
    venue = fixtures.create_venue(setup_minutes=20, turnaround_minutes=40)
    event = fixtures.create_event(
        organizer_id=organizer["id"], coordinator_id=coordinator["id"], status="approved"
    )

    booking = create_booking_request(_event_namespace(event), venue["id"], coordinator["id"])
    fixtures.booking_ids.append(booking["id"])

    assert booking["status"] == "pending"
    assert booking["setup_minutes"] == 20
    assert booking["turnaround_minutes"] == 40

    refreshed_event = supabase.table("events").select("status").eq("id", event["id"]).execute().data[0]
    assert refreshed_event["status"] == "planning"


def test_get_booking_reports_conflict_against_a_real_overlapping_confirmed_booking(fixtures):
    coordinator = fixtures.create_user("Conflict Test Coordinator", "event_coordinator")
    staff = fixtures.create_user("Conflict Test Staff", "venue_staff")
    organizer = fixtures.create_user("Conflict Test Organizer", "event_organizer")
    venue = fixtures.create_venue(setup_minutes=0, turnaround_minutes=0)

    start_date = (date.today() + timedelta(days=60)).isoformat()
    event_a = fixtures.create_event(
        organizer_id=organizer["id"],
        coordinator_id=coordinator["id"],
        status="approved",
        preferred_start_date=start_date,
        preferred_end_date=start_date,
        preferred_start_time="09:00",
        preferred_end_time="12:00",
    )
    event_b = fixtures.create_event(
        organizer_id=organizer["id"],
        coordinator_id=coordinator["id"],
        status="planning",
        preferred_start_date=start_date,
        preferred_end_date=start_date,
        preferred_start_time="11:00",
        preferred_end_time="14:00",
    )

    booking_a = create_booking_request(_event_namespace(event_a), venue["id"], coordinator["id"])
    fixtures.booking_ids.append(booking_a["id"])
    booking_b = create_booking_request(_event_namespace(event_b), venue["id"], coordinator["id"])
    fixtures.booking_ids.append(booking_b["id"])

    confirm_booking(booking_a["id"], _event_namespace(booking_a), staff["id"])

    fetched_b = get_booking(booking_b["id"])
    assert fetched_b["conflict"] is True

    with pytest.raises(ValidationError):
        confirm_booking(booking_b["id"], _event_namespace(booking_b), staff["id"])


def test_reject_booking_records_reason_coordinator_can_then_read(fixtures):
    coordinator = fixtures.create_user("Reject Test Coordinator", "event_coordinator")
    staff = fixtures.create_user("Reject Test Staff", "venue_staff")
    organizer = fixtures.create_user("Reject Test Organizer", "event_organizer")
    venue = fixtures.create_venue()
    event = fixtures.create_event(
        organizer_id=organizer["id"], coordinator_id=coordinator["id"], status="planning"
    )

    booking = create_booking_request(_event_namespace(event), venue["id"], coordinator["id"])
    fixtures.booking_ids.append(booking["id"])

    rejected = reject_booking(booking["id"], _event_namespace(booking), staff["id"], "Venue too small for this event.")
    assert rejected["status"] == "rejected"

    # The coordinator's actual read path: get_booking must surface the
    # reason itself (joined from venue_booking_status_log), not just the
    # "rejected" status -- see Approval AC2 ("the Coordinator can view it").
    fetched = get_booking(booking["id"])
    assert fetched["status"] == "rejected"
    assert fetched["rejection"]["reason"] == "Venue too small for this event."


def test_list_bookings_scoping_against_a_real_database(fixtures):
    coordinator_a = fixtures.create_user("List Test Coordinator A", "event_coordinator")
    coordinator_b = fixtures.create_user("List Test Coordinator B", "event_coordinator")
    organizer = fixtures.create_user("List Test Organizer", "event_organizer")
    venue = fixtures.create_venue()

    event_a = fixtures.create_event(
        organizer_id=organizer["id"], coordinator_id=coordinator_a["id"], status="planning"
    )
    event_b = fixtures.create_event(
        organizer_id=organizer["id"], coordinator_id=coordinator_b["id"], status="planning"
    )
    booking_a = create_booking_request(_event_namespace(event_a), venue["id"], coordinator_a["id"])
    fixtures.booking_ids.append(booking_a["id"])
    booking_b = create_booking_request(_event_namespace(event_b), venue["id"], coordinator_b["id"])
    fixtures.booking_ids.append(booking_b["id"])

    coordinator_a_view = list_bookings(make_user(["event_coordinator"], user_id=coordinator_a["id"]))
    assert {b["id"] for b in coordinator_a_view} & {booking_a["id"], booking_b["id"]} == {booking_a["id"]}


def test_list_bookings_embeds_event_and_venue_names_for_the_queue_ui(fixtures):
    """The venue_staff queue spans many events/venues at once, so each
    row needs more than a bare event_id/venue_id to be recognisable --
    see list_bookings' own comment on the events(name)/venues(name)
    embed."""
    coordinator = fixtures.create_user("Embed Test Coordinator", "event_coordinator")
    staff = fixtures.create_user("Embed Test Staff", "venue_staff")
    organizer = fixtures.create_user("Embed Test Organizer", "event_organizer")
    venue = fixtures.create_venue(name=f"Embed Test Venue {uuid.uuid4()}")
    event = fixtures.create_event(
        organizer_id=organizer["id"],
        coordinator_id=coordinator["id"],
        status="planning",
        name=f"Embed Test Event {uuid.uuid4()}",
    )

    booking = create_booking_request(_event_namespace(event), venue["id"], coordinator["id"])
    fixtures.booking_ids.append(booking["id"])

    staff_view = list_bookings(make_user(["venue_staff"], user_id=staff["id"]))
    fetched = next(b for b in staff_view if b["id"] == booking["id"])
    assert fetched["events"]["name"] == event["name"]
    assert fetched["venues"]["name"] == venue["name"]
