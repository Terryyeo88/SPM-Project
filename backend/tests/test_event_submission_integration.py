"""Live Supabase integration test for event request submission."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.events.event_service import (
    create_draft_request,
    create_event_request,
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
    event_id = None

    try:
        supabase.table("profiles").insert(
            {"id": user_id, "name": "Event Submission Test Organizer", "email": email}
        ).execute()
        supabase.table("user_roles").insert(
            {"user_id": user_id, "role": "event_organizer"}
        ).execute()

        created_event = create_event_request(
            user_id,
            {
                "name": f"Community Conference {uuid.uuid4()}",
                "description": "A real database submission test.",
                "purpose": "Verify event request persistence.",
                "preferred_start_date": "2026-11-10",
                "preferred_end_date": "2026-11-10",
                "preferred_start_time": None,
                "preferred_end_time": None,
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
                "special_requests": "Database integration test.",
            },
        )
        event_id = created_event["id"]
        assert created_event["status"] == "draft"

        stored_draft = (
            supabase.table("events")
            .select("*")
            .eq("id", event_id)
            .single()
            .execute()
            .data
        )
        submitted_event = submit_event_request(event_id, SimpleNamespace(**stored_draft))

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
        if event_id:
            supabase.table("events").delete().eq("id", event_id).execute()
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
            {"description": "Only the description has been drafted so far."},
        )
        event_id = created_event["id"]

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
            {"description": "A draft that will be deleted."},
        )
        event_id = created_event["id"]

        delete_draft_request(event_id, SimpleNamespace(**created_event))

        remaining = (
            supabase.table("events")
            .select("id")
            .eq("id", event_id)
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
