"""
IS-36 (approved -> planning), IS-38 (confirmed -> completed, read-only
afterwards), IS-39 (cancel with a reason), plus the minimal confirm route
IS-38 needs to be reachable end to end.

Unit level, no database. Rule tests call can() directly. Route tests go
through the real app, the real @require and the real transition(), with
only transition()'s _db_* functions and the route's loader swapped for
in-memory fakes.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.auth.context as context_module
import app.events.routes as routes_module
import app.events.transitions as transitions
from app.authz import actions
from app.authz.policy import can
from tests.factories import FakeEvent, make_user

COORD = "coord-1"
ORG = "org-1"


def _coordinator(user_id=COORD):
    return make_user(["event_coordinator"], user_id=user_id)


def _event(status, coordinator_id=COORD):
    return FakeEvent(id="event-1", organizer_id=ORG, coordinator_id=coordinator_id, status=status)


# -- rules: who may take each step, from which status ------------------------

STEPS = [
    (actions.EVENT_START_PLANNING, "approved"),
    (actions.EVENT_CONFIRM, "planning"),
    (actions.EVENT_COMPLETE, "confirmed"),
]


@pytest.mark.parametrize("action,from_status", STEPS)
def test_assigned_coordinator_may_take_step_from_its_status(action, from_status):
    assert can(_coordinator(), action, _event(from_status))


@pytest.mark.parametrize("action,from_status", STEPS)
def test_step_refused_from_any_other_status(action, from_status):
    for status in ["draft", "submitted", "under_review", "approved", "planning",
                   "confirmed", "completed", "cancelled", "rejected"]:
        if status != from_status:
            assert not can(_coordinator(), action, _event(status)), (action, status)


@pytest.mark.parametrize("action,from_status", STEPS)
def test_unassigned_coordinator_and_organiser_cannot_take_step(action, from_status):
    assert not can(_coordinator("someone-else"), action, _event(from_status))
    assert not can(make_user(["event_organizer"], user_id=ORG), action, _event(from_status))


def test_is36_coordinator_can_set_planning_only_if_approved():
    assert can(_coordinator(), actions.EVENT_START_PLANNING, _event("approved"))
    assert not can(_coordinator(), actions.EVENT_START_PLANNING, _event("under_review"))
    assert not can(_coordinator(), actions.EVENT_START_PLANNING, _event("confirmed"))


# -- IS-38: a completed event is read-only ------------------------------------


def test_completed_event_refuses_edit_submit_cancel_and_reassign():
    """IS-38: "completed events are read-only going forward". Checked for
    everyone who could otherwise act on the event: its organiser, its
    assigned coordinator, and a user holding both roles on it."""
    completed = _event("completed")
    organiser = make_user(["event_organizer"], user_id=ORG)
    coordinator = _coordinator()
    both = make_user(["event_organizer", "event_coordinator"], user_id=ORG)
    both_event = FakeEvent(id="event-1", organizer_id=ORG, coordinator_id=ORG, status="completed")

    for user, event in [(organiser, completed), (coordinator, completed), (both, both_event)]:
        for action in (actions.EVENT_EDIT, actions.EVENT_SUBMIT, actions.EVENT_CANCEL,
                       actions.EVENT_REASSIGN_COORDINATOR, actions.EVENT_DELETE,
                       actions.EVENT_START_PLANNING, actions.EVENT_CONFIRM, actions.EVENT_COMPLETE,
                       actions.EVENT_APPROVE, actions.EVENT_REJECT):
            assert not can(user, action, event), (user.roles, action)
    # ...but it can still be viewed.
    assert can(organiser, actions.EVENT_VIEW, completed)
    assert can(coordinator, actions.EVENT_VIEW, completed)


@pytest.mark.parametrize("status", ["under_review", "approved", "planning", "confirmed", "cancelled", "rejected"])
def test_reassign_still_allowed_before_completion(status):
    """The new precondition excludes ONLY completed -- no story makes any
    other status read-only (cancelled/rejected flagged in open-questions)."""
    assert can(_coordinator(), actions.EVENT_REASSIGN_COORDINATOR, _event(status))


# -- IS-39: cancel rule ----------------------------------------------------


@pytest.mark.parametrize("status", ["approved", "planning", "confirmed"])
def test_is39_coordinator_can_cancel_after_approval(status):
    assert can(_coordinator(), actions.EVENT_CANCEL, _event(status))


@pytest.mark.parametrize("status", ["draft", "submitted", "under_review", "completed", "cancelled", "rejected"])
def test_is39_cancel_refused_before_approval_or_when_finished(status):
    assert not can(_coordinator(), actions.EVENT_CANCEL, _event(status))


# -- routes ---------------------------------------------------------------


class _Store:
    def __init__(self, status):
        self.status, self.history = status, []

    def current_status(self, event_id):
        return self.status

    def conditional_update(self, event_id, from_status, to_status):
        if self.status != from_status:
            return None
        self.status = to_status
        return {"id": event_id, "status": to_status, "organizer_id": ORG, "coordinator_id": COORD}

    def insert_history(self, event_id, from_status, to_status, actor, reason):
        self.history.append({"from_status": from_status, "to_status": to_status, "changed_by": actor,
                             "reason": reason, "changed_at": "2026-10-01T00:00:00+00:00"})

    def list_history(self, event_id):
        return list(self.history)


@pytest.fixture
def world(monkeypatch):
    """Returns setup(roles, status, user_id, loaded_status=None). loaded_status
    lets a test make @require see one status while the DB holds another
    (the race)."""

    def setup(roles, status, user_id=COORD, loaded_status=None):
        store = _Store(status)
        monkeypatch.setattr(transitions, "_db_current_status", store.current_status)
        monkeypatch.setattr(transitions, "_db_conditional_update", store.conditional_update)
        monkeypatch.setattr(transitions, "_db_insert_history", store.insert_history)
        monkeypatch.setattr(transitions, "_db_list_history", store.list_history)
        monkeypatch.setattr(
            routes_module,
            "load_event",
            lambda event_id: SimpleNamespace(
                id=event_id, organizer_id=ORG, coordinator_id=COORD, status=loaded_status or store.status
            ),
        )
        monkeypatch.setattr(
            context_module,
            "_load_profile_with_roles",
            lambda uid: ("Test User", "test@example.com", frozenset(roles)),
        )
        monkeypatch.setattr(context_module, "_get_last_active", lambda session_id: None)
        monkeypatch.setattr(context_module, "_touch_session_activity", lambda *a, **k: None)
        return store

    return setup


def _auth(signing_key, user_id=COORD):
    return {"Authorization": f"Bearer {signing_key.make_token(sub=user_id)}"}


@pytest.mark.parametrize(
    "path,from_status,to_status",
    [("start-planning", "approved", "planning"), ("confirm", "planning", "confirmed"),
     ("complete", "confirmed", "completed")],
)
def test_lifecycle_route_moves_event_and_records_actor(client, signing_key, world, path, from_status, to_status):
    store = world(["event_coordinator"], from_status)
    response = client.post(f"/events/event-1/{path}", headers=_auth(signing_key), json={})

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["status"] == to_status
    assert store.history[0]["from_status"] == from_status
    assert store.history[0]["to_status"] == to_status
    assert store.history[0]["changed_by"] == COORD


def test_is36_start_planning_refused_unless_approved(client, signing_key, world):
    store = world(["event_coordinator"], "under_review")
    response = client.post("/events/event-1/start-planning", headers=_auth(signing_key), json={})
    assert response.status_code == 403
    assert store.status == "under_review"


def test_is38_complete_refused_unless_confirmed(client, signing_key, world):
    store = world(["event_coordinator"], "planning")
    response = client.post("/events/event-1/complete", headers=_auth(signing_key), json={})
    assert response.status_code == 403
    assert store.status == "planning"


def test_is38_reassign_route_refused_on_completed_event(client, signing_key, world):
    world(["event_coordinator"], "completed")
    response = client.post(
        "/events/event-1/reassign-coordinator", headers=_auth(signing_key), json={"new_coordinator_id": "coord-2"}
    )
    assert response.status_code == 403


def test_organiser_cannot_drive_lifecycle(client, signing_key, world):
    world(["event_organizer"], "approved", user_id=ORG)
    response = client.post("/events/event-1/start-planning", headers=_auth(signing_key, ORG), json={})
    assert response.status_code == 404  # no coordinator relationship: not entitled to know


def test_is39_cancel_stores_reason_and_returns_it(client, signing_key, world):
    store = world(["event_coordinator"], "planning")
    response = client.post(
        "/events/event-1/cancel", headers=_auth(signing_key), json={"reason": "  Venue unavailable  "}
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["status"] == "cancelled"
    assert body["cancellation_reason"] == "Venue unavailable"
    assert store.history == [
        {"from_status": "planning", "to_status": "cancelled", "changed_by": COORD,
         "reason": "Venue unavailable", "changed_at": "2026-10-01T00:00:00+00:00"}
    ]


@pytest.mark.parametrize("body", [{}, {"reason": ""}, {"reason": "   "}, {"reason": 7}, None])
def test_is39_cancel_without_a_reason_is_400_and_changes_nothing(client, signing_key, world, body):
    store = world(["event_coordinator"], "approved")
    response = client.post("/events/event-1/cancel", headers=_auth(signing_key), json=body)
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "validation_error"
    assert store.status == "approved"
    assert store.history == []


def test_is39_organiser_sees_cancellation_reason_in_status_history(client, signing_key, world):
    store = world(["event_organizer"], "cancelled", user_id=ORG)
    store.history.append({"from_status": "planning", "to_status": "cancelled", "changed_by": COORD,
                          "reason": "Venue unavailable", "changed_at": "2026-10-01T00:00:00+00:00"})

    response = client.get("/events/event-1/status-history", headers=_auth(signing_key, ORG))

    assert response.status_code == 200
    assert response.get_json()[-1]["reason"] == "Venue unavailable"


def test_status_history_hidden_from_unrelated_organiser(client, signing_key, world):
    world(["event_organizer"], "cancelled", user_id="org-other")
    response = client.get("/events/event-1/status-history", headers=_auth(signing_key, "org-other"))
    assert response.status_code == 404


def test_lost_race_between_authz_and_write_is_409(client, signing_key, world):
    """@require saw `approved` (the loader's read) but by the time the write
    runs the event is `cancelled`. The conditional update matches nothing,
    so the caller gets a 409, and the concurrent cancel is not overwritten."""
    store = world(["event_coordinator"], "cancelled", loaded_status="approved")
    response = client.post("/events/event-1/start-planning", headers=_auth(signing_key), json={})

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "status_conflict"
    assert store.status == "cancelled"
    assert store.history == []
