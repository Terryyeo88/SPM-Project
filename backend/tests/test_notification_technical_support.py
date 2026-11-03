"""
IS-26 Receive Technical Support Notifications -- who is told what, and when
nobody is. In-memory fake, no database. The wiring (that each story's own
code reaches these) is test_notification_hook_technical_support.py.
"""

from __future__ import annotations

import logging

import pytest

import app.notifications.notification_service as service
from tests.test_notification_service import EVENT_ID, REQUEST_ID, NotificationsFake

STAFF = ("staff-1", "staff-2")


@pytest.fixture
def db(monkeypatch):
    fake = NotificationsFake(
        rows=[{"id": EVENT_ID, "name": "Tech Symposium", "coordinator_id": "coord-now", "status": "planning"}]
    )
    fake.tables["user_roles"] = [
        {"user_id": "staff-1", "role": "technical_support_staff"},
        {"user_id": "staff-2", "role": "technical_support_staff"},
        {"user_id": "coord-now", "role": "event_coordinator"},
        {"user_id": "officer-1", "role": "safety_officer"},
    ]
    fake.tables["equipment_requests"] = [
        {"id": REQUEST_ID, "event_id": EVENT_ID, "status": "pending"},
        {"id": "00000000-0000-0000-0000-000000000001", "event_id": EVENT_ID, "status": "rejected"},
        {"id": "00000000-0000-0000-0000-000000000002", "event_id": "other-event", "status": "confirmed"},
    ]
    monkeypatch.setattr(service, "supabase", fake)
    return fake


def _sent(db):
    return sorted((row["recipient_id"], row["type"]) for row in db.notifications)


def _links(db):
    return {(row["entity_type"], row["entity_id"]) for row in db.notifications}


# -- AC1, AC2: a request is submitted, a quantity change is asked for ---------------------


def test_a_submitted_request_tells_every_technical_support_member_and_nobody_else(db):
    service.technical_support_request_news(REQUEST_ID, "submitted", "coord-now")

    assert _sent(db) == [(staff, service.EQUIPMENT_REQUEST_SUBMITTED) for staff in STAFF]
    assert _links(db) == {(service.ENTITY_EQUIPMENT_REQUEST, REQUEST_ID)}
    assert {row["message"] for row in db.notifications} == {
        'A new equipment request for "Tech Symposium" is waiting for your review.'
    }


def test_a_quantity_change_tells_technical_support(db):
    service.technical_support_request_news(REQUEST_ID, "change requested", "coord-now")

    assert _sent(db) == [(staff, service.EQUIPMENT_CHANGE_REQUESTED) for staff in STAFF]
    assert "change the quantity" in db.notifications[0]["message"]


def test_a_withdrawn_request_tells_technical_support(db):
    service.technical_support_request_news(REQUEST_ID, "cancelled", "coord-now")

    assert _sent(db) == [(staff, service.EQUIPMENT_REQUEST_CANCELLED) for staff in STAFF]
    assert db.notifications[0]["message"] == (
        'The equipment request for "Tech Symposium" was cancelled by the coordinator.'
    )


def test_the_person_who_acted_is_not_told_about_their_own_action(db):
    service.technical_support_request_news(REQUEST_ID, "submitted", "staff-1")

    assert _sent(db) == [("staff-2", service.EQUIPMENT_REQUEST_SUBMITTED)]


@pytest.mark.parametrize("what", ["confirmed", "rejected", "", "nonsense"])
def test_other_request_news_is_not_technical_supports_to_hear(db, what):
    service.technical_support_request_news(REQUEST_ID, what, "coord-now")
    assert db.notifications == []


def test_an_unknown_request_tells_nobody(db):
    service.technical_support_request_news("99999999-9999-9999-9999-999999999999", "submitted", None)
    assert db.notifications == []


def test_with_no_technical_support_members_nothing_is_written(db):
    db.tables["user_roles"] = [{"user_id": "coord-now", "role": "event_coordinator"}]
    service.technical_support_request_news(REQUEST_ID, "submitted", None)
    assert db.notifications == []


# -- AC4: the session is cancelled ---------------------------------------------------------


