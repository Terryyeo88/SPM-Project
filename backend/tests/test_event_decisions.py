"""
Event Review and Approval -- the coordinator's Approve / Reject decision,
plus GET /events/coordinators (the Reassign dropdown's choices).

Unit-level like test_events_routes.py: no real Supabase. Route tests
monkeypatch the loader/service functions to test routing + authz wiring;
the service tests swap event_service's `supabase` for a small fake to
test the status update, the audit-log write and the "still under review"
guard.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.auth.context as context_module
import app.events.event_service as service_module
import app.events.routes as routes_module
from app.authz import actions
from app.authz.policy import can
from app.shared.errors import ValidationError
from tests.factories import FakeEvent, make_user


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


# -- POST /events/<id>/approve --------------------------------------------


def test_approve_route_approves_for_assigned_coordinator(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    event = FakeEvent(id="event-1", coordinator_id="user-1", status="under_review")
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: event)
    calls = []

    def fake_approve(event_id, loaded, approved_by):
        calls.append((event_id, approved_by))
        return {"id": event_id, "status": "approved"}

    monkeypatch.setattr(routes_module, "approve_event_request", fake_approve)

    response = client.post("/events/event-1/approve", headers=_auth(signing_key))

    assert response.status_code == 200
    assert response.get_json()["status"] == "approved"
    assert calls == [("event-1", "user-1")]


def test_approve_route_404_for_coordinator_not_assigned(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    event = FakeEvent(id="event-1", coordinator_id="someone-else", status="under_review")
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: event)
    called = []
    monkeypatch.setattr(routes_module, "approve_event_request", lambda *a: called.append(a))

    response = client.post("/events/event-1/approve", headers=_auth(signing_key))

    assert response.status_code == 404
    assert called == []


def test_approve_route_403_when_not_under_review(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    event = FakeEvent(id="event-1", coordinator_id="user-1", status="approved")
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: event)
    called = []
    monkeypatch.setattr(routes_module, "approve_event_request", lambda *a: called.append(a))

    response = client.post("/events/event-1/approve", headers=_auth(signing_key))

    assert response.status_code == 403
    assert called == []


def test_organiser_cannot_approve_own_event(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_organizer"])
    event = FakeEvent(id="event-1", organizer_id="user-1", status="under_review")
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: event)

    response = client.post("/events/event-1/approve", headers=_auth(signing_key))

    assert response.status_code == 404


# -- POST /events/<id>/reject ---------------------------------------------


def test_reject_route_passes_reason_to_service(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    event = FakeEvent(id="event-1", coordinator_id="user-1", status="under_review")
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: event)
    calls = []

    def fake_reject(event_id, loaded, rejected_by, reason):
        calls.append((event_id, rejected_by, reason))
        return {"id": event_id, "status": "rejected"}

    monkeypatch.setattr(routes_module, "reject_event_request", fake_reject)

    response = client.post(
        "/events/event-1/reject", headers=_auth(signing_key), json={"reason": "No suitable dates"}
    )

    assert response.status_code == 200
    assert calls == [("event-1", "user-1", "No suitable dates")]


def test_reject_route_404_for_coordinator_not_assigned(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    event = FakeEvent(id="event-1", coordinator_id="someone-else", status="under_review")
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: event)

    response = client.post("/events/event-1/reject", headers=_auth(signing_key), json={"reason": "x"})

    assert response.status_code == 404


# -- GET /events/coordinators ---------------------------------------------


def test_coordinators_route_lists_for_coordinator(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    coordinators = [{"id": "c1", "name": "Alice", "email": "a@example.com"}]
    monkeypatch.setattr(routes_module, "list_coordinators", lambda: coordinators)

    response = client.get("/events/coordinators", headers=_auth(signing_key))

    assert response.status_code == 200
    assert response.get_json() == coordinators


def test_coordinators_route_forbidden_for_organiser(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_organizer"])

    response = client.get("/events/coordinators", headers=_auth(signing_key))

    assert response.status_code == 403


def test_coordinator_list_rule_allows_only_coordinators():
    assert can(make_user(["event_coordinator"]), actions.COORDINATOR_LIST) is True
    for role in ["event_organizer", "venue_staff", "technical_support_staff", "attendee"]:
        assert can(make_user([role]), actions.COORDINATOR_LIST) is False


# -- service: approve_event_request / reject_event_request ----------------


class _FakeQuery:
    def __init__(self, db, table):
        self.db, self.table, self.filters, self.op = db, table, [], None

    def update(self, values):
        self.op = ("update", values)
        return self

    def insert(self, values):
        self.op = ("insert", values)
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def select(self, *_):
        return self

    def execute(self):
        kind, values = self.op
        if kind == "insert":
            self.db.inserts.append((self.table, values))
            return SimpleNamespace(data=[values])
        matched = [row for row in self.db.events if all(row.get(c) == v for c, v in self.filters)]
        for row in matched:
            row.update(values)
        return SimpleNamespace(data=matched)


class _FakeSupabase:
    def __init__(self, events):
        self.events, self.inserts = events, []

    def table(self, name):
        return _FakeQuery(self, name)


@pytest.fixture
def fake_db(monkeypatch):
    db = _FakeSupabase([{"id": "event-1", "status": "under_review", "coordinator_id": "coord-1"}])
    monkeypatch.setattr(service_module, "supabase", db)
    return db


def _loaded(status="under_review"):
    return SimpleNamespace(id="event-1", status=status, coordinator_id="coord-1")


def test_approve_sets_status_and_logs_who_approved(fake_db):
    result = service_module.approve_event_request("event-1", _loaded(), "coord-1")

    assert result["status"] == "approved"
    assert fake_db.inserts == [
        (
            "event_status_log",
            {
                "event_id": "event-1",
                "from_status": "under_review",
                "to_status": "approved",
                "changed_by": "coord-1",
                "reason": None,
            },
        )
    ]


def test_reject_sets_status_and_logs_trimmed_reason(fake_db):
    result = service_module.reject_event_request("event-1", _loaded(), "coord-1", "  Dates unavailable  ")

    assert result["status"] == "rejected"
    assert fake_db.inserts[0][1]["reason"] == "Dates unavailable"
    assert fake_db.inserts[0][1]["to_status"] == "rejected"


@pytest.mark.parametrize("reason", [None, "", "   ", 42])
def test_reject_requires_a_reason(fake_db, reason):
    with pytest.raises(ValidationError):
        service_module.reject_event_request("event-1", _loaded(), "coord-1", reason)
    assert fake_db.events[0]["status"] == "under_review"
    assert fake_db.inserts == []


def test_second_decision_is_refused_once_no_longer_under_review(fake_db):
    service_module.approve_event_request("event-1", _loaded(), "coord-1")

    with pytest.raises(ValidationError):
        service_module.reject_event_request("event-1", _loaded(), "coord-1", "changed my mind")
    assert fake_db.events[0]["status"] == "approved"
    assert len(fake_db.inserts) == 1
