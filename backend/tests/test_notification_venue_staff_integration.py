"""
IS-25 against a real (local) Supabase: the role lookup and the live-booking
filter run against the real schema, and real notification rows are written,
linking to the booking Venue Staff open.

Skipped without credentials; refuses a non-local database. See the README's
"Running tests".
"""

from __future__ import annotations

import pytest

import app.notifications.notification_service as service
from app.venues.booking_service import create_booking_request
from tests.test_notifications_integration import _mine
from tests.test_venue_bookings_integration import _event_namespace, fixtures  # noqa: F401 (fixture)

pytestmark = pytest.mark.integration


def _world(fixtures):  # noqa: F811
    coordinator = fixtures.create_user("Venue Notify Coordinator", "event_coordinator")
    staff_a = fixtures.create_user("Venue Notify Staff A", "venue_staff")
    staff_b = fixtures.create_user("Venue Notify Staff B", "venue_staff")
    # events.organizer_id is required, like every other test using this helper.
    organizer = fixtures.create_user("Venue Notify Organizer", "event_organizer")
    venue = fixtures.create_venue()
    event = fixtures.create_event(
        organizer_id=organizer["id"], coordinator_id=coordinator["id"], status="planning"
    )
    return coordinator["id"], staff_a["id"], staff_b["id"], venue, event


def test_a_booking_request_tells_every_venue_staff_member_but_not_the_coordinator(fixtures):  # noqa: F811
    coordinator, staff_a, staff_b, venue, event = _world(fixtures)

    booking = create_booking_request(_event_namespace(event), venue["id"], coordinator)
    fixtures.booking_ids.append(booking["id"])

    for staff in (staff_a, staff_b):
        [row] = [r for r in _mine(staff) if r["type"] == service.VENUE_BOOKING_REQUESTED]
        assert (row["entity_type"], row["entity_id"]) == (service.ENTITY_VENUE_BOOKING, booking["id"])
        assert row["message"] == f'A venue booking request for "{event["name"]}" is waiting for your review.'
    assert [r for r in _mine(coordinator) if r["type"] == service.VENUE_BOOKING_REQUESTED] == []


def test_a_reschedule_of_a_session_with_a_pending_booking_tells_venue_staff(fixtures):  # noqa: F811
    coordinator, staff_a, _, venue, event = _world(fixtures)
    booking = create_booking_request(_event_namespace(event), venue["id"], coordinator)
    fixtures.booking_ids.append(booking["id"])

    service.venue_staff_event_news(event["id"], "changed", {"preferred_start_date"}, coordinator)

    [row] = [r for r in _mine(staff_a) if r["type"] == service.VENUE_EVENT_CHANGED]
    assert row["entity_id"] == booking["id"]


def test_a_session_with_no_booking_is_not_news(fixtures):  # noqa: F811
    coordinator, staff_a, _, _, event = _world(fixtures)

    service.venue_staff_event_news(event["id"], "changed", {"preferred_start_date"}, coordinator)
    service.venue_staff_event_news(event["id"], "cancelled", actor_id=coordinator)

    news = (service.VENUE_EVENT_CHANGED, service.VENUE_EVENT_CANCELLED)
    assert [r for r in _mine(staff_a) if r["type"] in news] == []


def test_a_cancellation_tells_venue_staff_about_the_booking_it_released(fixtures):  # noqa: F811
    coordinator, staff_a, _, venue, event = _world(fixtures)
    booking = create_booking_request(_event_namespace(event), venue["id"], coordinator)
    fixtures.booking_ids.append(booking["id"])

    service.venue_staff_event_news(
        event["id"], "cancelled", actor_id=coordinator, released_booking_ids=[booking["id"]]
    )

    [row] = [r for r in _mine(staff_a) if r["type"] == service.VENUE_EVENT_CANCELLED]
    assert row["entity_id"] == booking["id"]
