"""
Equipment request decision (IS-69): equipment_service._notify_request_decision keeps its signature and hands its own
arguments, untouched, to notification_service.equipment_request_decided. Who gets told what
is test_notification_service.py's job; this proves the wiring, and the
integration test below proves it end to end: a real rejection writes a real
notification.

In its own file so that dropping the [PENDING ...] commit that rewired this
hook drops its test with it.
"""

from __future__ import annotations

import pytest

import app.equipment.equipment_service as equipment_service
import app.notifications.notification_service as notification_service
from tests.test_notifications_integration import _mine, session_with_request, users  # noqa: F401 (fixtures)


def test_equipment_hook_passes_its_arguments_to_the_notification_service(monkeypatch):
    seen = []
    monkeypatch.setattr(notification_service, "equipment_request_decided", lambda *a: seen.append(a))

    equipment_service._notify_request_decision("r", "change accepted")

    assert seen == [("r", "change accepted")]


@pytest.mark.integration
def test_rejecting_an_equipment_request_notifies_the_sessions_current_coordinator(session_with_request, users):  # noqa: F811
    event, request, coordinator_before, coordinator_now = session_with_request
    staff = users(["technical_support_staff"])

    equipment_service.reject_request(request["id"], "Projector is out for repair.", staff)

    [row] = _mine(coordinator_now)
    assert (row["type"], row["entity_type"], row["entity_id"]) == (
        notification_service.EQUIPMENT_REQUEST_REJECTED,
        "event",
        event["id"],
    )
    assert row["message"] == f'Your equipment request for "{event["name"]}" was rejected.'
    assert _mine(coordinator_before) == []
    assert _mine(staff) == []
