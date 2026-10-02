"""Live Supabase integration test for event request submission."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.events.event_service import (
    create_draft_request,
    delete_draft_request,
    submit_event_request,
)
from app.extensions import supabase

pytestmark = pytest.mark.integration

_PASSWORD = "Password123!-throwaway-test-account"


def test_create_and_submit_event_request_against_supabase():
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
