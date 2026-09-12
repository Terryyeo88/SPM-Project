"""
Tests for POST /events/<event_id>/reassign-coordinator (app/events/routes.py).

Unit-level, like test_me_route.py / test_authz_decorators.py: no real
Supabase, no network. `load_event` and `reassign_coordinator` (the
service function, imported into this route module's namespace) are
monkeypatched here so this file tests routing/authz wiring only -- the
actual reassignment business logic already has its own coverage in
tests/test_coordinator_assignment_integration.py.
"""

from __future__ import annotations

import app.auth.context as context_module
import app.events.routes as routes_module
from app.events.coordinator_service import NoCoordinatorAvailableError
from tests.factories import FakeEvent


def _mock_profile(monkeypatch, roles):
    monkeypatch.setattr(
        context_module,
        "_load_profile_with_roles",
        lambda user_id: ("Test User", "test@example.com", frozenset(roles)),
    )
    monkeypatch.setattr(context_module, "_get_last_active", lambda session_id: None)
    monkeypatch.setattr(context_module, "_touch_session_activity", lambda *a, **k: None)


def test_reassign_route_succeeds_for_assigned_coordinator(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    event = FakeEvent(id="event-1", coordinator_id="user-1")
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: event)

    calls = []

    def fake_reassign(**kwargs):
        calls.append(kwargs)
        return {"id": "new-coord", "name": "New Coordinator", "email": "new@example.com"}

    monkeypatch.setattr(routes_module, "reassign_coordinator", fake_reassign)

    token = signing_key.make_token(sub="user-1")
    response = client.post(
        "/events/event-1/reassign-coordinator",
        headers={"Authorization": f"Bearer {token}"},
        json={"new_coordinator_id": "new-coord", "reason": "going on leave"},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "coordinator": {"id": "new-coord", "name": "New Coordinator", "email": "new@example.com"}
    }
    assert calls == [
        {
            "event_id": "event-1",
            "new_coordinator_id": "new-coord",
            "requested_by": "user-1",
            "reason": "going on leave",
        }
    ]


def test_reassign_route_denies_coordinator_not_assigned_to_this_event(client, signing_key, monkeypatch):
    """Someone holding the event_coordinator role, but not the one
    assigned to THIS event, must be denied -- and denied with 404, since
    per rule_event_reassign_coordinator they have no relationship to it
    at all."""
    _mock_profile(monkeypatch, ["event_coordinator"])
    event = FakeEvent(id="event-1", coordinator_id="someone-else")
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: event)

    reassign_called = []
    monkeypatch.setattr(
        routes_module, "reassign_coordinator", lambda **kwargs: reassign_called.append(kwargs)
    )

    token = signing_key.make_token(sub="user-1")
    response = client.post(
        "/events/event-1/reassign-coordinator",
        headers={"Authorization": f"Bearer {token}"},
        json={"new_coordinator_id": "new-coord"},
    )

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "not_found"
    assert reassign_called == []  # authz must block this before the service ever runs


def test_reassign_route_requires_new_coordinator_id(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    event = FakeEvent(id="event-1", coordinator_id="user-1")
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: event)

    token = signing_key.make_token(sub="user-1")
    response = client.post(
        "/events/event-1/reassign-coordinator",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "validation_error"


def test_reassign_route_translates_no_coordinator_available_to_400(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    event = FakeEvent(id="event-1", coordinator_id="user-1")
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: event)

    def fake_reassign(**kwargs):
        raise NoCoordinatorAvailableError("Everyone is busy that day.")

    monkeypatch.setattr(routes_module, "reassign_coordinator", fake_reassign)

    token = signing_key.make_token(sub="user-1")
    response = client.post(
        "/events/event-1/reassign-coordinator",
        headers={"Authorization": f"Bearer {token}"},
        json={"new_coordinator_id": "new-coord"},
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "validation_error"


def test_reassign_route_rejects_unauthenticated(client):
    response = client.post("/events/event-1/reassign-coordinator", json={"new_coordinator_id": "x"})
    assert response.status_code == 401
