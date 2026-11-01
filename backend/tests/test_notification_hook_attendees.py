"""
Notification (Attendees) (IS-76): WHEN each attendee notification is
triggered -- registering, withdrawing, confirming and cancelling call
their hook only once their own change has succeeded, and each hook hands
its arguments, untouched, to notification_service. What the notification
says and who gets it is test_notification_attendees.py's job.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.events.routes as routes_module
import app.notifications.notification_service as notification_service
import app.registrations.registration_service as registration_service
from app.shared.errors import NotFoundError, ValidationError
from tests.test_event_lifecycle import _auth, world  # noqa: F401 -- `world` is a fixture

DETAILS = {"email": "a@example.com", "phone": "9123 4567", "notify_email": True}


# -- the hooks pass their arguments through ---------------------------------------------


def test_registration_hooks_pass_their_arguments_to_the_notification_service(monkeypatch):
    seen = []
    monkeypatch.setattr(notification_service, "registration_recorded", lambda *a: seen.append(("recorded", a)))
    monkeypatch.setattr(notification_service, "registration_withdrawn", lambda *a: seen.append(("withdrawn", a)))

    registration_service._notify_registered({"id": "r"})
    registration_service._notify_withdrawn("s1", "a1", "r2")

    assert seen == [("recorded", ({"id": "r"},)), ("withdrawn", ("s1", "a1", "r2"))]


def test_event_hooks_pass_their_arguments_to_the_notification_service(monkeypatch):
    seen = []
    monkeypatch.setattr(notification_service, "event_reconfirmed", lambda *a: seen.append(("reconfirmed", a)))
    monkeypatch.setattr(notification_service, "event_cancelled", lambda *a: seen.append(("cancelled", a)))

    routes_module._notify_attendees_reconfirmed("s1")
    routes_module._notify_attendees_cancelled("s1")

    assert seen == [("reconfirmed", ("s1",)), ("cancelled", ("s1",))]


# -- registering / withdrawing ---------------------------------------------------------


@pytest.fixture
def hooks(monkeypatch):
    seen = []
    monkeypatch.setattr(registration_service, "_notify_registered", lambda *a: seen.append(("registered", a)))
    monkeypatch.setattr(registration_service, "_notify_withdrawn", lambda *a: seen.append(("withdrawn", a)))
    return seen


@pytest.mark.parametrize("status", ["confirmed", "waitlisted"])
def test_a_successful_registration_triggers_the_hook_with_the_new_row(monkeypatch, hooks, status):
    row = {"id": "r1", "event_id": "s1", "attendee_id": "a1", "status": status}
    monkeypatch.setattr(registration_service, "_db_register", lambda *a: {"outcome": "registered", "registration": row})

    assert registration_service.register(SimpleNamespace(id="s1"), "a1", DETAILS) == row
    assert hooks == [("registered", (row,))]


@pytest.mark.parametrize("outcome", ["already_registered", "not_started", "closed", "not_open", None])
def test_a_refused_registration_triggers_nothing(monkeypatch, hooks, outcome):
    monkeypatch.setattr(registration_service, "_db_register", lambda *a: {"outcome": outcome})
    event = SimpleNamespace(id="s1", registration_start_datetime=None, registration_end_datetime=None)

    with pytest.raises((ValidationError, NotFoundError)):
        registration_service.register(event, "a1", DETAILS)
    assert hooks == []


@pytest.mark.parametrize("promoted_id", ["r2", None])
def test_a_withdrawal_triggers_the_hook_with_whoever_moved_up(monkeypatch, hooks, promoted_id):
    monkeypatch.setattr(
        registration_service,
        "_db_withdraw",
        lambda *a: {"outcome": "withdrawn", "promoted_registration_id": promoted_id},
    )

    assert registration_service.withdraw("s1", "a1") == {"withdrawn": True, "promoted": promoted_id is not None}
    assert hooks == [("withdrawn", ("s1", "a1", promoted_id))]


@pytest.mark.parametrize("outcome", ["started", "not_registered"])
def test_a_refused_withdrawal_triggers_nothing(monkeypatch, hooks, outcome):
    monkeypatch.setattr(registration_service, "_db_withdraw", lambda *a: {"outcome": outcome})

    with pytest.raises((ValidationError, NotFoundError)):
        registration_service.withdraw("s1", "a1")
    assert hooks == []


# -- confirming / cancelling (through the real routes) -------------------------------------


@pytest.fixture
def event_hooks(monkeypatch):
    seen = []
    monkeypatch.setattr(routes_module, "_notify_attendees_reconfirmed", lambda *a: seen.append(("reconfirmed", a)))
    monkeypatch.setattr(routes_module, "_notify_attendees_cancelled", lambda *a: seen.append(("cancelled", a)))
    return seen


def test_confirming_triggers_the_reconfirmed_hook(client, signing_key, world, event_hooks):  # noqa: F811
    world(["event_coordinator"], "safety_review")
    response = client.post("/events/event-1/confirm", headers=_auth(signing_key), json={})

    assert response.status_code == 200
    assert event_hooks == [("reconfirmed", ("event-1",))]


def test_a_refused_confirmation_triggers_nothing(client, signing_key, world, event_hooks):  # noqa: F811
    store = world(["event_coordinator"], "safety_review")
    store.approved = False
    response = client.post("/events/event-1/confirm", headers=_auth(signing_key), json={})

    assert response.status_code == 400
    assert event_hooks == []


@pytest.mark.parametrize("from_status", ["approved", "planning", "safety_review", "confirmed"])
def test_ac6_cancelling_triggers_only_the_cancelled_hook(client, signing_key, world, event_hooks, from_status):  # noqa: F811
    world(["event_coordinator"], from_status)
    response = client.post("/events/event-1/cancel", headers=_auth(signing_key), json={"reason": "No venue"})

    assert response.status_code == 200
    assert event_hooks == [("cancelled", ("event-1",))]


def test_a_refused_cancellation_triggers_nothing(client, signing_key, world, event_hooks):  # noqa: F811
    world(["event_coordinator"], "planning")
    response = client.post("/events/event-1/cancel", headers=_auth(signing_key), json={"reason": " "})

    assert response.status_code == 400
    assert event_hooks == []


def test_completing_tells_attendees_nothing(client, signing_key, world, event_hooks):  # noqa: F811
    world(["event_coordinator"], "confirmed")
    response = client.post("/events/event-1/complete", headers=_auth(signing_key), json={})

    assert response.status_code == 200
    assert event_hooks == []
