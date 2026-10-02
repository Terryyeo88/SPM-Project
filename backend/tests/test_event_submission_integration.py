"""Live Supabase integration test for event request submission."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.events.event_service import (
    create_draft_request,
    create_event_request,
    delete_draft_request,
    list_event_requests,
    list_event_sessions,
    save_draft_request,
    submit_event_request,
)
from app.extensions import supabase
from tests.factories import make_user

pytestmark = pytest.mark.integration

_PASSWORD = "Password123!-throwaway-test-account"


@pytest.fixture
def organizer():
    """A throwaway organiser account. Every event it owns is deleted
    afterwards (its log rows go with them -- both log tables cascade on
    event delete), then the account itself."""
    email = f"event-sessions-{uuid.uuid4()}@example.com"
    user_id = supabase.auth.admin.create_user(
        {"email": email, "password": _PASSWORD, "email_confirm": True}
    ).user.id
    try:
        supabase.table("profiles").insert(
            {"id": user_id, "name": "Event Sessions Test Organizer", "email": email}
        ).execute()
        supabase.table("user_roles").insert({"user_id": user_id, "role": "event_organizer"}).execute()
        yield user_id
    finally:
        supabase.table("events").delete().eq("organizer_id", user_id).execute()
        supabase.table("user_roles").delete().eq("user_id", user_id).execute()
        supabase.table("profiles").delete().eq("id", user_id).execute()
        supabase.auth.admin.delete_user(user_id)


def _days_ahead(days: int) -> str:
    return (date.today() + timedelta(days=days)).isoformat()


def _session(days: int, **overrides) -> dict:
    session = {
        "preferred_start_date": _days_ahead(days),
        "preferred_end_date": _days_ahead(days),
        "preferred_start_time": "09:00",
        "preferred_end_time": "17:00",
        "expected_attendance": 50,
        "accessibility_needs": [],
        "room_layout": "theatre",
        "equipment": [],
        "registration_needs": False,
        "special_requests": "",
    }
    session.update(overrides)
    return session


def _rows_for(shared_event_id: str) -> list[dict]:
    return (
        supabase.table("events")
        .select("*")
        .eq("shared_event_id", shared_event_id)
        .order("preferred_start_date")
        .execute()
        .data
    )


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_submit_without_draft_creates_linked_sessions_against_supabase(organizer):
    """POST /events path: no draft is ever saved. Every session is written
    as its own events row under one server-generated shared_event_id, with
    its own requirements, and submitted."""
    registration_opens = f"{_days_ahead(1)}T01:00:00.000Z"  # 09:00 SGT
    registration_closes = f"{_days_ahead(30)}T10:00:00.000Z"  # 18:00 SGT, day before session 1

    group = create_event_request(
        organizer,
        {
            "name": f"Multi-session Conference {uuid.uuid4()}",
            "description": "Integration test for sessions.",
            "purpose": "Verify sessions persist.",
            "sessions": [
                _session(
                    31,
                    expected_attendance=200,
                    equipment=[{"item": "microphone", "quantity": 2}],
                    registration_needs=True,
                    registration_start_datetime=registration_opens,
                    registration_end_datetime=registration_closes,
                ),
                _session(
                    33,
                    expected_attendance=40,
                    room_layout="boardroom",
                    accessibility_needs=[{"item": "lift_access"}],
                ),
            ],
        },
    )

    shared_event_id = group["shared_event_id"]
    uuid.UUID(shared_event_id)
    first, second = _rows_for(shared_event_id)

    assert first["organizer_id"] == second["organizer_id"] == organizer
    assert first["name"] == second["name"]
    assert first["expected_attendance"] == 200
    assert first["equipment_needed"] == {"equipment": [{"item": "microphone", "quantity": 2}]}
    assert second["expected_attendance"] == 40
    assert second["room_layout"] == "boardroom"
    assert second["accessibility_needs"] == [{"item": "lift_access"}]

    # timestamptz stores the instant: whatever offset Postgres returns it
    # in, it's the same moment the organiser picked.
    assert _instant(first["registration_start_datetime"]) == _instant(registration_opens)
    assert _instant(first["registration_end_datetime"]) == _instant(registration_closes)
    assert second["registration_needs"] is False
    assert second["registration_start_datetime"] is None
    assert second["registration_end_datetime"] is None

    # Submitted (or under review, if a coordinator was free) -- see the note
    # in test_create_and_submit_event_request_against_supabase on why the
    # exact branch can't be assumed against a shared coordinator pool.
    for row in (first, second):
        assert row["status"] in ("submitted", "under_review")
        assert (row["coordinator_id"] is not None) == (row["status"] == "under_review")


def test_save_draft_adds_updates_and_removes_sessions_against_supabase(organizer):
    """Against a real database: saving a draft updates the sessions sent with an
    id, adds the one sent without an id, and deletes the one left out. Every
    remaining row gets the new shared name and stays a draft."""

    created = create_draft_request(
        organizer,
        {
            "name": "Draft with sessions",
            "sessions": [_session(31), _session(32), _session(33)],
        },
    )
    keep, drop, update = created["sessions"]
    event = SimpleNamespace(**keep)

    saved = save_draft_request(
        keep["id"],
        event,
        {
            "name": "Draft with sessions (renamed)",
            "sessions": [
                {"id": keep["id"], "expected_attendance": 60},
                {"id": update["id"], "room_layout": "banquet"},
                _session(40, room_layout="networking"),
            ],
        },
    )

    rows = _rows_for(created["shared_event_id"])
    ids = {row["id"] for row in rows}
    assert drop["id"] not in ids
    assert {keep["id"], update["id"]} <= ids
    assert len(rows) == 3
    assert {row["name"] for row in rows} == {"Draft with sessions (renamed)"}
    assert {row["status"] for row in rows} == {"draft"}
    by_id = {row["id"]: row for row in rows}
    assert by_id[keep["id"]]["expected_attendance"] == 60
    assert by_id[update["id"]]["room_layout"] == "banquet"
    assert [s["id"] for s in saved["sessions"]] == [row["id"] for row in rows]


def test_submitted_request_appears_in_assigned_coordinators_queue_against_supabase(organizer):
    """IS-31 AC: "Submitted requests become visible in the assigned
    Coordinator's queue". End to end against a real database: after the
    organiser submits, the coordinator the system assigned finds the
    request in their own event list (the queue their dashboard is built
    from), as under_review."""
    group = create_event_request(
        organizer,
        {
            "name": f"Queue visibility {uuid.uuid4()}",
            "description": "Checks the coordinator queue after submission.",
            "purpose": "IS-31 acceptance criterion.",
            "sessions": [_session(35)],
        },
    )
    (row,) = _rows_for(group["shared_event_id"])
    if row["coordinator_id"] is None:
        pytest.skip(
            "No coordinator was free to auto-assign in this database, so there is no "
            "assigned coordinator's queue to check (seed coordinators with `supabase db reset`)."
        )

    coordinator = make_user(["event_coordinator"], user_id=row["coordinator_id"])
    queue = {event["id"]: event for event in list_event_requests(coordinator)}
    assert row["id"] in queue
    assert queue[row["id"]]["status"] == "under_review"
    assert row["id"] in {event["id"] for event in list_event_requests(coordinator, "under_review")}


def test_create_and_submit_event_request_against_supabase():
    """Against a real database: a two-session draft is created with one
    shared_event_id. Submitting from the first session moves both sessions
    to submitted/under_review, and the submitted session's status and
    coordinator_id agree with what's stored."""

    email = f"event-submission-{uuid.uuid4()}@example.com"
    created_user = supabase.auth.admin.create_user(
        {"email": email, "password": _PASSWORD, "email_confirm": True}
    )
    user_id = created_user.user.id
    shared_event_id = None

    try:
        supabase.table("profiles").insert(
            {"id": user_id, "name": "Event Submission Test Organizer", "email": email}
        ).execute()
        supabase.table("user_roles").insert(
            {"user_id": user_id, "role": "event_organizer"}
        ).execute()

        common = {
            "preferred_start_time": None,
            "preferred_end_time": None,
            "accessibility_needs": [{"item": "wheelchair_access", "quantity": 2}],
            "special_requests": "Database integration test.",
        }
        created = create_draft_request(
            user_id,
            {
                "name": f"Community Conference {uuid.uuid4()}",
                "description": "A real database submission test.",
                "purpose": "Verify event request persistence.",
                "sessions": [
                    {
                        **common,
                        "preferred_start_date": "2026-11-10",
                        "preferred_end_date": "2026-11-10",
                        "expected_attendance": 100,
                        "accessibility_needs": [
                            {"item": "wheelchair_access", "quantity": 2},
                            {
                                "item": "removable_seats",
                                "quantity": 4,
                                "notes": "front row, near main entrance",
                            },
                        ],
                        "room_layout": "theatre",
                        "equipment": [
                            {"item": "microphone", "quantity": 3},
                            {"item": "projector", "quantity": 1},
                        ],
                        "registration_needs": True,
                        "registration_start_datetime": "2026-11-01T09:00:00+08:00",
                        "registration_end_datetime": "2026-11-09T18:00:00+08:00",
                    },
                    {
                        **common,
                        "preferred_start_date": "2026-11-12",
                        "preferred_end_date": "2026-11-12",
                        "expected_attendance": 30,
                        "room_layout": "boardroom",
                        "equipment": [],
                        "registration_needs": False,
                    },
                ],
            },
        )
        shared_event_id = created["shared_event_id"]
        assert len(created["sessions"]) == 2
        assert all(s["status"] == "draft" for s in created["sessions"])
        assert all(s["shared_event_id"] == shared_event_id for s in created["sessions"])
        event_id = created["sessions"][0]["id"]

        stored_draft = (
            supabase.table("events")
            .select("*")
            .eq("id", event_id)
            .single()
            .execute()
            .data
        )
        submitted_event = submit_event_request(event_id, SimpleNamespace(**stored_draft))

        # Submitting from one session submits every draft session of the
        # same request.
        sibling_statuses = (
            supabase.table("events")
            .select("status")
            .eq("shared_event_id", shared_event_id)
            .execute()
            .data
        )
        assert len(sibling_statuses) == 2
        assert all(row["status"] in ("submitted", "under_review") for row in sibling_statuses)

        # The organiser still sees every session of their own request.
        group = list_event_sessions(
            SimpleNamespace(**stored_draft), make_user(["event_organizer"], user_id=user_id)
        )
        assert sorted(s["id"] for s in group["sessions"]) == sorted(s["id"] for s in created["sessions"])

        # Per submit_event_request's own docstring, submission lands on
        # "under_review" if a coordinator could be auto-assigned, or stays
        # "submitted" if none was available. Which branch fires here depends
        # on this shared project's live coordinator pool -- see
        # test_coordinator_assignment_integration.py's own note on why tests
        # here can't assume a specific coordinator state (seeded coordinators
        # like Alice/Brandon/Chloe are real candidates this test doesn't
        # control). So this asserts the real invariant (status and
        # coordinator_id must agree) instead of guessing which branch wins.
        assert submitted_event["status"] in ("submitted", "under_review")
        if submitted_event["status"] == "under_review":
            assert submitted_event["coordinator_id"] is not None
        else:
            assert submitted_event["coordinator_id"] is None

        stored_submitted = (
            supabase.table("events")
            .select("status, coordinator_id")
            .eq("id", event_id)
            .single()
            .execute()
            .data
        )
        assert stored_submitted["status"] == submitted_event["status"]
        assert stored_submitted["coordinator_id"] == submitted_event["coordinator_id"]
    finally:
        if shared_event_id:
            supabase.table("events").delete().eq("shared_event_id", shared_event_id).execute()
        supabase.table("user_roles").delete().eq("user_id", user_id).execute()
        supabase.table("profiles").delete().eq("id", user_id).execute()
        supabase.auth.admin.delete_user(user_id)


