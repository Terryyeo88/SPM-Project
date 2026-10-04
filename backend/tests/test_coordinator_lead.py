"""
Event Coordinator Lead (Week 7 customer change #5) -- authz rules, routes
and the Lead's event list. Unit level: no database.

"Newly submitted event requests should no longer be assigned directly to
an Event Coordinator. Instead, they first enter an unassigned queue that
can be viewed by the Event Coordinator Lead. The Lead can review basic
event information, assign a suitable Event Coordinator, and reassign
events where necessary. Event Coordinators should only be able to manage
events assigned to them, while the Event Coordinator Lead should be able
to view all coordinator assignments and active events under their
supervision."

Not covered because not built: "Relevant users should be notified when
assignments or reassignments occur" (see docs/open-questions.md).
"""

from __future__ import annotations

import pytest

import app.auth.context as context_module
import app.events.event_service as service_module
import app.events.routes as routes_module
from app.authz import actions
from app.authz.policy import can
from app.authz.rules import Decision, rule_event_assign_coordinator, rule_event_view
from app.events.coordinator_service import NoCoordinatorAvailableError
from tests.factories import FakeEvent, make_user
from tests.fake_supabase import FakeSupabase

LEAD = make_user(["event_coordinator_lead"], user_id="lead-1")
COORDINATOR = make_user(["event_coordinator"], user_id="coord-1")
ORGANISER = make_user(["event_organizer"], user_id="org-1")


def _event(status="submitted", coordinator_id=None, organizer_id="org-1"):
    return FakeEvent(id="event-1", organizer_id=organizer_id, coordinator_id=coordinator_id, status=status)


# -- view / list ---------------------------------------------------------------


@pytest.mark.parametrize(
    "status", ["submitted", "under_review", "approved", "planning", "confirmed", "completed", "cancelled", "rejected"]
)
def test_lead_can_view_every_submitted_event_whoever_it_is_assigned_to(status):
    assert can(LEAD, actions.EVENT_VIEW, _event(status=status, coordinator_id="coord-9"))


def test_lead_cannot_see_someone_elses_draft():
    """A draft hasn't been submitted to anyone yet -- 404, like any other outsider."""
    assert rule_event_view(LEAD, _event(status="draft")) is Decision.DENY_NOT_FOUND


def test_lead_may_list_events_and_coordinators():
    assert can(LEAD, actions.EVENT_LIST)
    assert can(LEAD, actions.COORDINATOR_LIST)


def test_coordinator_still_only_sees_their_own_events():
    assert can(COORDINATOR, actions.EVENT_VIEW, _event(status="under_review", coordinator_id="coord-1"))
    assert not can(COORDINATOR, actions.EVENT_VIEW, _event(status="under_review", coordinator_id="coord-9"))
    assert not can(COORDINATOR, actions.EVENT_VIEW, _event(status="submitted"))


def test_lead_list_is_every_non_draft_event_plus_their_own_drafts(monkeypatch):
    fake = FakeSupabase([
        {"id": "queue", "status": "submitted", "organizer_id": "org-1", "coordinator_id": None,
         "created_at": "2026-10-03"},
        {"id": "assigned", "status": "planning", "organizer_id": "org-2", "coordinator_id": "coord-1",
         "created_at": "2026-10-02"},
        {"id": "someone-elses-draft", "status": "draft", "organizer_id": "org-1", "coordinator_id": None,
         "created_at": "2026-10-04"},
        {"id": "own-draft", "status": "draft", "organizer_id": "lead-1", "coordinator_id": None,
         "created_at": "2026-10-01"},
    ])
    monkeypatch.setattr(service_module, "supabase", fake)

    rows = service_module.list_event_requests(LEAD)

    assert [row["id"] for row in rows] == ["queue", "assigned", "own-draft"]
    assert [row["id"] for row in service_module.list_event_requests(LEAD, "submitted")] == ["queue"]


# -- assign ----------------------------------------------------------------------


def test_lead_may_assign_a_request_in_the_unassigned_queue():
    assert rule_event_assign_coordinator(LEAD, _event()) is Decision.ALLOW


@pytest.mark.parametrize(
    "event",
    [
        _event(status="submitted", coordinator_id="coord-1"),  # already assigned: reassign instead
        _event(status="under_review", coordinator_id="coord-1"),
        _event(status="rejected", coordinator_id="coord-1"),
    ],
)
def test_lead_cannot_assign_once_a_request_has_left_the_queue(event):
    assert rule_event_assign_coordinator(LEAD, event) is Decision.DENY_FORBIDDEN


def test_nobody_but_the_lead_may_assign():
    # The organiser can see their own request, so 403; a coordinator with no
    # relationship to it gets 404.
    assert rule_event_assign_coordinator(ORGANISER, _event()) is Decision.DENY_FORBIDDEN
    assert rule_event_assign_coordinator(COORDINATOR, _event()) is Decision.DENY_NOT_FOUND


