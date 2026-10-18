"""
Live Supabase integration tests for the Operational Feasibility Check (Week 7
change #6). Proves what the unit tests can't: the migration
(supabase/migrations/20261019000000_safety_officer.sql) applies, the
one-pending-per-session unique index refuses a second pending review, the
decision check constraint holds, and safety_service's embeds (the session,
the reviewer/submitter names through their named foreign keys, the venue on
a booking) work against real PostgREST.

Same fixture/cleanup shape as test_venue_bookings_integration.py. Skipped
automatically without a local Supabase (see conftest.py).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from postgrest.exceptions import APIError

from app.extensions import supabase
from app.safety.safety_service import (
    decide_review,
    get_review,
    is_approved,
    list_reviews,
    list_reviews_for_event,
    review_detail,
    submit_for_safety_check,
)
from app.shared.errors import ValidationError
from tests.factories import make_user

pytestmark = pytest.mark.integration

_PASSWORD = "Password123!-throwaway-test-account"


class _Fixtures:
    def __init__(self):
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
        return {"id": user_id, "name": name}

    def ready_session(self, coordinator_id: str, organizer_id: str) -> dict:
        """A planning session with one confirmed venue booking: ready to submit."""
        venue = (
            supabase.table("venues")
            .insert(
                {
                    "name": f"Safety Test Venue {uuid.uuid4()}",
                    "location": "Test Wing",
                    "capacity": 120,
                    "facilities": [],
                    "accessibility_features": ["wheelchair_access"],
                    "supported_layouts": ["theatre"],
                    "status": "available",
                }
            )
            .execute()
            .data[0]
        )
        self.venue_ids.append(venue["id"])
        day = (date.today() + timedelta(days=40)).isoformat()
        event = (
            supabase.table("events")
            .insert(
                {
                    "name": f"Safety Test Event {uuid.uuid4()}",
                    "description": "integration test event -- safe to delete",
                    "purpose": "testing",
                    "expected_attendance": 80,
                    "preferred_start_date": day,
                    "preferred_end_date": day,
                    "preferred_start_time": "09:00",
                    "preferred_end_time": "12:00",
                    "organizer_id": organizer_id,
                    "coordinator_id": coordinator_id,
                    "status": "planning",
                }
            )
            .execute()
            .data[0]
        )
        self.event_ids.append(event["id"])
        supabase.table("venue_bookings").insert(
            {
                "event_id": event["id"],
                "venue_id": venue["id"],
                "status": "confirmed",
                "requested_by": coordinator_id,
                "setup_minutes": 0,
                "turnaround_minutes": 0,
                "booking_start": f"{day}T09:00:00+08:00",
                "booking_end": f"{day}T12:00:00+08:00",
            }
        ).execute()
        return event

    def cleanup(self) -> None:
        for event_id in self.event_ids:  # cascades to safety_reviews and venue_bookings
            supabase.table("events").delete().eq("id", event_id).execute()
        for venue_id in self.venue_ids:
            supabase.table("venues").delete().eq("id", venue_id).execute()
        for user_id in self.user_ids:
            supabase.auth.admin.delete_user(user_id)


@pytest.fixture
def world():
    f = _Fixtures()
    coordinator = f.create_user("Safety Test Coordinator", "event_coordinator")
    organizer = f.create_user("Safety Test Organizer", "event_organizer")
    officer = f.create_user("Safety Test Officer", "safety_officer")
    event = f.ready_session(coordinator["id"], organizer["id"])
    yield SimpleNamespace(f=f, coordinator=coordinator, officer=officer, event=event)
    f.cleanup()


def _status(event_id: str) -> str:
    return supabase.table("events").select("status").eq("id", event_id).execute().data[0]["status"]


def test_submit_writes_a_pending_review_the_officer_sees_with_its_session(world):
    result = submit_for_safety_check(SimpleNamespace(**world.event), world.coordinator["id"])

    assert result["review"]["status"] == "pending"
    assert _status(world.event["id"]) == "safety_review"
    mine = [r for r in list_reviews(make_user(["safety_officer"])) if r["event_id"] == world.event["id"]]
    assert len(mine) == 1
    assert mine[0]["event"]["name"] == world.event["name"]
    assert mine[0]["submitted_by_name"] == "Safety Test Coordinator"


def test_the_database_allows_only_one_pending_review_per_session(world):
    submit_for_safety_check(SimpleNamespace(**world.event), world.coordinator["id"])

    with pytest.raises(APIError) as exc_info:
        supabase.table("safety_reviews").insert(
            {"event_id": world.event["id"], "status": "pending", "submitted_by": world.coordinator["id"]}
        ).execute()
    assert exc_info.value.code == "23505"

    # ...and the service turns that into a clear message, not a 500.
    with pytest.raises(ValidationError) as service_error:
        submit_for_safety_check(SimpleNamespace(**{**world.event, "status": "planning"}), world.coordinator["id"])
    assert service_error.value.message == "This session is already waiting for a safety check."


def test_a_decided_review_must_say_who_decided_and_when(world):
    with pytest.raises(APIError):
        supabase.table("safety_reviews").insert(
            {"event_id": world.event["id"], "status": "approved", "submitted_by": world.coordinator["id"]}
        ).execute()


def test_changes_requested_goes_back_to_planning_and_a_resubmission_is_a_new_review(world):
    first = submit_for_safety_check(SimpleNamespace(**world.event), world.coordinator["id"])["review"]
    decide_review(
        first["id"],
        SimpleNamespace(**get_review(first["id"])),
        "changes_requested",
        world.officer["id"],
        "Move the stage away from exit B.",
    )

    assert _status(world.event["id"]) == "planning"
    [history] = list_reviews_for_event(world.event["id"])
    assert history["status"] == "changes_requested"
    assert history["comment"] == "Move the stage away from exit B."
    assert history["reviewed_by_name"] == "Safety Test Officer"

    second = submit_for_safety_check(SimpleNamespace(**world.event), world.coordinator["id"])["review"]
    assert second["id"] != first["id"]
    assert [r["status"] for r in list_reviews_for_event(world.event["id"])] == ["pending", "changes_requested"]


def test_approval_opens_confirmation_and_the_detail_shows_the_venue(world):
    review = submit_for_safety_check(SimpleNamespace(**world.event), world.coordinator["id"])["review"]
    assert is_approved(world.event["id"]) is False

    decide_review(review["id"], SimpleNamespace(**get_review(review["id"])), "approved", world.officer["id"], None)

    assert is_approved(world.event["id"]) is True
    assert _status(world.event["id"]) == "safety_review"  # the coordinator confirms, not the officer
    detail = review_detail(SimpleNamespace(**get_review(review["id"])))
    assert detail["event"]["expected_attendance"] == 80
    [booking] = detail["venue_bookings"]
    assert booking["venues"]["capacity"] == 120
    assert detail["reviewed_by_name"] == "Safety Test Officer"
