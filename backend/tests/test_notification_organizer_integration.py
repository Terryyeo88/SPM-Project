"""
IS-23 against a real (local) Supabase: the organizer's notification is a real
row, addressed to the session's organizer, linking to the session.

Skipped without credentials; refuses a non-local database. See the README's
"Running tests".
"""

from __future__ import annotations

import pytest

import app.notifications.notification_service as service
from tests.test_notifications_integration import _mine, session_with_request, users  # noqa: F401 (fixtures)

pytestmark = pytest.mark.integration


def _organizer_of(event: dict) -> str:
    return event["organizer_id"]


def test_each_milestone_is_a_real_notification_to_the_organizer_only(session_with_request):  # noqa: F811
    event, _, coordinator_before, coordinator_now = session_with_request
    organizer = _organizer_of(event)

    for what in ("submitted", "approved", "rejected", "confirmed", "cancelled"):
        service.organizer_event_news(event["id"], what, coordinator_now)

    mine = _mine(organizer)
    assert sorted(row["type"] for row in mine) == sorted(
        [
            service.EVENT_REQUEST_SUBMITTED,
            service.EVENT_REQUEST_APPROVED,
            service.EVENT_REQUEST_REJECTED,
            service.EVENT_CONFIRMED,
            service.EVENT_CANCELLED_ORGANIZER,
        ]
    )
    assert {(row["entity_type"], row["entity_id"]) for row in mine} == {(service.ENTITY_EVENT, event["id"])}
    assert _mine(coordinator_now) == [] and _mine(coordinator_before) == []


def test_the_organizer_is_told_of_their_own_submission_but_not_their_own_decision(session_with_request):  # noqa: F811
    event, *_ = session_with_request
    organizer = _organizer_of(event)

    service.organizer_event_news(event["id"], "submitted", organizer)
    service.organizer_event_news(event["id"], "cancelled", organizer)

    assert [row["type"] for row in _mine(organizer)] == [service.EVENT_REQUEST_SUBMITTED]
