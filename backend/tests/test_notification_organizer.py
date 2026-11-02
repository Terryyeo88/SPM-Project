"""
IS-23 Notification (Event Organizer) -- who is told what. In-memory fake, no
database. When each notification is triggered is
test_notification_hook_organizer.py's job.
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
                "status": "under_review",
            }
        ]
    )
    monkeypatch.setattr(service, "supabase", fake)
    return fake


def _only(db):
    [row] = db.notifications
    return row


@pytest.mark.parametrize(
    "what, type_, message",
    [
        ("submitted", service.EVENT_REQUEST_SUBMITTED, 'Your event request "Tech Symposium" was submitted.'),
        ("approved", service.EVENT_REQUEST_APPROVED, 'Your event request "Tech Symposium" was approved.'),
        (
            "rejected",
            service.EVENT_REQUEST_REJECTED,
            'Your event request "Tech Symposium" was rejected. Open it to see the reason.',
        ),
        ("confirmed", service.EVENT_CONFIRMED, '"Tech Symposium" on 12 Nov 2026, 2:00 PM has been confirmed.'),
        (
            "cancelled",
            service.EVENT_CANCELLED_ORGANIZER,
            '"Tech Symposium" on 12 Nov 2026, 2:00 PM was cancelled. Open it to see the reason.',
        ),
    ],
)
def test_the_organizer_is_told_each_milestone_of_their_request(db, what, type_, message):
    service.organizer_event_news(SESSION_ID, what, "coord-1")

    row = _only(db)
    assert (row["recipient_id"], row["type"], row["message"]) == ("org-1", type_, message)
    assert (row["entity_type"], row["entity_id"]) == (service.ENTITY_EVENT, SESSION_ID)


def test_only_the_organizer_is_told_not_the_coordinator(db):
    service.organizer_event_news(SESSION_ID, "approved", "coord-1")
    assert [row["recipient_id"] for row in db.notifications] == ["org-1"]


def test_the_organizer_is_told_of_their_own_submission(db):
    service.organizer_event_news(SESSION_ID, "submitted", "org-1")
    assert _only(db)["recipient_id"] == "org-1"


@pytest.mark.parametrize("what", ["approved", "rejected", "confirmed", "cancelled"])
def test_the_organizer_is_not_told_of_anything_else_they_did_themselves(db, what):
    service.organizer_event_news(SESSION_ID, what, "org-1")
    assert db.notifications == []


@pytest.mark.parametrize("what", ["planning", "completed", "under_review", "", "nonsense"])
def test_other_status_changes_are_not_the_organizers_to_hear(db, what):
    service.organizer_event_news(SESSION_ID, what, "coord-1")
    assert db.notifications == []


def test_an_unknown_session_tells_nobody(db):
    service.organizer_event_news("99999999-9999-9999-9999-999999999999", "approved", "coord-1")
    assert db.notifications == []


def test_a_session_with_no_organizer_tells_nobody(db):
    db.rows[0]["organizer_id"] = None
    service.organizer_event_news(SESSION_ID, "approved", "coord-1")
    assert db.notifications == []


def test_a_failed_write_is_logged_and_swallowed(monkeypatch, caplog):
    class Broken:
        def table(self, name):
            raise RuntimeError("database down")

    monkeypatch.setattr(service, "supabase", Broken())

    with caplog.at_level(logging.ERROR, logger=service.__name__):
        assert service.organizer_event_news(SESSION_ID, "approved") is None

    assert [record.getMessage() for record in caplog.records] == [
        "Notification not sent: organizer_event_news failed"
    ]
