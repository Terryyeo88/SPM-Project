"""Live Supabase tests for IS-61 CRUD in Venue Catalogue: what the unit tests'
fakes (test_venue_catalogue_crud.py) can't prove. See
supabase/migrations/20261023100000_venue_catalogue_crud.sql.

  AC1  an added venue is stored and listed in the catalogue.
  AC2  an edit is stored; a deleted venue can't be edited.
  AC3  a deleted venue leaves the catalogue but can still be looked up.
  AC4  deleting releases the pending/confirmed bookings of ongoing events
       (cancelled, flagged released_by_venue_deletion, logged with a
       reason) and leaves completed/cancelled/rejected events' bookings
       alone; a confirmed session returns to planning, and one under a
       safety check has the check withdrawn and returns to planning.

Also: the database refuses a new booking, or an approval, on a deleted venue;
and only the backend (service role) can delete or change a venue -- a
signed-in user, even Venue Staff, calling the database directly can't.

Every test creates its own throwaway users, venue and events and removes
them afterwards. Skipped automatically without a local Supabase (see
conftest.py).
"""

from __future__ import annotations

import os
import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from postgrest.exceptions import APIError
from supabase import create_client

from app.extensions import supabase
from app.shared.errors import ValidationError
from app.venues import venue_service as service
from app.venues.booking_service import confirm_booking, create_booking_request
from app.venues.venue_service import VenueDeletedError

pytestmark = pytest.mark.integration

_PASSWORD = "Password123!-throwaway-test-account"
FINISHED_STATUSES = ["completed", "cancelled", "rejected"]


class _Fixtures:
    def __init__(self):
        self.event_ids: list[str] = []
        self.venue_ids: list[str] = []
        self.user_ids: list[str] = []
        self._organizer: str | None = None

    def user(self, role: str) -> str:
        email = f"venue-crud-{uuid.uuid4()}@example.com"
        user_id = supabase.auth.admin.create_user(
            {"email": email, "password": _PASSWORD, "email_confirm": True}
        ).user.id
        self.user_ids.append(user_id)
        supabase.table("profiles").insert({"id": user_id, "name": f"Venue CRUD {role}", "email": email}).execute()
        supabase.table("user_roles").insert({"user_id": user_id, "role": role}).execute()
        return user_id

    def venue(self, **overrides) -> dict:
        venue = service.create_venue(
            {
                "name": f"IS-61 Venue {uuid.uuid4()}",
                "location": "Test Wing",
                "capacity": 100,
                "supported_layouts": ["theatre"],
                **overrides,
            }
        )
        self.venue_ids.append(venue["id"])
        return venue

    def event(self, coordinator_id: str, status: str = "planning") -> dict:
        day = (date.today() + timedelta(days=40)).isoformat()
        if self._organizer is None:
            self._organizer = self.user("event_organizer")
        row = {
            "organizer_id": self._organizer,
            "name": f"IS-61 event {uuid.uuid4()}",
            "status": status,
            "coordinator_id": coordinator_id,
            "expected_attendance": 10,
            "preferred_start_date": day,
            "preferred_end_date": day,
            "preferred_start_time": "09:00",
            "preferred_end_time": "12:00",
        }
        event = supabase.table("events").insert(row).execute().data[0]
        self.event_ids.append(event["id"])
        return event

    def booking(self, event: dict, venue: dict, requested_by: str, status: str = "confirmed") -> dict:
        booking = create_booking_request(SimpleNamespace(**event), venue["id"], requested_by)
        if status != "pending":
            booking = (
                supabase.table("venue_bookings").update({"status": status}).eq("id", booking["id"]).execute().data[0]
            )
        return booking

    def cleanup(self) -> None:
        for event_id in self.event_ids:
            supabase.table("events").delete().eq("id", event_id).execute()
        for venue_id in self.venue_ids:
            supabase.table("venue_bookings").delete().eq("venue_id", venue_id).execute()
            supabase.table("venues").delete().eq("id", venue_id).execute()
        for user_id in self.user_ids:
            supabase.table("user_roles").delete().eq("user_id", user_id).execute()
            supabase.table("profiles").delete().eq("id", user_id).execute()
            supabase.auth.admin.delete_user(user_id)


@pytest.fixture
def f():
    fixtures = _Fixtures()
    yield fixtures
    fixtures.cleanup()


@pytest.fixture
def staff(f):
    return f.user("venue_staff")


@pytest.fixture
def coordinator(f):
    return f.user("event_coordinator")


def _booking(booking_id):
    return supabase.table("venue_bookings").select("*").eq("id", booking_id).single().execute().data


def _event_status(event_id):
    return supabase.table("events").select("status").eq("id", event_id).single().execute().data["status"]


def _catalogue_ids():
    return [venue["id"] for venue in service.list_venues()]


# -- AC1 / AC2 / AC3 -----------------------------------------------------------


