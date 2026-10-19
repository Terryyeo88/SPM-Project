"""
Route-level tests for the IS-43 change-request endpoints. Loaders and
services are monkeypatched, so this tests routing and authz wiring only;
behaviour is in test_equipment_change.py.
"""

from __future__ import annotations

from types import SimpleNamespace

import app.equipment.routes as routes_module
from app.shared.errors import ValidationError
from tests.test_equipment_accept_routes import _auth, _boom, _mock_profile


def _request(status="confirmed", event_status="planning", requested_by="user-1"):
    return SimpleNamespace(id="req-1", requested_by=requested_by, status=status, event_status=event_status, items=[])


def _change(status="pending", event_status="planning"):
    return SimpleNamespace(id="chg-1", status=status, event_status=event_status)


# -- coordinator: ask ---------------------------------------------------------


def test_the_coordinator_asks_for_a_change(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(routes_module, "load_request", lambda request_id: _request())
    calls = []

    def fake_create(request_id, item_id, quantity, requested_by):
        calls.append((request_id, item_id, quantity, requested_by))
        return {"id": "chg-1", "status": "pending", "new_quantity": quantity}

    monkeypatch.setattr(routes_module, "create_change_request", fake_create)
    body = {"item_id": "item-1", "quantity": 4}
    response = client.post("/equipment/requests/req-1/change-requests", json=body, headers=_auth(signing_key))
    assert response.status_code == 201
    assert calls == [("req-1", "item-1", 4, "user-1")]


def test_a_validation_error_is_a_400(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(routes_module, "load_request", lambda request_id: _request())

    def refuse(*args):
        raise ValidationError("The quantity is already 2 -- enter a different number.")

    monkeypatch.setattr(routes_module, "create_change_request", refuse)
    response = client.post(
        "/equipment/requests/req-1/change-requests", json={"item_id": "i", "quantity": 2}, headers=_auth(signing_key)
    )
    assert response.status_code == 400
    assert "already 2" in response.get_data(as_text=True)


def test_a_pending_request_cannot_have_a_change_asked_for_403(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(routes_module, "load_request", lambda request_id: _request(status="pending"))
    monkeypatch.setattr(routes_module, "create_change_request", _boom)
    response = client.post(
        "/equipment/requests/req-1/change-requests", json={"item_id": "i", "quantity": 3}, headers=_auth(signing_key)
    )
    assert response.status_code == 403


def test_another_coordinators_request_is_404(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(routes_module, "load_request", lambda request_id: _request(requested_by="someone-else"))
    monkeypatch.setattr(routes_module, "create_change_request", _boom)
    response = client.post(
        "/equipment/requests/req-1/change-requests", json={"item_id": "i", "quantity": 3}, headers=_auth(signing_key)
    )
    assert response.status_code == 404


def test_the_owner_can_list_the_changes_on_their_request(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(routes_module, "load_request", lambda request_id: _request())
    monkeypatch.setattr(routes_module, "list_changes_for_request", lambda request_id: [{"id": "chg-1"}])
    response = client.get("/equipment/requests/req-1/change-requests", headers=_auth(signing_key))
    assert response.status_code == 200
    assert response.get_json() == [{"id": "chg-1"}]


# -- technical support: queue, accept, reject ---------------------------------


def test_technical_staff_see_the_pending_queue_and_a_coordinator_does_not(client, signing_key, monkeypatch):
    monkeypatch.setattr(routes_module, "list_pending_changes", lambda: [{"id": "chg-1"}])
    _mock_profile(monkeypatch, ["technical_support_staff"])
    assert client.get("/equipment/change-requests", headers=_auth(signing_key)).status_code == 200
    _mock_profile(monkeypatch, ["event_coordinator"])
    assert client.get("/equipment/change-requests", headers=_auth(signing_key)).status_code == 404


def test_technical_staff_accept_a_change(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["technical_support_staff"])
    monkeypatch.setattr(routes_module, "load_change_resource", lambda change_id: _change())
    calls = []
    monkeypatch.setattr(
        routes_module, "accept_change", lambda change_id, by: calls.append((change_id, by)) or {"status": "accepted"}
    )
    response = client.post("/equipment/change-requests/chg-1/accept", headers=_auth(signing_key))
    assert response.status_code == 200
    assert calls == [("chg-1", "user-1")]


def test_an_accept_the_stock_cannot_cover_is_a_400(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["technical_support_staff"])
    monkeypatch.setattr(routes_module, "load_change_resource", lambda change_id: _change())

    def refuse(change_id, by):
        raise ValidationError("Not enough equipment for that change (projector: 5 wanted, 3 available).")

    monkeypatch.setattr(routes_module, "accept_change", refuse)
    response = client.post("/equipment/change-requests/chg-1/accept", headers=_auth(signing_key))
    assert response.status_code == 400
    assert "5 wanted, 3 available" in response.get_data(as_text=True)


def test_technical_staff_reject_a_change_with_a_reason(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["technical_support_staff"])
    monkeypatch.setattr(routes_module, "load_change_resource", lambda change_id: _change())
    calls = []
    monkeypatch.setattr(
        routes_module,
        "reject_change",
        lambda change_id, reason, by: calls.append((change_id, reason, by)) or {"status": "rejected"},
    )
    response = client.post(
        "/equipment/change-requests/chg-1/reject", json={"reason": "Not enough stock"}, headers=_auth(signing_key)
    )
    assert response.status_code == 200
    assert calls == [("chg-1", "Not enough stock", "user-1")]


def test_a_decided_change_is_403_for_accept_and_reject(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["technical_support_staff"])
    monkeypatch.setattr(routes_module, "load_change_resource", lambda change_id: _change(status="accepted"))
    monkeypatch.setattr(routes_module, "accept_change", _boom)
    monkeypatch.setattr(routes_module, "reject_change", _boom)
    assert client.post("/equipment/change-requests/chg-1/accept", headers=_auth(signing_key)).status_code == 403
    response = client.post("/equipment/change-requests/chg-1/reject", json={"reason": "x"}, headers=_auth(signing_key))
    assert response.status_code == 403


def test_accept_is_blocked_on_a_cancelled_event_but_reject_is_not(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["technical_support_staff"])
    monkeypatch.setattr(routes_module, "load_change_resource", lambda change_id: _change(event_status="cancelled"))
    monkeypatch.setattr(routes_module, "accept_change", _boom)
    monkeypatch.setattr(routes_module, "reject_change", lambda *a: {"status": "rejected"})
    assert client.post("/equipment/change-requests/chg-1/accept", headers=_auth(signing_key)).status_code == 403
    response = client.post("/equipment/change-requests/chg-1/reject", json={"reason": "x"}, headers=_auth(signing_key))
    assert response.status_code == 200


def test_a_coordinator_cannot_decide(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(routes_module, "load_change_resource", lambda change_id: _change())
    monkeypatch.setattr(routes_module, "accept_change", _boom)
    assert client.post("/equipment/change-requests/chg-1/accept", headers=_auth(signing_key)).status_code == 404


def test_unauthenticated_calls_are_401(client):
    assert client.post("/equipment/requests/req-1/change-requests", json={}).status_code == 401
    assert client.get("/equipment/change-requests").status_code == 401
    assert client.post("/equipment/change-requests/chg-1/accept").status_code == 401
