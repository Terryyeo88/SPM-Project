"""Live Supabase integration tests for IS-21 change requests -- only what the
unit tests (FakeSupabase) structurally cannot prove:

1. The real event_change_requests and event_logs tables accept what the
   services write (column names, jsonb, the enum, FKs to events/profiles),
   an approval really writes the event, and the change lands in the audit
   trail.
2. The partial unique index allows only one PENDING change per session,
   even when the app's own check is bypassed (the race it exists for).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from postgrest.exceptions import APIError

from app.events.change_request_service import approve_change_request, request_event_change
from app.extensions import supabase

pytestmark = pytest.mark.integration

_PASSWORD = "Password123!-throwaway-test-account"


def _create_user(roles: list[str]) -> str:
    email = f"change-request-test-{uuid.uuid4()}@example.com"
    created = supabase.auth.admin.create_user({"email": email, "password": _PASSWORD, "email_confirm": True})
    user_id = created.user.id
    supabase.table("profiles").insert({"id": user_id, "name": "Change Request Test User", "email": email}).execute()
    for role in roles:
        supabase.table("user_roles").insert({"user_id": user_id, "role": role}).execute()
    return user_id


def _delete_user(user_id: str) -> None:
    supabase.table("user_roles").delete().eq("user_id", user_id).execute()
    supabase.table("profiles").delete().eq("id", user_id).execute()
    supabase.auth.admin.delete_user(user_id)


@pytest.fixture
def confirmed_event():
    organizer = _create_user(["event_organizer"])
    coordinator = _create_user(["event_coordinator"])
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
