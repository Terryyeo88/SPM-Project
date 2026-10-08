"""Live Supabase integration tests for IS-21 change requests -- only what the
unit tests (FakeSupabase) structurally cannot prove:

1. The real event_change_requests and event_logs tables accept what the
   services write (column names, jsonb, the enum, FKs to events/profiles),
   an approval really writes the event, and the change lands in the audit
   trail.
2. The partial unique index allows only one PENDING change per session,
   even when the app's own check is bypassed (the race it exists for).
3. The two JOINS the code relies on -- which the unit tests' fake database
   ignores entirely -- work against the real schema: event_logs ->
   profiles(name) for the Change History, and venue_bookings ->
   venues(...) for the impact warning.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from postgrest.exceptions import APIError

from app.events.change_request_service import approve_change_request, list_change_requests, request_event_change
from app.events.event_log import list_event_logs
from app.extensions import supabase
from tests.factories import make_user

pytestmark = pytest.mark.integration

_PASSWORD = "Password123!-throwaway-test-account"


def _create_user(roles: list[str], name: str = "Change Request Test User") -> str:
    email = f"change-request-test-{uuid.uuid4()}@example.com"
    created = supabase.auth.admin.create_user({"email": email, "password": _PASSWORD, "email_confirm": True})
    user_id = created.user.id
    supabase.table("profiles").insert({"id": user_id, "name": name, "email": email}).execute()
    for role in roles:
        supabase.table("user_roles").insert({"user_id": user_id, "role": role}).execute()
    return user_id


def _delete_user(user_id: str) -> None:
    supabase.table("user_roles").delete().eq("user_id", user_id).execute()
    supabase.table("profiles").delete().eq("id", user_id).execute()
    supabase.auth.admin.delete_user(user_id)


@pytest.fixture
def confirmed_event():
    organizer = _create_user(["event_organizer"], name="Test Organiser")
    coordinator = _create_user(["event_coordinator"], name="Test Coordinator")
    day = (date.today() + timedelta(days=30)).isoformat()
    event = (
        supabase.table("events")
        .insert(
            {
                "name": f"Change Request Test Event {uuid.uuid4()}",
                "description": "Integration test event.",
                "purpose": "Testing.",
                "organizer_id": organizer,
                "coordinator_id": coordinator,
                "status": "confirmed",
                "shared_event_id": str(uuid.uuid4()),
                "preferred_start_date": day,
                "preferred_end_date": day,
                "expected_attendance": 50,
                "room_layout": "theatre",
                "registration_needs": False,
                "equipment_needed": {"equipment": []},
            }
        )
        .execute()
        .data[0]
    )
    try:
        yield SimpleNamespace(**event), organizer, coordinator
    finally:
        # event_logs first: it has no FK to events (only shared_event_id), and it
        # references the profiles. event_change_requests cascades from
        # events, but its requested_by/reviewed_by FKs to profiles do not.
        supabase.table("event_logs").delete().eq("shared_event_id", event["shared_event_id"]).execute()
        supabase.table("events").delete().eq("id", event["id"]).execute()
        _delete_user(organizer)
        _delete_user(coordinator)


def test_change_request_round_trips_and_approval_writes_the_event(confirmed_event):
    """Against a real database: a request is saved with its before/after
    values; approving it updates the event (still confirmed), and the event
    log gets two entries -- the organiser's request and the coordinator's
    applied change -- with exactly the live table's columns."""
    event, organizer, coordinator = confirmed_event

    change = request_event_change(event, organizer, {"changes": {"expected_attendance": 75}, "reason": "More RSVPs."})
    assert change["shared_event_id"] == event.shared_event_id
    assert change["requested_changes"] == {"expected_attendance": 75}
    assert change["previous_values"] == {"expected_attendance": 50}
    assert change["status"] == "pending"

    result = approve_change_request(event, change["event_change_req_id"], coordinator)

    assert result["change_request"]["status"] == "approved"
    stored = supabase.table("events").select("expected_attendance, status").eq("id", event.id).execute().data[0]
    assert stored == {"expected_attendance": 75, "status": "confirmed"}

    entries = supabase.table("event_logs").select("*").eq("shared_event_id", event.shared_event_id).execute().data
    # The organiser's request, then the coordinator's applied change.
    [requested] = [e for e in entries if e["changed_by"] == organizer]
    assert requested["changes"] == {"expected_attendance": {"from": 50, "to": 75}}
    [entry] = [e for e in entries if e["changed_by"] == coordinator]
    assert entry["event_log_id"]
    assert entry["changes"] == {"expected_attendance": {"from": 50, "to": 75}}
    assert entry["changed_by"] == coordinator
    assert entry["changed_at"]
    assert set(entry) == {"event_log_id", "shared_event_id", "changes", "changed_by", "changed_at"}
    assert result["change_request"]["reviewed_at"]


