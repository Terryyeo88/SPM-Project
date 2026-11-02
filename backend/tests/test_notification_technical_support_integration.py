"""
IS-26 against a real (local) Supabase: the queries behind "who is told" run
against the real schema -- the role lookup, the live-request filter -- and a
real notification row is written, with the entity link the frontend follows.

Skipped without credentials; refuses a non-local database. See the README's
"Running tests".
"""

from __future__ import annotations

import pytest

import app.equipment.equipment_service as equipment_service
import app.notifications.notification_service as service
from app.extensions import supabase
from tests.test_notifications_integration import _mine, session_with_request, users  # noqa: F401 (fixtures)

pytestmark = pytest.mark.integration


def test_withdrawing_a_pending_request_tells_every_technical_support_member_but_not_the_coordinator(
    session_with_request, users  # noqa: F811
):
    event, request, coordinator_before, coordinator_now = session_with_request
    staff_a, staff_b = users(["technical_support_staff"]), users(["technical_support_staff"])

    equipment_service.cancel_request(request["id"], coordinator_before)

    for staff in (staff_a, staff_b):
        [row] = [r for r in _mine(staff) if r["type"] == service.EQUIPMENT_REQUEST_CANCELLED]
        assert (row["entity_type"], row["entity_id"]) == (service.ENTITY_EQUIPMENT_REQUEST, request["id"])
        assert row["message"] == f'The equipment request for "{event["name"]}" was cancelled by the coordinator.'
    assert [r for r in _mine(coordinator_before) if r["type"] == service.EQUIPMENT_REQUEST_CANCELLED] == []


def test_the_person_who_acted_is_not_told_even_when_they_are_technical_support(
    session_with_request, users  # noqa: F811
):
    _, request, _, _ = session_with_request
    actor, other = users(["technical_support_staff"]), users(["technical_support_staff"])

    service.technical_support_request_news(request["id"], "submitted", actor)

    assert _mine(actor) == []
    assert [r["type"] for r in _mine(other)] == [service.EQUIPMENT_REQUEST_SUBMITTED]


def test_a_reschedule_of_a_session_with_a_live_request_tells_technical_support(
    session_with_request, users  # noqa: F811
):
    event, request, _, _ = session_with_request
    staff = users(["technical_support_staff"])

    service.technical_support_event_news(event["id"], "changed", {"preferred_start_date"})

    [row] = _mine(staff)
    assert row["type"] == service.EQUIPMENT_EVENT_CHANGED
    assert row["entity_id"] == request["id"]


def test_a_session_whose_only_request_was_rejected_is_not_news(session_with_request, users):  # noqa: F811
    event, request, _, _ = session_with_request
    staff = users(["technical_support_staff"])
    supabase.table("equipment_requests").update(
        {"status": "rejected", "rejection_reason": "No stock.", "decided_by": staff}
    ).eq("id", request["id"]).execute()

    service.technical_support_event_news(event["id"], "cancelled")
    service.technical_support_event_news(event["id"], "changed", {"preferred_start_date"})

    assert _mine(staff) == []
