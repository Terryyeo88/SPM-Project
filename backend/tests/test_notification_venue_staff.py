"""
IS-25 Notification (Venue Staff) -- who is told what, and when nobody is.
In-memory fake, no database. When each is triggered is
test_notification_hook_venue_staff.py's job.
"""

from __future__ import annotations

import logging

import pytest

import app.notifications.notification_service as service
from tests.test_notification_service import NotificationsFake

SESSION_ID = "11111111-1111-1111-1111-111111111111"
BOOKING_A = "00000000-0000-0000-0000-00000000000a"
BOOKING_B = "00000000-0000-0000-0000-00000000000b"
STAFF = ("staff-1", "staff-2")


@pytest.fixture
def db(monkeypatch):
    fake = NotificationsFake(
        rows=[{"id": SESSION_ID, "name": "Tech Symposium", "coordinator_id": "coord-1", "status": "planning"}]
    )
    fake.tables["user_roles"] = [
        {"user_id": "staff-1", "role": "venue_staff"},
        {"user_id": "staff-2", "role": "venue_staff"},
        {"user_id": "coord-1", "role": "event_coordinator"},
        {"user_id": "tech-1", "role": "technical_support_staff"},
    ]
    fake.tables["venue_bookings"] = [
        {"id": BOOKING_B, "event_id": SESSION_ID, "status": "confirmed"},
        {"id": BOOKING_A, "event_id": SESSION_ID, "status": "pending"},
        {"id": "00000000-0000-0000-0000-0000000000f1", "event_id": SESSION_ID, "status": "rejected"},
        {"id": "00000000-0000-0000-0000-0000000000f2", "event_id": "other-event", "status": "confirmed"},
    ]
    monkeypatch.setattr(service, "supabase", fake)
    return fake


def _sent(db):
    return sorted((row["recipient_id"], row["type"]) for row in db.notifications)


def _links(db):
    return {(row["entity_type"], row["entity_id"]) for row in db.notifications}


# -- AC1: a booking request is waiting -----------------------------------------------------------


def test_a_booking_request_tells_every_venue_staff_member_and_nobody_else(db):
    service.venue_staff_booking_requested({"id": BOOKING_A, "event_id": SESSION_ID}, "coord-1")

    assert _sent(db) == [(staff, service.VENUE_BOOKING_REQUESTED) for staff in STAFF]
    assert _links(db) == {(service.ENTITY_VENUE_BOOKING, BOOKING_A)}
    assert {row["message"] for row in db.notifications} == {
        'A venue booking request for "Tech Symposium" is waiting for your review.'
    }


def test_the_person_who_requested_is_not_told_even_when_they_are_venue_staff(db):
    service.venue_staff_booking_requested({"id": BOOKING_A, "event_id": SESSION_ID}, "staff-1")
    assert _sent(db) == [("staff-2", service.VENUE_BOOKING_REQUESTED)]


def test_a_booking_request_for_an_unknown_session_tells_nobody(db):
    service.venue_staff_booking_requested({"id": BOOKING_A, "event_id": "99999999-9999-9999-9999-999999999999"})
    assert db.notifications == []


def test_with_no_venue_staff_nothing_is_written(db):
    db.tables["user_roles"] = [{"user_id": "coord-1", "role": "event_coordinator"}]
    service.venue_staff_booking_requested({"id": BOOKING_A, "event_id": SESSION_ID})
    assert db.notifications == []


# -- AC3: rescheduled ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fields",
    [
        {"preferred_start_date"},
        {"preferred_end_date"},
        {"preferred_start_time"},
        {"preferred_end_time", "name"},
        {"preferred_start_date", "room_layout"},
    ],
)
def test_a_new_date_or_time_tells_venue_staff_the_session_was_rescheduled(db, fields):
    service.venue_staff_event_news(SESSION_ID, "changed", fields, "coord-1")

    assert _sent(db) == [(staff, service.VENUE_EVENT_CHANGED) for staff in STAFF]
    assert db.notifications[0]["message"] == (
        '"Tech Symposium" was rescheduled. Check that its venue booking still fits the new date and time.'
    )
    assert _links(db) == {(service.ENTITY_VENUE_BOOKING, BOOKING_A)}  # the first live booking by id


# -- AC2: changed in a way that affects the venue ----------------------------------------------------