def test_database_allows_only_one_pending_change_per_session(confirmed_event):
    """The DATABASE itself enforces "at most one pending change request per
    session" -- not just the app.

    request_event_change checks for a pending request before saving, but two
    requests sent at the same moment (a double click, two tabs) can both pass
    that check before either saves. The unique index
    uq_event_change_requests_one_pending_per_event is what stops the second.

    So this test writes straight to the table, skipping the app's check:
      1. a first pending request saves;
      2. a second pending one for the same session is refused by Postgres
         (error 23505, unique violation);
      3. once the first is decided (rejected), a new pending one saves --
         the index only counts pending rows.
    Needs a real database (a fake can't enforce an index), so it runs only
    against a local Supabase."""
    event, organizer, _ = confirmed_event
    row = {
        "shared_event_id": event.shared_event_id,
        "event_id": event.id,
        "requested_by": organizer,
        "requested_changes": {"room_layout": "banquet"},
        "previous_values": {"room_layout": "theatre"},
    }
    supabase.table("event_change_requests").insert(row).execute()

    with pytest.raises(APIError) as exc_info:
        supabase.table("event_change_requests").insert(row).execute()
    assert exc_info.value.code == "23505"  # unique_violation

    # A decided change doesn't count against the index.
    supabase.table("event_change_requests").update({"status": "rejected"}).eq("event_id", event.id).execute()
    supabase.table("event_change_requests").insert(row).execute()


def test_change_history_reads_who_made_each_entry_through_the_profiles_join(confirmed_event):
    """The Change History shows WHO made each entry by joining event_logs ->
    profiles(name) through changed_by. The unit tests' fake database ignores
    joins, so only a real database proves this one works.

    The organiser requests a change and the coordinator approves it; the
    history must come back newest first, with each person's real name and
    the right label: "changed" for the coordinator, "requested" for the
    organiser."""
    event, organizer, coordinator = confirmed_event
    change = request_event_change(event, organizer, {"changes": {"expected_attendance": 75}})
    approve_change_request(event, change["event_change_req_id"], coordinator)

    history = list_event_logs(event)

    assert [(entry["profiles"]["name"], entry["kind"]) for entry in history] == [
        ("Test Coordinator", "changed"),
        ("Test Organiser", "requested"),
    ]


def test_impact_warning_reads_the_booked_venue_through_the_venues_join(confirmed_event):
    """The impact warning checks a change against the booked venue by
    joining venue_bookings -> venues(name, capacity, supported_layouts,
    accessibility_features). The unit tests hand the venue in already
    joined, so only a real database proves the join itself works.

    The session has a booking at a 60-seat, theatre-only venue. The organiser
    asks for 75 attendees in a banquet layout; listing the request must flag
    both against that real venue, named in the warning."""
    event, organizer, coordinator = confirmed_event
    venue = (
        supabase.table("venues")
        .insert(
            {
                "name": f"Change Request Test Venue {uuid.uuid4()}",
                "location": "Test Wing",
                "capacity": 60,
                "facilities": [],
                "accessibility_features": [],
                "supported_layouts": ["theatre"],
                "status": "available",
            }
        )
        .execute()
        .data[0]
    )
    booking = (
        supabase.table("venue_bookings")
        .insert(
            {
                "event_id": event.id,
                "venue_id": venue["id"],
                "status": "pending",  # pending still counts as an arrangement
                "requested_by": coordinator,
                "setup_minutes": 0,
                "turnaround_minutes": 0,
                "booking_start": f"{event.preferred_start_date}T00:00:00+08:00",
                "booking_end": f"{event.preferred_start_date}T23:59:00+08:00",
            }
        )
        .execute()
        .data[0]
    )
    try:
        request_event_change(event, organizer, {"changes": {"expected_attendance": 75, "room_layout": "banquet"}})

        [listed] = list_change_requests(event, make_user(["event_coordinator"], user_id=coordinator))

        [venue_impact] = [impact for impact in listed["impact"] if impact["area"] == "venue"]
        assert venue["name"] in venue_impact["title"]
        assert venue_impact["booking_id"] == booking["id"]
        assert venue_impact["issues"] == [
            "75 expected attendees exceeds the venue's capacity of 60.",
            "The venue doesn't support a banquet layout.",
        ]
    finally:
        # The booking first: it references the venue (the event's own
        # cleanup in the fixture runs after this, too late for the venue).
        supabase.table("venue_bookings").delete().eq("id", booking["id"]).execute()
        supabase.table("venues").delete().eq("id", venue["id"]).execute()
