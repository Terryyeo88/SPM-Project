"""
Route-level tests for POST /equipment/requests/<id>/accept (IS-19). The
loader and the service are monkeypatched, so this tests routing and authz
wiring only; behaviour is in test_equipment_accept.py.
"""

from __future__ import annotations

from types import SimpleNamespace

import app.auth.context as context_module
import app.equipment.routes as routes_module
from app.shared.errors import ValidationError


def _mock_profile(monkeypatch, roles):
    monkeypatch.setattr(
        context_module,
        "_load_profile_with_roles",
        lambda user_id: ("Test User", "test@example.com", frozenset(roles)),
    )
    monkeypatch.setattr(context_module, "_get_last_active", lambda session_id: None)
    monkeypatch.setattr(context_module, "_touch_session_activity", lambda *a, **k: None)


def _auth(signing_key):
    return {"Authorization": f"Bearer {signing_key.make_token(sub='user-1')}"}


def _resource(status="pending", event_status="planning"):
    return SimpleNamespace(id="req-1", requested_by="coord-1", status=status, event_status=event_status, items=[])


def _boom(*_a, **_k):
    raise AssertionError("should not be called")


def test_technical_staff_accept_returns_the_confirmed_request(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["technical_support_staff"])
    monkeypatch.setattr(routes_module, "load_request", lambda request_id: _resource())
    calls = []

    def fake_accept(request_id):
        calls.append(request_id)
        return {"id": request_id, "status": "confirmed", "allocated": []}

    monkeypatch.setattr(routes_module, "accept_request", fake_accept)
    response = client.post("/equipment/requests/req-1/accept", headers=_auth(signing_key))
    assert response.status_code == 200
    assert response.get_json()["status"] == "confirmed"
    assert calls == ["req-1"]


def test_a_service_refusal_is_a_400_with_its_message(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["technical_support_staff"])
    monkeypatch.setattr(routes_module, "load_request", lambda request_id: _resource())

    def refuse(request_id):
        raise ValidationError(
            "There is not enough equipment available for this request (projector: 2 requested, 1 available)."
        )

    monkeypatch.setattr(routes_module, "accept_request", refuse)
    response = client.post("/equipment/requests/req-1/accept", headers=_auth(signing_key))
    assert response.status_code == 400
    assert "projector: 2 requested, 1 available" in response.get_data(as_text=True)


def test_an_already_confirmed_request_is_403(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["technical_support_staff"])
    monkeypatch.setattr(routes_module, "load_request", lambda request_id: _resource(status="confirmed"))
    monkeypatch.setattr(routes_module, "accept_request", _boom)
    assert client.post("/equipment/requests/req-1/accept", headers=_auth(signing_key)).status_code == 403


def test_a_cancelled_events_request_is_403(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["technical_support_staff"])
    monkeypatch.setattr(routes_module, "load_request", lambda request_id: _resource(event_status="cancelled"))
    monkeypatch.setattr(routes_module, "accept_request", _boom)
    assert client.post("/equipment/requests/req-1/accept", headers=_auth(signing_key)).status_code == 403


def test_a_coordinator_cannot_accept(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(routes_module, "load_request", lambda request_id: _resource())
    monkeypatch.setattr(routes_module, "accept_request", _boom)
    assert client.post("/equipment/requests/req-1/accept", headers=_auth(signing_key)).status_code == 404


def test_accept_rejects_unauthenticated(client):
    assert client.post("/equipment/requests/req-1/accept").status_code == 401