# -- reassign --------------------------------------------------------------------


def test_lead_may_reassign_any_assigned_event_but_not_once_completed():
    assert can(LEAD, actions.EVENT_REASSIGN_COORDINATOR, _event(status="planning", coordinator_id="coord-9"))
    assert not can(LEAD, actions.EVENT_REASSIGN_COORDINATOR, _event(status="completed", coordinator_id="coord-9"))


def test_lead_cannot_reassign_an_unassigned_request():
    """Nobody to take it from -- that's an assign, not a reassign."""
    assert not can(LEAD, actions.EVENT_REASSIGN_COORDINATOR, _event(status="submitted"))


def test_assigned_coordinator_can_still_reassign_their_own_event():
    assert can(COORDINATOR, actions.EVENT_REASSIGN_COORDINATOR, _event(status="planning", coordinator_id="coord-1"))


# -- routes ----------------------------------------------------------------------


def _as(monkeypatch, signing_key, roles, user_id):
    monkeypatch.setattr(
        context_module, "_load_profile_with_roles",
        lambda _user_id: ("Test User", "test@example.com", frozenset(roles)),
    )
    monkeypatch.setattr(context_module, "_get_last_active", lambda session_id: None)
    monkeypatch.setattr(context_module, "_touch_session_activity", lambda *a, **k: None)
    return {"Authorization": f"Bearer {signing_key.make_token(sub=user_id)}"}


def test_assign_route_assigns_the_leads_choice(client, signing_key, monkeypatch):
    headers = _as(monkeypatch, signing_key, ["event_coordinator_lead"], "lead-1")
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: _event())
    calls = []

    def fake_assign(event_id, actor=None, coordinator_id=None):
        calls.append((event_id, actor, coordinator_id))
        return {"id": coordinator_id, "name": "Alice", "email": "a@example.com"}

    monkeypatch.setattr(routes_module, "assign_initial_coordinator", fake_assign)

    response = client.post("/events/event-1/assign-coordinator", headers=headers, json={"coordinator_id": "coord-1"})

    assert response.status_code == 200
    assert response.get_json()["coordinator"]["id"] == "coord-1"
    assert calls == [("event-1", "lead-1", "coord-1")]


def test_assign_route_requires_a_coordinator(client, signing_key, monkeypatch):
    headers = _as(monkeypatch, signing_key, ["event_coordinator_lead"], "lead-1")
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: _event())

    response = client.post("/events/event-1/assign-coordinator", headers=headers, json={})

    assert response.status_code == 400


def test_assign_route_turns_a_busy_coordinator_into_a_400(client, signing_key, monkeypatch):
    headers = _as(monkeypatch, signing_key, ["event_coordinator_lead"], "lead-1")
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: _event())

    def busy(*args, **kwargs):
        raise NoCoordinatorAvailableError("Alice is already occupied on 2026-11-10.")

    monkeypatch.setattr(routes_module, "assign_initial_coordinator", busy)

    response = client.post("/events/event-1/assign-coordinator", headers=headers, json={"coordinator_id": "coord-1"})

    assert response.status_code == 400
    assert "already occupied" in response.get_json()["error"]["message"]


def test_assign_route_is_forbidden_to_the_organiser(client, signing_key, monkeypatch):
    headers = _as(monkeypatch, signing_key, ["event_organizer"], "org-1")
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: _event())
    called = []
    monkeypatch.setattr(routes_module, "assign_initial_coordinator", lambda *a, **k: called.append(a))

    response = client.post("/events/event-1/assign-coordinator", headers=headers, json={"coordinator_id": "coord-1"})

    assert response.status_code == 403
    assert called == []


def test_reassign_route_lets_the_lead_override_the_current_coordinator_check(client, signing_key, monkeypatch):
    """The Lead isn't the current coordinator, so the service's "only the
    current coordinator" check is skipped for them (requested_by=None)."""
    headers = _as(monkeypatch, signing_key, ["event_coordinator_lead"], "lead-1")
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: _event("planning", coordinator_id="coord-1"))
    calls = []

    def fake_reassign(**kwargs):
        calls.append(kwargs)
        return {"id": "coord-2", "name": "Brandon", "email": "b@example.com"}

    monkeypatch.setattr(routes_module, "reassign_coordinator", fake_reassign)

    response = client.post(
        "/events/event-1/reassign-coordinator", headers=headers, json={"new_coordinator_id": "coord-2"}
    )

    assert response.status_code == 200
    assert calls[0]["requested_by"] is None
    assert calls[0]["new_coordinator_id"] == "coord-2"
