"""
Route-level tests for POST /equipment/requests/<id>/cancel. Loader and
service are monkeypatched; behaviour is in test_equipment_cancel.py.
"""

from __future__ import annotations

from types import SimpleNamespace

import app.equipment.routes as routes_module
from tests.test_equipment_accept_routes import _auth, _boom, _mock_profile


def _request(status="confirmed", event_status="planning", requested_by="user-1"):
    return SimpleNamespace(id="req-1", requested_by=requested_by, status=status, event_status=event_status, items=[])


def test_the_owner_cancels_their_request(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(routes_module, "load_request", lambda request_id: _request())
    calls = []

    def fake_cancel(request_id, by):
        calls.append((request_id, by))
        return {"status": "cancelled"}

    monkeypatch.setattr(routes_module, "cancel_request", fake_cancel)
    response = client.post("/equipment/requests/req-1/cancel", headers=_auth(signing_key))
    assert response.status_code == 200
    assert response.get_json()["status"] == "cancelled"
    assert calls == [("req-1", "user-1")]


def test_a_pending_request_can_be_cancelled_too(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(routes_module, "load_request", lambda request_id: _request(status="pending"))
    monkeypatch.setattr(routes_module, "cancel_request", lambda *a: {"status": "cancelled"})
    assert client.post("/equipment/requests/req-1/cancel", headers=_auth(signing_key)).status_code == 200


def test_a_rejected_request_is_403(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(routes_module, "load_request", lambda request_id: _request(status="rejected"))
    monkeypatch.setattr(routes_module, "cancel_request", _boom)
    assert client.post("/equipment/requests/req-1/cancel", headers=_auth(signing_key)).status_code == 403


def test_a_cancelled_event_is_403(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(routes_module, "load_request", lambda request_id: _request(event_status="cancelled"))
    monkeypatch.setattr(routes_module, "cancel_request", _boom)
    assert client.post("/equipment/requests/req-1/cancel", headers=_auth(signing_key)).status_code == 403


def test_someone_elses_request_is_404(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(routes_module, "load_request", lambda request_id: _request(requested_by="other"))
    monkeypatch.setattr(routes_module, "cancel_request", _boom)
    assert client.post("/equipment/requests/req-1/cancel", headers=_auth(signing_key)).status_code == 404


def test_technical_staff_cannot_cancel(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["technical_support_staff"])
    monkeypatch.setattr(routes_module, "load_request", lambda request_id: _request())
    monkeypatch.setattr(routes_module, "cancel_request", _boom)
    assert client.post("/equipment/requests/req-1/cancel", headers=_auth(signing_key)).status_code == 404


def test_unauthenticated_is_401(client):
    assert client.post("/equipment/requests/req-1/cancel").status_code == 401