def test_a_cancelled_session_with_a_live_request_tells_technical_support(db):
    service.technical_support_event_news(EVENT_ID, "cancelled", actor_id="coord-now")

    assert _sent(db) == [(staff, service.EQUIPMENT_EVENT_CANCELLED) for staff in STAFF]
    assert _links(db) == {(service.ENTITY_EQUIPMENT_REQUEST, REQUEST_ID)}
    assert db.notifications[0]["message"] == '"Tech Symposium" was cancelled. Its equipment has been released.'


@pytest.mark.parametrize("status", ["rejected", "cancelled"])
def test_a_session_whose_requests_are_over_is_not_news(db, status):
    db.tables["equipment_requests"] = [{"id": REQUEST_ID, "event_id": EVENT_ID, "status": status}]
    service.technical_support_event_news(EVENT_ID, "cancelled")
    assert db.notifications == []


def test_a_session_with_no_equipment_request_is_not_news(db):
    db.tables["equipment_requests"] = []
    service.technical_support_event_news(EVENT_ID, "cancelled")
    service.technical_support_event_news(EVENT_ID, "changed", {"preferred_start_date"})
    assert db.notifications == []


def test_a_confirmed_request_counts_as_live(db):
    db.tables["equipment_requests"] = [{"id": REQUEST_ID, "event_id": EVENT_ID, "status": "confirmed"}]
    service.technical_support_event_news(EVENT_ID, "cancelled")
    assert len(db.notifications) == 2


def test_an_unknown_session_tells_nobody(db):
    service.technical_support_event_news("99999999-9999-9999-9999-999999999999", "cancelled")
    assert db.notifications == []


# -- AC2, AC3: the session is changed or rescheduled ---------------------------------------


@pytest.mark.parametrize(
    "fields",
    [
        {"preferred_start_date"},
        {"preferred_end_time"},
        {"preferred_start_time", "name"},
        {"room_layout", "preferred_start_date"},
    ],
)
def test_a_new_date_or_time_tells_technical_support_the_session_was_rescheduled(db, fields):
    service.technical_support_event_news(EVENT_ID, "changed", fields, "coord-now")

    assert _sent(db) == [(staff, service.EQUIPMENT_EVENT_CHANGED) for staff in STAFF]
    assert _links(db) == {(service.ENTITY_EQUIPMENT_REQUEST, REQUEST_ID)}
    assert db.notifications[0]["message"] == (
        '"Tech Symposium" was rescheduled. Check that its equipment booking still fits the new date and time.'
    )


@pytest.mark.parametrize("fields", [{"equipment"}, {"room_layout"}, {"equipment", "special_requests"}])
def test_a_new_equipment_list_or_room_layout_tells_technical_support(db, fields):
    service.technical_support_event_news(EVENT_ID, "changed", fields)

    assert _sent(db) == [(staff, service.EQUIPMENT_EVENT_CHANGED) for staff in STAFF]
    assert db.notifications[0]["message"] == (
        'The equipment or room layout for "Tech Symposium" was changed. Check its equipment booking.'
    )


@pytest.mark.parametrize(
    "fields", [set(), {"name"}, {"description", "purpose"}, {"expected_attendance"}, {"special_requests"}]
)
def test_a_change_to_something_technical_support_does_not_arrange_around_is_not_news(db, fields):
    service.technical_support_event_news(EVENT_ID, "changed", fields)
    assert db.notifications == []


def test_the_person_who_changed_the_session_is_not_told(db):
    service.technical_support_event_news(EVENT_ID, "changed", {"preferred_start_date"}, "staff-2")
    assert _sent(db) == [("staff-1", service.EQUIPMENT_EVENT_CHANGED)]


def test_news_of_another_kind_is_ignored(db):
    service.technical_support_event_news(EVENT_ID, "confirmed", {"preferred_start_date"})
    assert db.notifications == []


# -- best effort ---------------------------------------------------------------------------


def test_a_failed_write_is_logged_and_swallowed(monkeypatch, caplog):
    class Broken:
        def table(self, name):
            raise RuntimeError("database down")

    monkeypatch.setattr(service, "supabase", Broken())

    with caplog.at_level(logging.ERROR, logger=service.__name__):
        assert service.technical_support_request_news(REQUEST_ID, "submitted") is None
        assert service.technical_support_event_news(EVENT_ID, "cancelled") is None

    assert [record.getMessage() for record in caplog.records] == [
        "Notification not sent: technical_support_request_news failed",
        "Notification not sent: technical_support_event_news failed",
    ]