def test_create_partial_draft_against_supabase():
    """Verify incomplete draft data is stored without submission validation."""
    email = f"event-draft-{uuid.uuid4()}@example.com"
    created_user = supabase.auth.admin.create_user(
        {"email": email, "password": _PASSWORD, "email_confirm": True}
    )
    user_id = created_user.user.id
    event_id = None

    try:
        supabase.table("profiles").insert(
            {"id": user_id, "name": "Event Draft Test Organizer", "email": email}
        ).execute()
        supabase.table("user_roles").insert(
            {"user_id": user_id, "role": "event_organizer"}
        ).execute()

        created_event = create_draft_request(
            user_id,
            {"description": "Only the description has been drafted so far.", "sessions": [{}]},
        )
        event_id = created_event["sessions"][0]["id"]

        stored_event = (
            supabase.table("events")
            .select("name, description, status, organizer_id")
            .eq("id", event_id)
            .single()
            .execute()
            .data
        )
        assert stored_event["name"] == "Untitled event request"
        assert stored_event["description"] == "Only the description has been drafted so far."
        assert stored_event["status"] == "draft"
        assert stored_event["organizer_id"] == user_id
    finally:
        if event_id:
            supabase.table("events").delete().eq("id", event_id).execute()
        supabase.table("user_roles").delete().eq("user_id", user_id).execute()
        supabase.table("profiles").delete().eq("id", user_id).execute()
        supabase.auth.admin.delete_user(user_id)


