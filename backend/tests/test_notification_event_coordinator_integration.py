"""
IS-24 against a real (local) Supabase: the two new notifications are real
rows addressed to the session's CURRENT coordinator, linking to the session.

Skipped without credentials; refuses a non-local database. See the README's
"Running tests".
"""

from __future__ import annotations

import pytest

import app.notifications.notification_service as service
from tests.test_notifications_integration import _mine, session_with_request, users  # noqa: F401 (fixtures)

pytestmark = pytest.mark.integration


def test_a_significant_change_request_reaches_the_current_coordinator_only(session_with_request):  # noqa: F811
    event, _, coordinator_before, coordinator_now = session_with_request

    service.event_change_requested(event["id"])

    [row] = _mine(coordinator_now)
    assert (row["type"], row["entity_type"], row["entity_id"]) == (
        service.EVENT_CHANGE_REQUESTED,
        service.ENTITY_EVENT,
        event["id"],
    )
    assert _mine(coordinator_before) == [] and _mine(event["organizer_id"]) == []


def test_a_blocked_venue_reaches_the_current_coordinator_only(session_with_request):  # noqa: F811
    event, _, coordinator_before, coordinator_now = session_with_request

    service.venue_booking_blocked({"id": "b1", "event_id": event["id"]})

    [row] = _mine(coordinator_now)
    assert row["type"] == service.VENUE_BOOKING_BLOCKED
    assert row["message"] == (
        f'The venue for "{event["name"]}" was blocked, so its booking was released. Book another venue.'
    )
    assert _mine(coordinator_before) == [] and _mine(event["organizer_id"]) == []