@pytest.mark.parametrize("fields", [{"expected_attendance"}, {"room_layout"}, {"accessibility_needs", "name"}])
def test_a_change_to_attendance_layout_or_accessibility_tells_venue_staff(db, fields):
    service.venue_staff_event_news(SESSION_ID, "changed", fields)

    assert _sent(db) == [(staff, service.VENUE_EVENT_CHANGED) for staff in STAFF]
    assert db.notifications[0]["message"] == (
        'A detail of "Tech Symposium" that affects its venue changed. Check its venue booking.'
    )


@pytest.mark.parametrize(
    "fields", [set(), {"name"}, {"description", "purpose"}, {"equipment"}, {"special_requests"}]
)
def test_a_change_the_venue_does_not_depend_on_is_not_news(db, fields):
    service.venue_staff_event_news(SESSION_ID, "changed", fields)
    assert db.notifications == []


def test_a_change_to_a_session_with_no_live_booking_is_not_news(db):
    db.tables["venue_bookings"] = [{"id": BOOKING_A, "event_id": SESSION_ID, "status": "rejected"}]
    service.venue_staff_event_news(SESSION_ID, "changed", {"preferred_start_date"})
    assert db.notifications == []


def test_the_person_who_changed_the_session_is_not_told(db):
    service.venue_staff_event_news(SESSION_ID, "changed", {"preferred_start_date"}, "staff-2")
    assert _sent(db) == [("staff-1", service.VENUE_EVENT_CHANGED)]


# -- AC4: cancelled ------------------------------------------------------------------------------------


def test_a_cancelled_session_with_a_live_booking_tells_venue_staff(db):
    service.venue_staff_event_news(SESSION_ID, "cancelled", actor_id="coord-1")

    assert _sent(db) == [(staff, service.VENUE_EVENT_CANCELLED) for staff in STAFF]
    assert db.notifications[0]["message"] == '"Tech Symposium" was cancelled. Its venue booking has been released.'


def test_a_booking_the_cancellation_just_released_still_counts(db):
    # By the time the hook runs the confirmed booking is "released", not live.
    db.tables["venue_bookings"] = [{"id": BOOKING_A, "event_id": SESSION_ID, "status": "released"}]

    service.venue_staff_event_news(SESSION_ID, "cancelled", released_booking_ids=[BOOKING_A])

    assert _sent(db) == [(staff, service.VENUE_EVENT_CANCELLED) for staff in STAFF]
    assert _links(db) == {(service.ENTITY_VENUE_BOOKING, BOOKING_A)}


def test_an_old_release_from_before_the_cancellation_does_not_count(db):
    db.tables["venue_bookings"] = [{"id": BOOKING_A, "event_id": SESSION_ID, "status": "released"}]
    service.venue_staff_event_news(SESSION_ID, "cancelled")
    assert db.notifications == []


@pytest.mark.parametrize("status", ["rejected", "cancelled"])
def test_a_session_whose_bookings_are_over_is_not_news(db, status):
    db.tables["venue_bookings"] = [{"id": BOOKING_A, "event_id": SESSION_ID, "status": status}]
    service.venue_staff_event_news(SESSION_ID, "cancelled")
    assert db.notifications == []


def test_an_unknown_session_tells_nobody(db):
    service.venue_staff_event_news("99999999-9999-9999-9999-999999999999", "cancelled")
    assert db.notifications == []


@pytest.mark.parametrize("what", ["confirmed", "approved", "", "nonsense"])
def test_news_of_another_kind_is_ignored(db, what):
    service.venue_staff_event_news(SESSION_ID, what, {"preferred_start_date"})
    assert db.notifications == []


# -- best effort ---------------------------------------------------------------------------------------


def test_a_failed_write_is_logged_and_swallowed(monkeypatch, caplog):
    class Broken:
        def table(self, name):
            raise RuntimeError("database down")

    monkeypatch.setattr(service, "supabase", Broken())

    with caplog.at_level(logging.ERROR, logger=service.__name__):
        assert service.venue_staff_booking_requested({"id": BOOKING_A, "event_id": SESSION_ID}) is None
        assert service.venue_staff_event_news(SESSION_ID, "cancelled") is None

    assert [record.getMessage() for record in caplog.records] == [
        "Notification not sent: venue_staff_booking_requested failed",
        "Notification not sent: venue_staff_event_news failed",
    ]