def test_delete_draft_removes_it_from_supabase():
    """Verify a draft event request is actually removed from the events
    table, not just marked deleted."""
    email = f"event-delete-{uuid.uuid4()}@example.com"
    created_user = supabase.auth.admin.create_user(
        {"email": email, "password": _PASSWORD, "email_confirm": True}
    )
    user_id = created_user.user.id
    event_id = None

    try:
        supabase.table("profiles").insert(
            {"id": user_id, "name": "Event Delete Test Organizer", "email": email}
        ).execute()
        supabase.table("user_roles").insert(
            {"user_id": user_id, "role": "event_organizer"}
        ).execute()

        created_event = create_draft_request(
            user_id,
            {"description": "A draft that will be deleted.", "sessions": [{}, {"expected_attendance": 20}]},
        )
        event_id = created_event["sessions"][0]["id"]

        # Deleting from one session removes the whole request.
        delete_draft_request(event_id, SimpleNamespace(**created_event["sessions"][0]))

        remaining = (
            supabase.table("events")
            .select("id")
            .eq("shared_event_id", created_event["shared_event_id"])
            .execute()
            .data
        )
        assert remaining == []
        event_id = None  # already gone -- nothing left for the finally block to clean up
    finally:
        if event_id:
            supabase.table("events").delete().eq("id", event_id).execute()
        supabase.table("user_roles").delete().eq("user_id", user_id).execute()
        supabase.table("profiles").delete().eq("id", user_id).execute()
        supabase.auth.admin.delete_user(user_id)