def test_ac1_an_added_venue_is_stored_and_listed(f):
    venue = f.venue(
        facilities=["wifi"],
        accessibility_features=["wheelchair_access"],
        supported_layouts=["theatre"],
    )

    stored = service.get_venue(venue["id"])
    assert stored["facilities"] == ["wifi"]
    assert stored["supported_layouts"] == ["theatre"]
    # Not part of the form: a new venue has no set hours.
    assert (stored["operating_hours_start"], stored["operating_hours_end"]) == (None, None)
    assert stored["deleted_at"] is None
    assert venue["id"] in _catalogue_ids()


def test_ac2_an_edit_is_stored(f):
    venue = f.venue()

    service.update_venue(venue["id"], {"capacity": 42, "status": "maintenance", "setup_minutes": 5})

    stored = service.get_venue(venue["id"])
    assert (stored["capacity"], stored["status"], stored["setup_minutes"]) == (42, "maintenance", 5)


def test_ac2_the_database_refuses_a_negative_buffer_written_straight_to_the_table(f):
    venue = f.venue()

    with pytest.raises(APIError) as refused:
        supabase.table("venues").update({"turnaround_minutes": -1}).eq("id", venue["id"]).execute()
    assert refused.value.code == "23514"


def test_ac3_a_deleted_venue_leaves_the_catalogue_but_can_be_looked_up_and_not_edited(f, staff):
    venue = f.venue()

    result = service.delete_venue(venue["id"], staff)

    assert result["venue"]["deleted_at"]
    assert venue["id"] not in _catalogue_ids()
    stored = service.get_venue(venue["id"])
    assert (bool(stored["deleted_at"]), stored["deleted_by"]) == (True, staff)
    with pytest.raises(VenueDeletedError):
        service.update_venue(venue["id"], {"capacity": 5})
    with pytest.raises(VenueDeletedError, match="already been deleted"):
        service.delete_venue(venue["id"], staff)


# -- AC4 -----------------------------------------------------------------------


@pytest.mark.parametrize("booking_status", ["pending", "confirmed"])
def test_ac4_an_ongoing_events_booking_is_released_and_logged(f, staff, coordinator, booking_status):
    venue = f.venue()
    event = f.event(coordinator, "planning")
    booking = f.booking(event, venue, coordinator, booking_status)

    result = service.delete_venue(venue["id"], staff)

    released = _booking(booking["id"])
    assert (released["status"], released["released_by_venue_deletion"]) == ("cancelled", True)
    assert result["released_bookings"] == [
        {
            "booking_id": booking["id"],
            "event_id": event["id"],
            "previous_status": booking_status,
            "event_status": "planning",
        }
    ]
    [log] = (
        supabase.table("venue_booking_status_log")
        .select("*")
        .eq("booking_id", booking["id"])
        .eq("to_status", "cancelled")
        .execute()
        .data
    )
    assert (log["from_status"], log["changed_by"]) == (booking_status, staff)
    assert f'Venue "{venue["name"]}" was deleted' in log["reason"]
    assert _event_status(event["id"]) == "planning"


@pytest.mark.parametrize("event_status", FINISHED_STATUSES)
def test_ac4_bookings_of_finished_events_are_left_alone(f, staff, coordinator, event_status):
    venue = f.venue()
    event = f.event(coordinator, "planning")
    booking = f.booking(event, venue, coordinator, "confirmed")
    supabase.table("events").update({"status": event_status}).eq("id", event["id"]).execute()

    result = service.delete_venue(venue["id"], staff)

    assert result["released_bookings"] == []
    kept = _booking(booking["id"])
    assert (kept["status"], kept["released_by_venue_deletion"]) == ("confirmed", False)
    assert _event_status(event["id"]) == event_status


def test_ac4_a_coordinators_own_cancellation_is_not_marked_as_a_release(f, staff, coordinator):
    venue = f.venue()
    event = f.event(coordinator, "planning")
    booking = f.booking(event, venue, coordinator, "cancelled")

    service.delete_venue(venue["id"], staff)

    assert _booking(booking["id"])["released_by_venue_deletion"] is False


def test_ac4_other_venues_bookings_for_the_session_are_untouched(f, staff, coordinator):
    venue, other = f.venue(), f.venue()
    event = f.event(coordinator, "planning")
    lost = f.booking(event, venue, coordinator, "confirmed")
    kept = f.booking(event, other, coordinator, "pending")

    service.delete_venue(venue["id"], staff)

    assert _booking(lost["id"])["status"] == "cancelled"
    assert _booking(kept["id"])["status"] == "pending"


def test_ac4_a_confirmed_event_returns_to_planning(f, staff, coordinator):
    venue = f.venue()
    event = f.event(coordinator, "planning")
    f.booking(event, venue, coordinator, "confirmed")
    supabase.table("events").update({"status": "confirmed"}).eq("id", event["id"]).execute()

    result = service.delete_venue(venue["id"], staff)

    assert _event_status(event["id"]) == "planning"
    assert result["returned_to_planning"] == [event["id"]]
    [history] = (
        supabase.table("event_status_log")
        .select("*")
        .eq("event_id", event["id"])
        .eq("from_status", "confirmed")
        .eq("to_status", "planning")
        .execute()
        .data
    )
    assert history["changed_by"] == staff
    assert f'Venue "{venue["name"]}" was deleted' in history["reason"]


