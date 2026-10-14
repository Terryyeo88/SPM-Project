"""
Route tests for GET /events/<event_id>/equipment-requests
(app/events/routes.py) -- View Reserved Equipment (Justin, Sprint 3).

Unit level, same style as test_venue_bookings_routes.py: load_event and
the service function are monkeypatched, so this checks routing + authz
wiring only. The grouping/sorting is covered in test_equipment_service.py.
"""

from __future__ import annotations

import app.auth.context as context_module
import app.events.routes as events_routes
from tests.factories import FakeEvent


def _mock_profile(monkeypatch, roles):
    monkeypatch.setattr(
        context_module,
        "_load_profile_with_roles",
        lambda user_id: ("Test User", "test@example.com", frozenset(roles)),
    )
    monkeypatch.setattr(context_module, "_get_last_active", lambda session_id: None)
    monkeypatch.setattr(context_module, "_touch_session_activity", lambda *a, **k: None)


def _auth(signing_key, user_id="user-1"):
    return {"Authorization": f"Bearer {signing_key.make_token(sub=user_id)}"}


# -- GET /events/<event_id>/equipment-requests (View Reserved Equipment) -----


def test_event_equipment_requests_for_assigned_coordinator(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    event = FakeEvent(id="event-1", coordinator_id="user-1", status="planning")
    monkeypatch.setattr(events_routes, "load_event", lambda event_id: event)
    seen = []

    def fake_list(event_id):
        seen.append(event_id)
        return [{"id": "req-1", "status": "confirmed", "allocated": []}]

    monkeypatch.setattr(events_routes, "list_equipment_requests_for_event", fake_list)

    response = client.get("/events/event-1/equipment-requests", headers=_auth(signing_key))

    assert response.status_code == 200
    assert response.get_json()[0]["id"] == "req-1"
    assert seen == ["event-1"]


def test_event_equipment_requests_404_for_coordinator_not_assigned(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    event = FakeEvent(id="event-1", coordinator_id="someone-else", status="planning")
    monkeypatch.setattr(events_routes, "load_event", lambda event_id: event)
    called = []
    monkeypatch.setattr(events_routes, "list_equipment_requests_for_event", lambda *a: called.append(a))

    response = client.get("/events/event-1/equipment-requests", headers=_auth(signing_key))

    assert response.status_code == 404
    assert called == []
