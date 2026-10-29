"""
Route-level tests for POST /equipment/requests/<id>/reject (IS-41). Loader and
service are monkeypatched; behaviour is in test_equipment_reject.py.
"""

from __future__ import annotations

import app.equipment.routes as routes_module
from app.shared.errors import ValidationError
from tests.test_equipment_accept_routes import _auth, _boom, _mock_profile, _resource


def test_technical_staff_reject_passes_the_reason_and_the_caller(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["technical_support_staff"])
    monkeypatch.setattr(routes_module, "load_request", lambda request_id: _resource())
    calls = []

    def fake_reject(request_id, reason, decided_by):
        calls.append((request_id, reason, decided_by))
        return {"id": request_id, "status": "rejected", "rejection_reason": reason}

    monkeypatch.setattr(routes_module, "reject_request", fake_reject)
    response = client.post(
        "/equipment/requests/req-1/reject", json={"reason": "Not enough stock"}, headers=_auth(signing_key)
    )
    assert response.status_code == 200
    assert response.get_json()["status"] == "rejected"
    assert calls == [("req-1", "Not enough stock", "user-1")]


def test_a_missing_reason_is_a_400(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["technical_support_staff"])
    monkeypatch.setattr(routes_module, "load_request", lambda request_id: _resource())

    def refuse(request_id, reason, decided_by):
        assert reason is None
        raise ValidationError("A reason is required to reject an equipment request.")

    monkeypatch.setattr(routes_module, "reject_request", refuse)
    response = client.post("/equipment/requests/req-1/reject", headers=_auth(signing_key))
    assert response.status_code == 400
    assert "reason is required" in response.get_data(as_text=True)


def test_an_already_decided_request_is_403(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["technical_support_staff"])
    monkeypatch.setattr(routes_module, "load_request", lambda request_id: _resource(status="confirmed"))
    monkeypatch.setattr(routes_module, "reject_request", _boom)
    response = client.post("/equipment/requests/req-1/reject", json={"reason": "x"}, headers=_auth(signing_key))
    assert response.status_code == 403


def test_a_cancelled_events_pending_request_can_still_be_rejected(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["technical_support_staff"])
    monkeypatch.setattr(routes_module, "load_request", lambda request_id: _resource(event_status="cancelled"))
    monkeypatch.setattr(routes_module, "reject_request", lambda *a: {"status": "rejected"})
    response = client.post("/equipment/requests/req-1/reject", json={"reason": "x"}, headers=_auth(signing_key))
    assert response.status_code == 200


def test_a_coordinator_cannot_reject(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(routes_module, "load_request", lambda request_id: _resource())
    monkeypatch.setattr(routes_module, "reject_request", _boom)
    response = client.post("/equipment/requests/req-1/reject", json={"reason": "x"}, headers=_auth(signing_key))
    assert response.status_code == 404


def test_reject_rejects_unauthenticated(client):
    assert client.post("/equipment/requests/req-1/reject", json={"reason": "x"}).status_code == 401
