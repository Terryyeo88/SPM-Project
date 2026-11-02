"""
IS-26 Receive Technical Support Notifications: WHEN each notification is
triggered. Each story's own code calls its hook only once its own change
has succeeded, and the hook hands its arguments, untouched, to
notification_service. Who is told what is
test_notification_technical_support.py's job; the editing hooks (update and
approve a session change) are covered next to their own tests in
test_event_update.py and test_event_change_requests.py.
"""

from __future__ import annotations

import pytest

import app.equipment.change_service as change_service
import app.equipment.equipment_service as equipment_service
import app.events.event_update as event_update
import app.events.routes as routes_module
import app.notifications.notification_service as notification_service
from app.shared.errors import ValidationError
from tests import test_equipment_cancel, test_equipment_change, test_equipment_create_request
from tests.test_equipment_create_request import EVENT, _line
from tests.test_equipment_create_request import db as create_db  # noqa: F401 -- fixture
from tests.test_event_lifecycle import _auth, world  # noqa: F401 -- `world` is a fixture


@pytest.fixture
def news(monkeypatch):
    seen = []
    monkeypatch.setattr(
        notification_service, "technical_support_request_news", lambda *a: seen.append(("request", a))
    )
    monkeypatch.setattr(
        notification_service, "technical_support_event_news", lambda *a, **k: seen.append(("event", a, k))
    )
    return seen


# -- the hooks pass their arguments through -------------------------------------------------


def test_the_equipment_hook_passes_its_arguments_to_the_notification_service(news):
    equipment_service._notify_technical_support("req-1", "submitted", "coord-1")
    equipment_service._notify_technical_support("req-1", "cancelled")

    assert news == [("request", ("req-1", "submitted", "coord-1")), ("request", ("req-1", "cancelled", None))]


def test_the_event_update_hook_passes_the_changed_field_names(news):
    event_update.notify_technical_support_of_change("s1", {"preferred_start_date": "x", "name": "y"}, "coord-1")

    assert news == [("event", ("s1", "changed", {"preferred_start_date", "name"}, "coord-1"), {})]


def test_the_cancel_route_hook_passes_the_event_and_the_actor(news, monkeypatch):
    monkeypatch.setattr(routes_module, "current_user", lambda: type("U", (), {"id": "coord-1"})())

    routes_module._notify_technical_support_cancelled("s1")

    assert news == [("event", ("s1", "cancelled"), {"actor_id": "coord-1"})]


# -- AC1: submitting a request ---------------------------------------------------------------


def test_submitting_a_request_triggers_the_hook_with_the_new_request(create_db, monkeypatch, news):  # noqa: F811
    hooks = []
    monkeypatch.setattr(equipment_service, "_notify_technical_support", lambda *a: hooks.append(a))

    result = equipment_service.create_request(EVENT, [_line()], "coord-1")

    assert hooks == [(result["id"], "submitted", "coord-1")]


def test_a_refused_request_triggers_nothing(create_db, monkeypatch):  # noqa: F811
    hooks = []
    monkeypatch.setattr(equipment_service, "_notify_technical_support", lambda *a: hooks.append(a))

    with pytest.raises(ValidationError):
        equipment_service.create_request(EVENT, [_line(quantity=0)], "coord-1")

    assert hooks == []


def test_a_request_whose_lines_failed_to_save_triggers_nothing(monkeypatch):
    hooks = []
    fake = test_equipment_create_request._DB(fail_items=True)
    monkeypatch.setattr(equipment_service, "supabase", fake)
    monkeypatch.setattr(equipment_service, "_notify_technical_support", lambda *a: hooks.append(a))

    with pytest.raises(RuntimeError):
        equipment_service.create_request(EVENT, [_line()], "coord-1")

    assert hooks == []


# -- AC2: asking for a quantity change ------------------------------------------------------


def test_asking_for_a_quantity_change_triggers_the_hook(monkeypatch):
    world_ = test_equipment_change._World(monkeypatch, old=2, new=3)
    world_.db.tables["equipment_change_requests"] = []
    hooks = []
    monkeypatch.setattr(change_service, "_notify_technical_support", lambda *a: hooks.append(a))
    monkeypatch.setattr(change_service, "_get_change_row", lambda change_id: test_equipment_change._change_row(2, 4))

    change_service.create_change_request("req-1", "item-1", 4, "coord-1")

    assert hooks == [("req-1", "change requested", "coord-1")]


def test_a_refused_quantity_change_triggers_nothing(monkeypatch):
    test_equipment_change._World(monkeypatch, old=2, new=3)
    hooks = []
    monkeypatch.setattr(change_service, "_notify_technical_support", lambda *a: hooks.append(a))

    with pytest.raises(ValidationError):
        change_service.create_change_request("req-1", "item-1", 2, "coord-1")

    assert hooks == []


# -- AC2: withdrawing a booking (IS-66) -----------------------------------------------------


def test_withdrawing_a_request_triggers_the_hook(monkeypatch):
    test_equipment_cancel._world(monkeypatch)
    hooks = []
    monkeypatch.setattr(equipment_service, "_notify_technical_support", lambda *a: hooks.append(a))

    equipment_service.cancel_request("req-1", "coord-1")

    assert hooks == [("req-1", "cancelled", "coord-1")]


def test_a_refused_withdrawal_triggers_nothing(monkeypatch):
    test_equipment_cancel._world(monkeypatch, status="rejected")
    hooks = []
    monkeypatch.setattr(equipment_service, "_notify_technical_support", lambda *a: hooks.append(a))

    with pytest.raises(ValidationError):
        equipment_service.cancel_request("req-1", "coord-1")

    assert hooks == []


# -- AC4: cancelling the session (through the real route) ------------------------------------


@pytest.fixture
def event_hooks(monkeypatch):
    seen = []
    monkeypatch.setattr(routes_module, "_notify_technical_support_cancelled", lambda *a: seen.append(a))
    return seen


def test_cancelling_a_session_triggers_the_hook(client, signing_key, world, event_hooks):  # noqa: F811
    world(["event_coordinator"], "planning")

    response = client.post("/events/event-1/cancel", headers=_auth(signing_key), json={"reason": "No venue"})

    assert response.status_code == 200
    assert event_hooks == [("event-1",)]


def test_a_refused_cancellation_triggers_nothing(client, signing_key, world, event_hooks):  # noqa: F811
    world(["event_coordinator"], "completed")

    response = client.post("/events/event-1/cancel", headers=_auth(signing_key), json={"reason": "No venue"})

    assert response.status_code == 403
    assert event_hooks == []
