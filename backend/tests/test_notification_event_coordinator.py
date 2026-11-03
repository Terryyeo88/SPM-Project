"""
IS-24 Notification (Event Coordinator) -- the two additions made on top of
IS-69: who is told what when a venue is blocked under a booking and when the
organizer asks for a significant change. In-memory fake, no database. When
each is triggered is test_notification_hook_event_coordinator.py's job.

Also covers Overwrite Venue Booking's venue_booking_overwritten -- a third,
later addition to the same "tell the session's coordinator" shape.
"""

from __future__ import annotations

import logging

import pytest

import app.notifications.notification_service as service
from tests.test_notification_service import NotificationsFake

SESSION_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def db(monkeypatch):
    fake = NotificationsFake(
        rows=[
            {
                "id": SESSION_ID,
                "shared_event_id": "group-1",
                "name": "Tech Symposium",
                "preferred_start_date": "2026-11-12",
                "preferred_start_time": "14:00:00",
                "organizer_id": "org-1",
                "coordinator_id": "coord-1",
                "status": "planning",
            }
        ]
    )
    monkeypatch.setattr(service, "supabase", fake)
    return fake


def _only(db):
    [row] = db.notifications
    return row


# -- a venue blocked under a booking --------------------------------------------------------


def test_a_blocked_venue_tells_the_sessions_coordinator_to_book_again(db):
    service.venue_booking_blocked({"id": "b1", "event_id": SESSION_ID})

    row = _only(db)
    assert (row["recipient_id"], row["type"]) == ("coord-1", service.VENUE_BOOKING_BLOCKED)
    assert row["message"] == (
        'The venue for "Tech Symposium" was blocked, so its booking was released. Book another venue.'
    )
    assert (row["entity_type"], row["entity_id"]) == (service.ENTITY_EVENT, SESSION_ID)


def test_the_coordinator_told_is_the_current_one_not_the_organizer(db):
    db.rows[0]["coordinator_id"] = "coord-2"
    service.venue_booking_blocked({"id": "b1", "event_id": SESSION_ID})
    assert [row["recipient_id"] for row in db.notifications] == ["coord-2"]


def test_a_blocked_booking_of_an_unknown_session_tells_nobody(db):
    service.venue_booking_blocked({"id": "b1", "event_id": "99999999-9999-9999-9999-999999999999"})
    service.venue_booking_blocked({"id": "b1"})
    assert db.notifications == []


def test_a_blocked_booking_of_a_session_with_no_coordinator_tells_nobody(db):
    db.rows[0]["coordinator_id"] = None
    service.venue_booking_blocked({"id": "b1", "event_id": SESSION_ID})
    assert db.notifications == []


# -- Overwrite Venue Booking: Venue Staff directly invalidated a booking ----------------------


def test_an_overwritten_booking_tells_the_sessions_coordinator_and_the_reason(db):
    service.venue_booking_overwritten({"id": "b1", "event_id": SESSION_ID}, "Venue has a burst pipe")

    row = _only(db)
    assert (row["recipient_id"], row["type"]) == ("coord-1", service.VENUE_BOOKING_OVERWRITTEN)
    assert row["message"] == (
        'Venue Staff overwrote the venue booking for "Tech Symposium": Venue has a burst pipe. '
        "Book another venue."
    )
    assert (row["entity_type"], row["entity_id"]) == (service.ENTITY_EVENT, SESSION_ID)


def test_the_coordinator_told_of_an_overwrite_is_the_current_one(db):
    db.rows[0]["coordinator_id"] = "coord-2"
    service.venue_booking_overwritten({"id": "b1", "event_id": SESSION_ID}, "Unsuitable.")
    assert [row["recipient_id"] for row in db.notifications] == ["coord-2"]


def test_an_overwritten_booking_of_an_unknown_session_tells_nobody(db):
    service.venue_booking_overwritten({"id": "b1", "event_id": "99999999-9999-9999-9999-999999999999"}, "x")
    service.venue_booking_overwritten({"id": "b1"}, "x")
    assert db.notifications == []


def test_an_overwritten_booking_of_a_session_with_no_coordinator_tells_nobody(db):
    db.rows[0]["coordinator_id"] = None
    service.venue_booking_overwritten({"id": "b1", "event_id": SESSION_ID}, "x")
    assert db.notifications == []


# -- the organizer asks for a significant change ---------------------------------------------


def test_a_significant_change_request_tells_the_assigned_coordinator_and_names_the_session(db):
    service.event_change_requested(SESSION_ID)

    row = _only(db)
    assert (row["recipient_id"], row["type"]) == ("coord-1", service.EVENT_CHANGE_REQUESTED)
    assert row["message"] == (
        'The organizer asked for a significant change to "Tech Symposium" on 12 Nov 2026, 2:00 PM. '
        "Review the request."
    )
    assert (row["entity_type"], row["entity_id"]) == (service.ENTITY_EVENT, SESSION_ID)


def test_only_the_coordinator_assigned_to_that_session_is_told(db):
    service.event_change_requested(SESSION_ID)
    assert [row["recipient_id"] for row in db.notifications] == ["coord-1"]
    assert "org-1" not in [row["recipient_id"] for row in db.notifications]


def test_a_session_with_no_coordinator_yet_tells_nobody(db):
    db.rows[0]["coordinator_id"] = None
    service.event_change_requested(SESSION_ID)
    assert db.notifications == []


def test_an_unknown_session_tells_nobody(db):
    service.event_change_requested("99999999-9999-9999-9999-999999999999")
    assert db.notifications == []


# -- best effort ------------------------------------------------------------------------------


def test_a_failed_write_is_logged_and_swallowed(monkeypatch, caplog):
    class Broken:
        def table(self, name):
            raise RuntimeError("database down")

    monkeypatch.setattr(service, "supabase", Broken())

    with caplog.at_level(logging.ERROR, logger=service.__name__):
        assert service.event_change_requested(SESSION_ID) is None
        assert service.venue_booking_blocked({"id": "b1", "event_id": SESSION_ID}) is None

    assert [record.getMessage() for record in caplog.records] == [
        "Notification not sent: event_change_requested failed",
        "Notification not sent: venue_booking_blocked failed",
    ]
