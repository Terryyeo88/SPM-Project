"""
app.notifications.notification_service (IS-69): who each notification goes
to, what it says and links to, best-effort writing, and the recipient's own
list / unread count / mark read. In-memory fake, no database; the RLS policy
and the real queries are test_notifications_integration.py's job.
"""

from __future__ import annotations

import logging

import pytest

import app.notifications.notification_service as service
from app.shared.errors import NotFoundError, ValidationError
from tests.fake_supabase import FakeSupabase, _FakeQuery

EVENT_ID = "11111111-1111-1111-1111-111111111111"
REVIEW_ID = "22222222-2222-2222-2222-222222222222"
REQUEST_ID = "33333333-3333-3333-3333-333333333333"


class _LimitQuery(_FakeQuery):
    """The shared fake plus .limit(), which only list_notifications uses."""

    _limit = None

    def limit(self, count):
        self._limit = count
        return self

    def execute(self):
        result = super().execute()
        if self._limit is not None and isinstance(result.data, list):
            result.data = result.data[: self._limit]
        return result


class NotificationsFake(FakeSupabase):
    def table(self, name):
        self.tables.setdefault(name, [])
        return _LimitQuery(self, name)

    @property
    def notifications(self):
        return self.tables.setdefault("notifications", [])


@pytest.fixture
def db(monkeypatch):
    fake = NotificationsFake(
        rows=[{"id": EVENT_ID, "name": "Tech Symposium", "coordinator_id": "coord-now", "status": "planning"}]
    )
    fake.tables["user_roles"] = [
        {"user_id": "officer-1", "role": "safety_officer"},
        {"user_id": "officer-2", "role": "safety_officer"},
        {"user_id": "coord-now", "role": "event_coordinator"},
    ]
    fake.tables["equipment_requests"] = [{"id": REQUEST_ID, "event_id": EVENT_ID, "requested_by": "coord-before"}]
    monkeypatch.setattr(service, "supabase", fake)
    return fake


def _sent(db):
    return [(row["recipient_id"], row["type"]) for row in db.notifications]


# -- notify --------------------------------------------------------------------


def test_notify_writes_one_row_per_distinct_recipient_in_one_insert(db):
    written = service.notify(["b", "a", None, "b"], "some_type", "Hello", "event", EVENT_ID)

    assert written == 2
    inserts = [call for call in db.calls if call["table"] == "notifications" and call["op"] == "insert"]
    assert len(inserts) == 1
    assert sorted(_sent(db)) == [("a", "some_type"), ("b", "some_type")]
    assert {(row["entity_type"], row["entity_id"], row["message"]) for row in db.notifications} == {
        ("event", EVENT_ID, "Hello")
    }


def test_notify_with_nobody_to_tell_writes_nothing(db):
    assert service.notify([None], "some_type", "Hello") == 0
    assert db.calls == []


def test_a_failed_write_is_logged_and_swallowed(monkeypatch, caplog):
    class Broken:
        def table(self, name):
            raise RuntimeError("database down")

    monkeypatch.setattr(service, "supabase", Broken())

    with caplog.at_level(logging.ERROR, logger=service.__name__):
        assert service.notify(["a"], "some_type", "Hello") is None
        service.coordinator_assigned({"id": EVENT_ID, "name": "X"}, {"id": "a"})

    assert [record.getMessage() for record in caplog.records] == [
        "Notification not sent: notify failed",
        "Notification not sent: notify failed",
    ]
    assert all(record.exc_info for record in caplog.records)  # the traceback is kept


def test_a_base_exception_is_not_swallowed(monkeypatch):
    """The unit-test database guard raises a BaseException on purpose, so a
    unit test that reaches the real client still fails loudly."""

    class Guard(BaseException):
        pass

    class Guarded:
        def table(self, name):
            raise Guard()

    monkeypatch.setattr(service, "supabase", Guarded())

    with pytest.raises(Guard):
        service.notify(["a"], "some_type", "Hello")


