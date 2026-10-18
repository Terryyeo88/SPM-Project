"""
HTTP routes for the Operational Feasibility Check (Week 7 change #6):

  POST /events/<id>/safety-review              coordinator submits a session
  GET  /events/<id>/safety-reviews             a session's history (event.view)
  GET  /safety-reviews                         the Safety Officer's dashboard
  GET  /safety-reviews/<id>                    one review
  POST /safety-reviews/<id>/approve | reject | request-changes

Routing + authz wiring only: loaders and the safety_service functions
imported into each route module are monkeypatched. Service behaviour is
test_safety_service.py's job.
"""

from __future__ import annotations

import pytest

import app.auth.context as context_module
import app.events.routes as events_routes
import app.safety.routes as safety_routes
from app.shared.errors import NotFoundError
from tests.factories import FakeEvent, FakeSafetyReview


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


# -- POST /events/<id>/safety-review -------------------------------------------


def test_assigned_coordinator_submits_a_planning_session(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(
        events_routes, "load_event", lambda event_id: FakeEvent(coordinator_id="user-1", status="planning")
    )
    calls = []

    def submit(event, submitted_by):
        calls.append((event.id, submitted_by))
        return {"event": {"id": event.id, "status": "safety_review"}, "review": {"id": "review-1", "status": "pending"}}

    monkeypatch.setattr(events_routes, "submit_for_safety_check", submit)
    response = client.post("/events/event-1/safety-review", headers=_auth(signing_key), json={})

    assert response.status_code == 201
    assert response.get_json()["review"]["status"] == "pending"
    assert calls == [("event-1", "user-1")]


@pytest.mark.parametrize("status", ["approved", "safety_review", "confirmed"])
def test_submit_outside_planning_is_a_403(client, signing_key, monkeypatch, status):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(events_routes, "load_event", lambda event_id: FakeEvent(coordinator_id="user-1", status=status))
    called = []
    monkeypatch.setattr(events_routes, "submit_for_safety_check", lambda *a: called.append(a))

    response = client.post("/events/event-1/safety-review", headers=_auth(signing_key), json={})
    assert response.status_code == 403
    assert called == []


def test_submit_by_another_coordinator_is_a_404(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(
        events_routes, "load_event", lambda event_id: FakeEvent(coordinator_id="other", status="planning")
    )
    called = []
    monkeypatch.setattr(events_routes, "submit_for_safety_check", lambda *a: called.append(a))

    response = client.post("/events/event-1/safety-review", headers=_auth(signing_key), json={})
    assert response.status_code == 404
    assert called == []


# -- GET /events/<id>/safety-reviews --------------------------------------------


def test_coordinator_reads_the_sessions_safety_history(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(
        events_routes, "load_event", lambda event_id: FakeEvent(coordinator_id="user-1", status="planning")
    )
    monkeypatch.setattr(
        events_routes, "list_reviews_for_event", lambda event_id: [{"id": "r-1", "status": "changes_requested"}]
    )

    response = client.get("/events/event-1/safety-reviews", headers=_auth(signing_key))
    assert response.status_code == 200
    assert response.get_json() == [{"id": "r-1", "status": "changes_requested"}]


def test_safety_history_is_hidden_from_someone_who_cannot_see_the_event(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(
        events_routes, "load_event", lambda event_id: FakeEvent(coordinator_id="other", status="planning")
    )
    response = client.get("/events/event-1/safety-reviews", headers=_auth(signing_key))
    assert response.status_code == 404


# -- GET /safety-reviews ------------------------------------------------------------


def test_safety_officer_lists_reviews(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["safety_officer"])
    seen = []

    def list_reviews(user, status):
        seen.append((user.id, status))
        return [{"id": "r-1"}]

    monkeypatch.setattr(safety_routes, "list_reviews", list_reviews)
    response = client.get("/safety-reviews?status=pending", headers=_auth(signing_key))

    assert response.status_code == 200
    assert response.get_json() == [{"id": "r-1"}]
    assert seen == [("user-1", "pending")]


@pytest.mark.parametrize("role", ["event_coordinator", "venue_staff", "event_coordinator_lead"])
def test_other_roles_cannot_list_reviews(client, signing_key, monkeypatch, role):
    _mock_profile(monkeypatch, [role])
    response = client.get("/safety-reviews", headers=_auth(signing_key))
    assert response.status_code == 403


# -- GET /safety-reviews/<id> -----------------------------------------------------


def test_safety_officer_opens_a_review_with_its_details(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["safety_officer"])
    monkeypatch.setattr(safety_routes, "load_review", lambda review_id: FakeSafetyReview(id=review_id))
    monkeypatch.setattr(safety_routes, "review_detail", lambda review: {"id": review.id, "event": {"id": "event-1"}})

    response = client.get("/safety-reviews/review-1", headers=_auth(signing_key))
    assert response.status_code == 200
    assert response.get_json()["event"] == {"id": "event-1"}


def test_a_coordinator_opening_a_review_gets_a_404(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(safety_routes, "load_review", lambda review_id: FakeSafetyReview(id=review_id))
    response = client.get("/safety-reviews/review-1", headers=_auth(signing_key))
    assert response.status_code == 404


def test_an_unknown_review_is_a_404(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["safety_officer"])

    def missing(review_id):
        raise NotFoundError("Safety review not found.")

    monkeypatch.setattr(safety_routes, "load_review", missing)
    response = client.get("/safety-reviews/nope", headers=_auth(signing_key))
    assert response.status_code == 404


# -- decisions ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path,to_status",
    [("approve", "approved"), ("reject", "rejected"), ("request-changes", "changes_requested")],
)
def test_each_decision_route_passes_its_status_and_the_comment(client, signing_key, monkeypatch, path, to_status):
    _mock_profile(monkeypatch, ["safety_officer"])
    monkeypatch.setattr(safety_routes, "load_review", lambda review_id: FakeSafetyReview(id=review_id))
    calls = []

    def decide(review_id, review, status, decided_by, comment):
        calls.append((review_id, status, decided_by, comment))
        return {"id": review_id, "status": status}

    monkeypatch.setattr(safety_routes, "decide_review", decide)
    response = client.post(f"/safety-reviews/review-1/{path}", headers=_auth(signing_key), json={"comment": "ok"})

    assert response.status_code == 200
    assert response.get_json()["status"] == to_status
    assert calls == [("review-1", to_status, "user-1", "ok")]


@pytest.mark.parametrize("path", ["approve", "reject", "request-changes"])
def test_a_decided_review_cannot_be_decided_again(client, signing_key, monkeypatch, path):
    _mock_profile(monkeypatch, ["safety_officer"])
    monkeypatch.setattr(safety_routes, "load_review", lambda review_id: FakeSafetyReview(status="approved"))
    called = []
    monkeypatch.setattr(safety_routes, "decide_review", lambda *a: called.append(a))

    response = client.post(f"/safety-reviews/review-1/{path}", headers=_auth(signing_key), json={"comment": "x"})
    assert response.status_code == 403
    assert called == []


@pytest.mark.parametrize("path", ["approve", "reject", "request-changes"])
def test_a_coordinator_cannot_decide(client, signing_key, monkeypatch, path):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(safety_routes, "load_review", lambda review_id: FakeSafetyReview())
    called = []
    monkeypatch.setattr(safety_routes, "decide_review", lambda *a: called.append(a))

    response = client.post(f"/safety-reviews/review-1/{path}", headers=_auth(signing_key), json={"comment": "x"})
    assert response.status_code == 404
    assert called == []
