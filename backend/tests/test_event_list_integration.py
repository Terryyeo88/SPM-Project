"""Live Supabase integration test for list_event_requests (View Event
Requests, Sprint 1) -- specifically the per-row scoping rule_event_list's
own docstring warns about: passing the role-only authz check does NOT
mean "every event", the CALLER must filter by organizer_id/coordinator_id
itself. This is exactly the function that filtering lives in, so it's
worth proving against a real query, not just trusting the Python."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.events.event_service import list_event_requests
from app.extensions import supabase

pytestmark = pytest.mark.integration

_PASSWORD = "Password123!-throwaway-test-account"


def _create_user(email: str, roles: list[str]) -> str:
    created = supabase.auth.admin.create_user({"email": email, "password": _PASSWORD, "email_confirm": True})
    user_id = created.user.id
    supabase.table("profiles").insert({"id": user_id, "name": "List Test User", "email": email}).execute()
    for role in roles:
        supabase.table("user_roles").insert({"user_id": user_id, "role": role}).execute()
    return user_id


def _delete_user(user_id: str) -> None:
    supabase.table("user_roles").delete().eq("user_id", user_id).execute()
    supabase.table("profiles").delete().eq("id", user_id).execute()
    supabase.auth.admin.delete_user(user_id)


def _insert_event(**overrides) -> dict:
    payload = {
        "name": f"List Test Event {uuid.uuid4()}",
        "description": "Integration test event.",
        "purpose": "Testing.",
        "status": "draft",
    }
    payload.update(overrides)
    return supabase.table("events").insert(payload).execute().data[0]


def test_organizer_sees_only_their_own_events():
    org_a = _create_user(f"list-org-a-{uuid.uuid4()}@example.com", ["event_organizer"])
    org_b = _create_user(f"list-org-b-{uuid.uuid4()}@example.com", ["event_organizer"])
    event_ids = []
    try:
        mine = _insert_event(organizer_id=org_a)
        not_mine = _insert_event(organizer_id=org_b)
        event_ids = [mine["id"], not_mine["id"]]

        user = SimpleNamespace(id=org_a, roles=frozenset(["event_organizer"]))
        results = list_event_requests(user)
        result_ids = {e["id"] for e in results}

        assert mine["id"] in result_ids
        assert not_mine["id"] not in result_ids
    finally:
        for event_id in event_ids:
            supabase.table("events").delete().eq("id", event_id).execute()
        _delete_user(org_a)
        _delete_user(org_b)


def test_coordinator_sees_only_events_assigned_to_them():
    organizer = _create_user(f"list-org-c-{uuid.uuid4()}@example.com", ["event_organizer"])
    coord_a = _create_user(f"list-coord-a-{uuid.uuid4()}@example.com", ["event_coordinator"])
    coord_b = _create_user(f"list-coord-b-{uuid.uuid4()}@example.com", ["event_coordinator"])
    event_ids = []
    try:
        assigned = _insert_event(organizer_id=organizer, coordinator_id=coord_a, status="under_review")
        other = _insert_event(organizer_id=organizer, coordinator_id=coord_b, status="under_review")
        event_ids = [assigned["id"], other["id"]]

        user = SimpleNamespace(id=coord_a, roles=frozenset(["event_coordinator"]))
        results = list_event_requests(user)
        result_ids = {e["id"] for e in results}

        assert assigned["id"] in result_ids
        assert other["id"] not in result_ids
    finally:
        for event_id in event_ids:
            supabase.table("events").delete().eq("id", event_id).execute()
        _delete_user(organizer)
        _delete_user(coord_a)
        _delete_user(coord_b)


def test_status_filter_narrows_results():
    organizer = _create_user(f"list-org-d-{uuid.uuid4()}@example.com", ["event_organizer"])
    event_ids = []
    try:
        draft = _insert_event(organizer_id=organizer, status="draft")
        submitted = _insert_event(organizer_id=organizer, status="submitted")
        event_ids = [draft["id"], submitted["id"]]

        user = SimpleNamespace(id=organizer, roles=frozenset(["event_organizer"]))
        results = list_event_requests(user, status="submitted")
        result_ids = {e["id"] for e in results}

        assert submitted["id"] in result_ids
        assert draft["id"] not in result_ids
    finally:
        for event_id in event_ids:
            supabase.table("events").delete().eq("id", event_id).execute()
        _delete_user(organizer)


def test_multi_role_user_sees_union_of_both():
    """A user holding both event_organizer and event_coordinator sees
    events they organize OR are assigned to coordinate -- structural
    multi-role union, same stance app.authz.rules takes throughout."""
    other_organizer = _create_user(f"list-org-e-{uuid.uuid4()}@example.com", ["event_organizer"])
    dual_user = _create_user(
        f"list-dual-{uuid.uuid4()}@example.com", ["event_organizer", "event_coordinator"]
    )
    event_ids = []
    try:
        organized_by_dual = _insert_event(organizer_id=dual_user, status="draft")
        coordinated_by_dual = _insert_event(
            organizer_id=other_organizer, coordinator_id=dual_user, status="under_review"
        )
        unrelated = _insert_event(organizer_id=other_organizer, status="draft")
        event_ids = [organized_by_dual["id"], coordinated_by_dual["id"], unrelated["id"]]

        user = SimpleNamespace(id=dual_user, roles=frozenset(["event_organizer", "event_coordinator"]))
        results = list_event_requests(user)
        result_ids = {e["id"] for e in results}

        assert organized_by_dual["id"] in result_ids
        assert coordinated_by_dual["id"] in result_ids
        assert unrelated["id"] not in result_ids
    finally:
        for event_id in event_ids:
            supabase.table("events").delete().eq("id", event_id).execute()
        _delete_user(other_organizer)
        _delete_user(dual_user)