# -- who is told what ------------------------------------------------------------


def test_coordinator_assigned_tells_the_coordinator_and_links_the_event(db):
    service.coordinator_assigned({"id": EVENT_ID, "name": "Tech Symposium"}, {"id": "coord-new", "name": "Alice"})

    [row] = db.notifications
    assert (row["recipient_id"], row["type"]) == ("coord-new", service.COORDINATOR_ASSIGNED)
    assert row["message"] == 'You have been assigned to coordinate "Tech Symposium".'
    assert (row["entity_type"], row["entity_id"]) == ("event", EVENT_ID)


@pytest.mark.parametrize(
    ("decision", "type_", "message"),
    [
        ("confirmed", service.VENUE_BOOKING_CONFIRMED, 'Your venue booking for "Tech Symposium" was confirmed.'),
        ("rejected", service.VENUE_BOOKING_REJECTED, 'Your venue booking for "Tech Symposium" was rejected.'),
    ],
)
def test_a_venue_booking_decision_goes_to_the_sessions_current_coordinator(db, decision, type_, message):
    service.venue_booking_decided({"id": "b-1", "event_id": EVENT_ID, "requested_by": "coord-before"}, decision)

    [row] = db.notifications
    assert (row["recipient_id"], row["type"], row["message"]) == ("coord-now", type_, message)
    assert (row["entity_type"], row["entity_id"]) == ("event", EVENT_ID)


def test_cancelling_a_booking_notifies_nobody(db):
    """The coordinator cancelled it themselves."""
    service.venue_booking_decided({"id": "b-1", "event_id": EVENT_ID}, "cancelled")
    assert db.notifications == []


def test_a_session_with_no_coordinator_notifies_nobody(db):
    db.rows[0]["coordinator_id"] = None
    service.venue_booking_decided({"id": "b-1", "event_id": EVENT_ID}, "confirmed")
    assert db.notifications == []


def test_a_released_booking_tells_the_coordinator_to_book_another_venue(db):
    service.venue_booking_released({"booking_id": "b-1", "event_id": EVENT_ID}, {"id": "v-1", "name": "Hall A"})

    [row] = db.notifications
    assert (row["recipient_id"], row["type"]) == ("coord-now", service.VENUE_BOOKING_RELEASED)
    assert row["message"] == (
        'Venue "Hall A" was deleted from the venue catalogue, so the booking for "Tech Symposium" was released. '
        "Book another venue."
    )


@pytest.mark.parametrize(
    ("decision", "type_"),
    [
        ("confirmed", service.EQUIPMENT_REQUEST_CONFIRMED),
        ("rejected", service.EQUIPMENT_REQUEST_REJECTED),
        ("change accepted", service.EQUIPMENT_CHANGE_ACCEPTED),
        ("change rejected", service.EQUIPMENT_CHANGE_REJECTED),
    ],
)
def test_an_equipment_decision_goes_to_the_sessions_current_coordinator(db, decision, type_):
    """Every decision string equipment_service and change_service pass."""
    service.equipment_request_decided(REQUEST_ID, decision)

    assert _sent(db) == [("coord-now", type_)]


def test_an_unknown_equipment_decision_or_request_notifies_nobody(db):
    service.equipment_request_decided(REQUEST_ID, "pending")
    service.equipment_request_decided("44444444-4444-4444-4444-444444444444", "confirmed")
    assert db.notifications == []


@pytest.mark.parametrize(
    ("what", "type_"),
    [("submitted", service.SAFETY_REVIEW_SUBMITTED), ("withdrawn", service.SAFETY_REVIEW_WITHDRAWN)],
)
def test_a_submission_or_withdrawal_goes_to_every_safety_officer_and_links_the_review(db, what, type_):
    service.safety_review_changed({"id": REVIEW_ID, "event_id": EVENT_ID, "submitted_by": "coord-now"}, what)

    assert sorted(_sent(db)) == [("officer-1", type_), ("officer-2", type_)]
    assert {(row["entity_type"], row["entity_id"]) for row in db.notifications} == {("safety_review", REVIEW_ID)}


