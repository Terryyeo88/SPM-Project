"""
Route-level tests for /equipment/* (app/equipment/routes.py). Unit level,
same style as test_venue_calendar_routes.py: the service functions and the
loader are monkeypatched so this file tests routing/authz/query-param
wiring only.
"""

from __future__ import annotations

from types import SimpleNamespace

import app.auth.context as context_module
import app.equipment.routes as routes_module
from app.shared.errors import NotFoundError


def _mock_profile(monkeypatch, roles):
    monkeypatch.setattr(
        context_module,
        "_load_profile_with_roles",
        lambda user_id: ("Test User", "test@example.com", frozenset(roles)),
    )
    monkeypatch.setattr(context_module, "_get_last_active", lambda session_id: None)
    monkeypatch.setattr(context_module, "_touch_session_activity", lambda *a, **k: None)


def _get(client, signing_key, path):
    token = signing_key.make_token(sub="user-1")
    return client.get(path, headers={"Authorization": f"Bearer {token}"})


def _request_resource(requested_by="someone-else"):
    return SimpleNamespace(id="req-1", requested_by=requested_by, status="pending", items=[])


def _boom(*_a, **_k):
    raise AssertionError("should not be called")


# -- GET /equipment ----------------------------------------------------------


def test_list_equipment_for_technical_staff_passes_filters(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["technical_support_staff"])
    seen = {}

    def fake(type_name, status):
        seen["args"] = (type_name, status)
        return [{"id": "u1", "asset_tag": "PRJ-001"}]

    monkeypatch.setattr(routes_module, "list_equipment", fake)
    response = _get(client, signing_key, "/equipment?type=projector&status=available")
    assert response.status_code == 200
    assert response.get_json() == [{"id": "u1", "asset_tag": "PRJ-001"}]
    assert seen["args"] == ("projector", "available")


def test_list_equipment_denied_for_coordinator(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(routes_module, "list_equipment", _boom)
    assert _get(client, signing_key, "/equipment").status_code == 403


def test_list_equipment_rejects_unauthenticated(client):
    assert client.get("/equipment").status_code == 401


# -- GET /equipment/<id> -----------------------------------------------------


def test_get_equipment_for_technical_staff(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["technical_support_staff"])
    monkeypatch.setattr(routes_module, "get_equipment", lambda equipment_id: {"id": equipment_id, "occupancy": []})
    response = _get(client, signing_key, "/equipment/u1")
    assert response.status_code == 200
    assert response.get_json()["id"] == "u1"


def test_get_equipment_denied_for_venue_staff(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["venue_staff"])
    monkeypatch.setattr(routes_module, "get_equipment", _boom)
    assert _get(client, signing_key, "/equipment/u1").status_code == 403


def test_get_equipment_missing_is_404(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["technical_support_staff"])

    def missing(equipment_id):
        raise NotFoundError("Equipment not found.")

    monkeypatch.setattr(routes_module, "get_equipment", missing)
    assert _get(client, signing_key, "/equipment/nope").status_code == 404


def test_requests_path_is_not_swallowed_by_the_dynamic_id_route(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["technical_support_staff"])
    monkeypatch.setattr(routes_module, "list_requests", lambda user, status: [{"id": "req-1"}])
    monkeypatch.setattr(routes_module, "get_equipment", _boom)
    response = _get(client, signing_key, "/equipment/requests")
    assert response.status_code == 200
    assert response.get_json() == [{"id": "req-1"}]


# -- GET /equipment/requests -------------------------------------------------


def test_list_requests_allowed_for_coordinator_and_passes_status(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    seen = {}

    def fake(user, status):
        seen["status"] = status
        return []

    monkeypatch.setattr(routes_module, "list_requests", fake)
    assert _get(client, signing_key, "/equipment/requests?status=pending").status_code == 200
    assert seen["status"] == "pending"


def test_list_requests_denied_for_attendee(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["attendee"])
    monkeypatch.setattr(routes_module, "list_requests", _boom)
    assert _get(client, signing_key, "/equipment/requests").status_code == 403


# -- GET /equipment/requests/<id> --------------------------------------------


def test_get_request_for_technical_staff(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["technical_support_staff"])
    monkeypatch.setattr(routes_module, "load_request", lambda request_id: _request_resource())
    response = _get(client, signing_key, "/equipment/requests/req-1")
    assert response.status_code == 200
    assert response.get_json()["id"] == "req-1"


def test_get_request_for_its_own_coordinator(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(routes_module, "load_request", lambda request_id: _request_resource(requested_by="user-1"))
    assert _get(client, signing_key, "/equipment/requests/req-1").status_code == 200


def test_get_request_for_another_coordinator_is_404(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(routes_module, "load_request", lambda request_id: _request_resource(requested_by="other"))
    assert _get(client, signing_key, "/equipment/requests/req-1").status_code == 404


def test_get_request_missing_is_404(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["technical_support_staff"])

    def missing(request_id):
        raise NotFoundError("Equipment request not found.")

    monkeypatch.setattr(routes_module, "load_request", missing)
    assert _get(client, signing_key, "/equipment/requests/nope").status_code == 404


# -- GET /equipment/requests/<id>/availability -------------------------------


def test_availability_for_technical_staff(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["technical_support_staff"])
    monkeypatch.setattr(routes_module, "load_request", lambda request_id: _request_resource())
    monkeypatch.setattr(
        routes_module, "check_availability", lambda request_id: {"items": [], "all_sufficient": True}
    )
    response = _get(client, signing_key, "/equipment/requests/req-1/availability")
    assert response.status_code == 200
    assert response.get_json()["all_sufficient"] is True


def test_availability_denied_for_requesting_coordinator(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(routes_module, "load_request", lambda request_id: _request_resource(requested_by="user-1"))
    monkeypatch.setattr(routes_module, "check_availability", _boom)
    assert _get(client, signing_key, "/equipment/requests/req-1/availability").status_code == 404


def test_availability_rejects_unauthenticated(client):
    assert client.get("/equipment/requests/req-1/availability").status_code == 401
