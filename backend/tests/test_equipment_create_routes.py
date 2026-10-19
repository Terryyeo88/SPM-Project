"""
Route-level tests for the IS-17 endpoints:
  POST /events/<event_id>/equipment-requests   (app/events/routes.py)
  GET  /equipment/types                        (app/equipment/routes.py)

Unit level, like test_venue_bookings_routes.py: load_event and the service
functions are monkeypatched, so this tests routing and authz wiring only;
behaviour is in test_equipment_create_request.py.
"""

from __future__ import annotations

import app.auth.context as context_module
import app.equipment.routes as equipment_routes
import app.events.routes as events_routes
from app.shared.errors import NotFoundError, ValidationError
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


def _boom(*_a, **_k):
    raise AssertionError("should not be called")


BODY = {"items": [{"equipment_type_id": "type-prj", "quantity": 2, "technical_requirements": "HDMI"}]}


# -- POST /events/<event_id>/equipment-requests ------------------------------


def test_create_for_assigned_coordinator_returns_201(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    event = FakeEvent(id="event-1", coordinator_id="user-1", status="planning")
    monkeypatch.setattr(events_routes, "load_event", lambda event_id: event)
    calls = []

    def fake_create(loaded_event, items, requested_by):
        calls.append((loaded_event.id, items, requested_by))
        return {"id": "req-1", "status": "pending"}

    monkeypatch.setattr(events_routes, "create_equipment_request", fake_create)

    response = client.post("/events/event-1/equipment-requests", headers=_auth(signing_key), json=BODY)

    assert response.status_code == 201
    assert response.get_json() == {"id": "req-1", "status": "pending"}
    assert calls == [("event-1", BODY["items"], "user-1")]


def test_create_with_no_body_passes_none_so_the_service_rejects_it(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    event = FakeEvent(id="event-1", coordinator_id="user-1", status="planning")
    monkeypatch.setattr(events_routes, "load_event", lambda event_id: event)

    def fake_create(loaded_event, items, requested_by):
        assert items is None
        raise ValidationError("Add at least one equipment item to the request.")

    monkeypatch.setattr(events_routes, "create_equipment_request", fake_create)
    response = client.post("/events/event-1/equipment-requests", headers=_auth(signing_key))
    assert response.status_code == 400


def test_create_denied_outside_planning(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    event = FakeEvent(id="event-1", coordinator_id="user-1", status="approved")
    monkeypatch.setattr(events_routes, "load_event", lambda event_id: event)
    monkeypatch.setattr(events_routes, "create_equipment_request", _boom)
    response = client.post("/events/event-1/equipment-requests", headers=_auth(signing_key), json=BODY)
    assert response.status_code == 403


def test_create_hides_the_event_from_a_coordinator_who_is_not_assigned(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    event = FakeEvent(id="event-1", coordinator_id="someone-else", status="planning")
    monkeypatch.setattr(events_routes, "load_event", lambda event_id: event)
    monkeypatch.setattr(events_routes, "create_equipment_request", _boom)
    response = client.post("/events/event-1/equipment-requests", headers=_auth(signing_key), json=BODY)
    assert response.status_code == 404


def test_create_for_a_missing_event_is_404(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])

    def missing(event_id):
        raise NotFoundError("Event not found.")

    monkeypatch.setattr(events_routes, "load_event", missing)
    response = client.post("/events/nope/equipment-requests", headers=_auth(signing_key), json=BODY)
    assert response.status_code == 404


def test_create_denied_for_technical_staff(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["technical_support_staff"])
    event = FakeEvent(id="event-1", coordinator_id="user-1", status="planning")
    monkeypatch.setattr(events_routes, "load_event", lambda event_id: event)
    monkeypatch.setattr(events_routes, "create_equipment_request", _boom)
    response = client.post("/events/event-1/equipment-requests", headers=_auth(signing_key), json=BODY)
    assert response.status_code in (403, 404)


def test_create_rejects_unauthenticated(client):
    assert client.post("/events/event-1/equipment-requests", json=BODY).status_code == 401


# -- GET /equipment/types ----------------------------------------------------


def test_types_listed_for_coordinator_and_technical_staff(client, signing_key, monkeypatch):
    monkeypatch.setattr(equipment_routes, "list_equipment_types", lambda: [{"id": "t1", "name": "projector"}])
    for role in ("event_coordinator", "technical_support_staff"):
        _mock_profile(monkeypatch, [role])
        response = client.get("/equipment/types", headers=_auth(signing_key))
        assert response.status_code == 200
        assert response.get_json() == [{"id": "t1", "name": "projector"}]


def test_types_denied_for_other_roles(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_organizer"])
    monkeypatch.setattr(equipment_routes, "list_equipment_types", _boom)
    assert client.get("/equipment/types", headers=_auth(signing_key)).status_code == 403


def test_types_is_not_swallowed_by_the_dynamic_unit_route(client, signing_key, monkeypatch):
    """/equipment/types must hit the static route, not /equipment/<id>."""
    _mock_profile(monkeypatch, ["technical_support_staff"])
    monkeypatch.setattr(equipment_routes, "list_equipment_types", lambda: [])
    monkeypatch.setattr(equipment_routes, "get_equipment", _boom)
    assert client.get("/equipment/types", headers=_auth(signing_key)).status_code == 200