@pytest.mark.parametrize(
    ("what", "type_"),
    [
        ("approved", service.SAFETY_REVIEW_APPROVED),
        ("rejected", service.SAFETY_REVIEW_REJECTED),
        ("changes_requested", service.SAFETY_REVIEW_CHANGES_REQUESTED),
    ],
)
def test_a_safety_decision_goes_to_the_sessions_coordinator(db, what, type_):
    service.safety_review_changed({"id": REVIEW_ID, "event_id": EVENT_ID, "submitted_by": "coord-before"}, what)

    assert _sent(db) == [("coord-now", type_)]
    assert db.notifications[0]["entity_type"] == "event"


# -- the recipient's own list ------------------------------------------------------


def _note(note_id, recipient, created_at, read_at=None):
    return {
        "id": note_id,
        "recipient_id": recipient,
        "type": "t",
        "message": "m",
        "entity_type": None,
        "entity_id": None,
        "read_at": read_at,
        "created_at": created_at,
    }


N1 = "aaaaaaaa-0000-0000-0000-000000000001"
N2 = "aaaaaaaa-0000-0000-0000-000000000002"
N3 = "aaaaaaaa-0000-0000-0000-000000000003"


@pytest.fixture
def inbox(db):
    db.tables["notifications"] = [
        _note(N1, "me", "2026-10-01T00:00:00+00:00"),
        _note(N2, "me", "2026-10-03T00:00:00+00:00", read_at="2026-10-04T00:00:00+00:00"),
        _note(N3, "someone-else", "2026-10-02T00:00:00+00:00"),
    ]
    return db


def test_list_is_only_the_callers_own_newest_first(inbox):
    assert [row["id"] for row in service.list_notifications("me")] == [N2, N1]


@pytest.mark.parametrize("unread", ["true", "1"])
def test_list_can_be_unread_only(inbox, unread):
    assert [row["id"] for row in service.list_notifications("me", unread)] == [N1]


def test_list_rejects_a_nonsense_unread_filter(inbox):
    with pytest.raises(ValidationError):
        service.list_notifications("me", "maybe")


def test_list_is_capped(db):
    db.tables["notifications"] = [_note(f"n-{i}", "me", f"2026-10-01T00:00:{i:02d}+00:00") for i in range(60)]
    assert len(service.list_notifications("me")) == service.LIST_LIMIT


def test_unread_count_counts_only_the_callers_unread(inbox):
    assert service.unread_count("me") == 1
    assert service.unread_count("someone-else") == 1
    assert service.unread_count("nobody") == 0


def test_mark_read_sets_read_at_and_drops_the_count(inbox):
    marked = service.mark_read(N1, "me")

    assert marked["id"] == N1 and marked["read_at"]
    assert service.unread_count("me") == 0


def test_marking_an_already_read_one_keeps_its_first_read_time(inbox):
    assert service.mark_read(N2, "me")["read_at"] == "2026-10-04T00:00:00+00:00"


def test_mark_read_is_scoped_to_the_caller(inbox):
    """authz has already refused this with a 404; the write is scoped anyway."""
    service.mark_read(N3, "me")
    assert inbox.tables["notifications"][2]["read_at"] is None


def test_mark_all_read_marks_only_the_callers_unread(inbox):
    assert service.mark_all_read("me") == 1
    assert service.unread_count("me") == 0
    assert service.unread_count("someone-else") == 1
    assert inbox.tables["notifications"][1]["read_at"] == "2026-10-04T00:00:00+00:00"


@pytest.mark.parametrize("notification_id", ["aaaaaaaa-0000-0000-0000-00000000dead", "not-a-uuid"])
def test_get_notification_missing_or_malformed_is_not_found(inbox, notification_id):
    with pytest.raises(NotFoundError):
        service.get_notification(notification_id)
