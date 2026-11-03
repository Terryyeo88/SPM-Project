"""
IS-23 Notification (Event Organizer): WHEN each notification is triggered.
Each story step calls its hook only once its own change has succeeded, and
the hook hands its arguments, untouched, to notification_service. Who is
told what is test_notification_organizer.py's job.
"""

from __future__ import annotations

import pytest

import app.events.event_service as service_module
import app.events.routes as routes_module
import app.notifications.notification_service as notification_service
from app.events.transitions import TransitionConflictError
from app.shared.errors import ValidationError
from tests.test_event_decisions import _loaded, _loaded_session, fake_db, request_db  # noqa: F401 -- fixtures
from tests.test_event_lifecycle import _auth, world  # noqa: F401 -- `world` is a fixture
from tests.test_event_submit_transitions import _complete_event
from tests.test_event_submit_transitions import world as submit_world  # noqa: F401 -- fixture


@pytest.fixture
def news(monkeypatch):
    seen = []
    monkeypatch.setattr(notification_service, "organizer_event_news", lambda *a: seen.append(a))
    return seen


def test_the_hooks_pass_their_arguments_to_the_notification_service(news, monkeypatch):
    monkeypatch.setattr(routes_module, "current_user", lambda: type("U", (), {"id": "coord-1"})())

    service_module._notify_organizer("s1", "approved", "coord-1")
    service_module._notify_organizer("s1", "submitted")
    routes_module._notify_organizer("s1", "confirmed")

    assert news == [("s1", "approved", "coord-1"), ("s1", "submitted", None), ("s1", "confirmed", "coord-1")]


# -- AC1: the request is submitted -----------------------------------------------------------


def test_submitting_triggers_one_notification_with_the_organizer_as_the_actor(submit_world, news):  # noqa: F811
    submit_world("draft")

    service_module.submit_event_request("event-1", _complete_event("draft"))

    assert news == [("event-1", "submitted", "org-1")]


def test_a_submission_that_lost_a_race_triggers_nothing(submit_world, news):  # noqa: F811
    submit_world("approved")

    with pytest.raises(TransitionConflictError):
        service_module.submit_event_request("event-1", _complete_event("draft"))

    assert news == []


# -- AC3: the coordinator approves or rejects ------------------------------------------------


def test_approving_triggers_one_notification_for_the_whole_request(request_db, news):  # noqa: F811
    service_module.approve_event_request("s1", _loaded_session(), "coord-1")

    assert news == [("s1", "approved", "coord-1")]


def test_rejecting_triggers_one_notification_for_the_whole_request(request_db, news):  # noqa: F811
    service_module.reject_event_request("s1", _loaded_session(), "coord-1", "Venue clash")

    assert news == [("s1", "rejected", "coord-1")]


def test_a_refused_decision_triggers_nothing(fake_db, news):  # noqa: F811
    with pytest.raises(ValidationError):
        service_module.reject_event_request("event-1", _loaded(), "coord-1", "  ")
    service_module.approve_event_request("event-1", _loaded(), "coord-1")
    news.clear()

    with pytest.raises(TransitionConflictError):
        service_module.reject_event_request("event-1", _loaded(), "coord-1", "changed my mind")

    assert news == []


def test_starting_planning_is_not_news_to_the_organizer(request_db, news):  # noqa: F811
    service_module.start_planning_request("s3", _loaded_session("s3"), "coord-1")
    assert news == []


# -- AC4, AC5: a session is confirmed or cancelled (through the real routes) -----------------


@pytest.fixture
def route_news(monkeypatch):
    seen = []
    monkeypatch.setattr(routes_module, "_notify_organizer", lambda *a: seen.append(a))
    return seen


def test_confirming_a_session_triggers_the_hook(client, signing_key, world, route_news):  # noqa: F811
    world(["event_coordinator"], "safety_review")

    response = client.post("/events/event-1/confirm", headers=_auth(signing_key), json={})

    assert response.status_code == 200
    assert route_news == [("event-1", "confirmed")]


def test_a_refused_confirmation_triggers_nothing(client, signing_key, world, route_news):  # noqa: F811
    store = world(["event_coordinator"], "safety_review")
    store.approved = False

    response = client.post("/events/event-1/confirm", headers=_auth(signing_key), json={})

    assert response.status_code == 400
    assert route_news == []


def test_cancelling_a_session_triggers_the_hook(client, signing_key, world, route_news):  # noqa: F811
    world(["event_coordinator"], "planning")

    response = client.post("/events/event-1/cancel", headers=_auth(signing_key), json={"reason": "No venue"})

    assert response.status_code == 200
    assert route_news == [("event-1", "cancelled")]


def test_a_refused_cancellation_triggers_nothing(client, signing_key, world, route_news):  # noqa: F811
    world(["event_coordinator"], "completed")

    response = client.post("/events/event-1/cancel", headers=_auth(signing_key), json={"reason": "No venue"})

    assert response.status_code == 403
    assert route_news == []


def _lose_the_race(monkeypatch):
    def conflict(*args, **kwargs):
        raise TransitionConflictError("This event is no longer in that status.")

    monkeypatch.setattr(routes_module, "transition", conflict)


def test_a_confirmation_that_loses_a_race_triggers_nothing(client, signing_key, world, route_news, monkeypatch):  # noqa: F811
    world(["event_coordinator"], "safety_review")
    _lose_the_race(monkeypatch)

    response = client.post("/events/event-1/confirm", headers=_auth(signing_key), json={})

    assert response.status_code == 409
    assert route_news == []


def test_a_cancellation_that_loses_a_race_triggers_nothing(client, signing_key, world, route_news, monkeypatch):  # noqa: F811
    world(["event_coordinator"], "planning")
    _lose_the_race(monkeypatch)

    response = client.post("/events/event-1/cancel", headers=_auth(signing_key), json={"reason": "No venue"})

    assert response.status_code == 409
    assert route_news == []