def test_ac4_a_session_under_safety_check_has_it_withdrawn_and_returns_to_planning(f, staff, coordinator):
    venue = f.venue()
    event = f.event(coordinator, "planning")
    f.booking(event, venue, coordinator, "confirmed")
    supabase.table("events").update({"status": "safety_review"}).eq("id", event["id"]).execute()
    review = (
        supabase.table("safety_reviews")
        .insert({"event_id": event["id"], "status": "pending", "submitted_by": coordinator})
        .execute()
        .data[0]
    )

    service.delete_venue(venue["id"], staff)

    assert _event_status(event["id"]) == "planning"
    withdrawn = supabase.table("safety_reviews").select("*").eq("id", review["id"]).single().execute().data
    assert (withdrawn["status"], withdrawn["reviewed_by"]) == ("changes_requested", staff)
    assert "was deleted" in withdrawn["comment"]
    # Nothing pending is left to block the coordinator resubmitting once rebooked.
    resubmitted = (
        supabase.table("safety_reviews")
        .insert({"event_id": event["id"], "status": "pending", "submitted_by": coordinator})
        .execute()
        .data
    )
    assert resubmitted


def test_ac4_the_coordinator_can_book_another_venue_afterwards(f, staff, coordinator):
    venue, replacement = f.venue(), f.venue()
    event = f.event(coordinator, "planning")
    f.booking(event, venue, coordinator, "confirmed")
    supabase.table("events").update({"status": "confirmed"}).eq("id", event["id"]).execute()

    service.delete_venue(venue["id"], staff)
    rebooked = create_booking_request(
        SimpleNamespace(**{**event, "status": "planning"}), replacement["id"], coordinator
    )

    assert rebooked["status"] == "pending"


# -- a deleted venue can't be booked -------------------------------------------


def test_a_deleted_venue_cannot_be_requested(f, staff, coordinator):
    venue = f.venue()
    event = f.event(coordinator, "planning")
    service.delete_venue(venue["id"], staff)

    with pytest.raises(ValidationError, match="has been deleted"):
        create_booking_request(SimpleNamespace(**event), venue["id"], coordinator)


def test_the_database_refuses_a_booking_on_a_deleted_venue_written_straight_to_the_table(f, staff, coordinator):
    venue = f.venue()
    event = f.event(coordinator, "planning")
    service.delete_venue(venue["id"], staff)

    with pytest.raises(APIError) as refused:
        supabase.table("venue_bookings").insert(
            {
                "event_id": event["id"],
                "venue_id": venue["id"],
                "status": "pending",
                "requested_by": coordinator,
                "setup_minutes": 0,
                "turnaround_minutes": 0,
                "booking_start": "2026-12-01T09:00:00+08:00",
                "booking_end": "2026-12-01T12:00:00+08:00",
            }
        ).execute()
    assert refused.value.code == "23514"


def test_a_pending_booking_left_on_a_deleted_venue_cannot_be_approved(f, staff, coordinator):
    # A finished event's pending booking isn't released, but it can't be
    # confirmed onto a deleted venue either.
    venue = f.venue()
    event = f.event(coordinator, "planning")
    booking = f.booking(event, venue, coordinator, "pending")
    supabase.table("events").update({"status": "cancelled"}).eq("id", event["id"]).execute()
    service.delete_venue(venue["id"], staff)

    with pytest.raises(ValidationError, match="has been deleted"):
        confirm_booking(booking["id"], SimpleNamespace(**_booking(booking["id"])), staff)
    assert _booking(booking["id"])["status"] == "pending"


# -- only the backend can delete or change a venue -----------------------------


def _signed_in_as(user_id: str):
    """A Supabase client signed in as this user: requests carry their JWT, so
    the database applies the `authenticated` role's grants and RLS -- what a
    caller bypassing Flask would get."""
    email = supabase.table("profiles").select("email").eq("id", user_id).single().execute().data["email"]
    client = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])
    client.auth.sign_in_with_password({"email": email, "password": _PASSWORD})
    return client


def test_a_signed_in_user_cannot_call_delete_venue_directly(f, staff):
    venue = f.venue()

    with pytest.raises(APIError) as refused:
        _signed_in_as(staff).rpc("delete_venue", {"p_venue_id": venue["id"], "p_deleted_by": staff}).execute()

    assert refused.value.code == "42501"  # permission denied: execute is revoked from authenticated
    assert service.get_venue(venue["id"])["deleted_at"] is None


def test_a_signed_in_user_cannot_change_a_venue_directly(f, staff):
    venue = f.venue()

    # venues has a read policy only (20260923000000_venues.sql), so RLS
    # matches no row to update or soft-delete.
    _signed_in_as(staff).table("venues").update({"capacity": 1, "deleted_at": "2026-10-23T00:00:00+00:00"}).eq(
        "id", venue["id"]
    ).execute()

    stored = service.get_venue(venue["id"])
    assert (stored["capacity"], stored["deleted_at"]) == (100, None)
