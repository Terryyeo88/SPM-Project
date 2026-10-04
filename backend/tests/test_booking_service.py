"""
Unit tests for app.venues.booking_service -- Venue Booking Request /
Approval (Josiah, Sprint 2).

Unit-level like the service half of test_event_decisions.py: no real
Supabase. A small local fake client is used instead of the shared
tests/fake_supabase.FakeSupabase -- that module's own docstring says it
only models what event_service/coordinator_service use (no
`.maybe_single()`), so this follows test_event_decisions.py's own
precedent of writing a local fake scoped to what THIS service needs,
rather than extending another module's test double.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.venues.booking_service as service_module
from app.shared.errors import NotFoundError, ValidationError
from tests.factories import make_user


class _FakeQuery:
    def __init__(self, db, table):
        self.db, self.table, self.filters, self.in_filters = db, table, [], []
        self.op, self.payload, self.ordering, self.want_maybe_single = None, None, None, False

    def select(self, *_):
        return self

    def insert(self, payload):
        self.op, self.payload = "insert", payload
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def in_(self, column, values):
        self.in_filters.append((column, tuple(values)))
        return self

    def order(self, column, desc=False):
        self.ordering = (column, desc)
        return self

    def maybe_single(self):
        self.want_maybe_single = True
        return self

    def _matches(self, row):
        for column, value in self.filters:
            if row.get(column) != value:
                return False
        for column, values in self.in_filters:
            if row.get(column) not in values:
                return False
        return True

    def execute(self):
        rows = self.db.tables.setdefault(self.table, [])
        self.db.calls.append({"table": self.table, "op": self.op, "filters": list(self.filters)})

        if self.op == "insert":
            new_rows = self.payload if isinstance(self.payload, list) else [self.payload]
            created = []
            for row in new_rows:
                stored = {"id": self.db.new_id(), **row}
                rows.append(stored)
                created.append(dict(stored))
            self.db.inserts.extend((self.table, row) for row in created)
            return SimpleNamespace(data=created)

        matched = [row for row in rows if self._matches(row)]
        if self.op == "update":
            for row in matched:
                row.update(self.payload)
        data = [dict(row) for row in matched]
        if self.ordering:
            column, desc = self.ordering
            data.sort(key=lambda row: row.get(column) or "", reverse=desc)
        if self.want_maybe_single:
            # Real maybe_single().execute() returns None itself (not a
            # response object) on zero matches -- see
            # app.auth.context._get_last_active's own comment on this.
            return SimpleNamespace(data=data[0]) if data else None
        return SimpleNamespace(data=data)


class _FakeSupabase:
    def __init__(self):
        self.tables, self.calls, self.inserts = {}, [], []
        self._next_id = 0

    def table(self, name):
        self.tables.setdefault(name, [])
        return _FakeQuery(self, name)

    def new_id(self):
        self._next_id += 1
        return f"row-{self._next_id}"


@pytest.fixture
def fake_db(monkeypatch):
    db = _FakeSupabase()
    monkeypatch.setattr(service_module, "supabase", db)
    return db


def _venue(venue_id="venue-1", setup=30, turnaround=30, **overrides):
    row = {"id": venue_id, "name": "Test Venue", "setup_minutes": setup, "turnaround_minutes": turnaround}
    row.update(overrides)
    return row


def _event(event_id="event-1", status="planning", **overrides):
    row = SimpleNamespace(
        id=event_id,
        status=status,
        preferred_start_date="2026-11-01",
        preferred_end_date=None,
        preferred_start_time="09:00",
        preferred_end_time="17:00",
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def _booking(booking_id="booking-1", venue_id="venue-1", status="pending", **overrides):
    row = {
        "id": booking_id,
        "event_id": "event-1",
        "venue_id": venue_id,
        "status": status,
        "requested_by": "coord-1",
        "setup_minutes": 30,
        "turnaround_minutes": 30,
        "booking_start": "2026-11-01T08:30:00+08:00",
        "booking_end": "2026-11-01T17:30:00+08:00",
    }
    row.update(overrides)
    return row


# -- create_booking_request: buffer math -------------------------------------


def test_create_booking_applies_setup_and_turnaround_buffers(fake_db):
    fake_db.tables["venues"] = [_venue(setup=30, turnaround=90)]
    event = _event(status="planning", preferred_start_time="09:00", preferred_end_time="17:00")

    booking = service_module.create_booking_request(event, "venue-1", "coord-1")

    assert booking["booking_start"] == "2026-11-01T08:30:00+08:00"
    assert booking["booking_end"] == "2026-11-01T18:30:00+08:00"
    assert booking["setup_minutes"] == 30
    assert booking["turnaround_minutes"] == 90
    assert booking["status"] == "pending"
    assert booking["requested_by"] == "coord-1"


def test_create_booking_snapshots_buffers_not_a_live_reference(fake_db):
    """Changing the venue's buffers later must not retroactively change
    an already-created booking's padded span -- see the migration's own
    comment on why these columns are snapshotted."""
    fake_db.tables["venues"] = [_venue(setup=15, turnaround=15)]
    event = _event()

    booking = service_module.create_booking_request(event, "venue-1", "coord-1")
    fake_db.tables["venues"][0]["setup_minutes"] = 999

    assert booking["setup_minutes"] == 15


def test_create_booking_raises_for_unknown_venue(fake_db):
    event = _event()
    with pytest.raises(ValidationError):
        service_module.create_booking_request(event, "does-not-exist", "coord-1")
    assert fake_db.tables.get("venue_bookings", []) == []


@pytest.mark.parametrize("venue_id", [None, "", "   ", 42])
def test_create_booking_requires_a_venue_id(fake_db, venue_id):
    event = _event()
    with pytest.raises(ValidationError):
        service_module.create_booking_request(event, venue_id, "coord-1")
    assert fake_db.tables.get("venue_bookings", []) == []


# -- create_booking_request: approved -> planning side effect ---------------


def test_create_booking_moves_an_approved_event_to_planning(fake_db):
    fake_db.tables["venues"] = [_venue()]
    fake_db.tables["events"] = [{"id": "event-1", "status": "approved"}]
    event = _event(status="approved")

    service_module.create_booking_request(event, "venue-1", "coord-1")

    assert fake_db.tables["events"][0]["status"] == "planning"


def test_create_booking_does_not_touch_an_already_planning_event(fake_db):
    fake_db.tables["venues"] = [_venue()]
    fake_db.tables["events"] = [{"id": "event-1", "status": "planning"}]
    event = _event(status="planning")

    service_module.create_booking_request(event, "venue-1", "coord-1")

    assert fake_db.tables["events"][0]["status"] == "planning"
    assert not any(call["table"] == "events" for call in fake_db.calls)


def test_create_booking_side_effect_is_conditioned_on_still_being_approved(fake_db):
    """Same race-proofing idiom as event_service._decide: the UPDATE is
    conditioned on status still being "approved", so a second, racing
    booking_request call against an event already flipped to "planning"
    is a no-op, not an error and not a double-write."""
    fake_db.tables["venues"] = [_venue()]
    fake_db.tables["events"] = [{"id": "event-1", "status": "planning"}]
    event = _event(status="approved")  # caller's stale in-memory copy

    service_module.create_booking_request(event, "venue-1", "coord-1")

    assert fake_db.tables["events"][0]["status"] == "planning"


# -- get_booking: computed conflict field -------------------------------------


def test_get_booking_raises_not_found_for_missing_id(fake_db):
    with pytest.raises(NotFoundError):
        service_module.get_booking("does-not-exist")


def test_get_booking_conflict_is_false_with_no_other_confirmed_booking(fake_db):
    fake_db.tables["venue_bookings"] = [_booking(status="pending")]

    booking = service_module.get_booking("booking-1")

    assert booking["conflict"] is False


def test_get_booking_conflict_is_true_when_another_confirmed_booking_overlaps(fake_db):
    fake_db.tables["venue_bookings"] = [
        _booking("booking-1", status="pending"),
        _booking(
            "booking-2",
            status="confirmed",
            booking_start="2026-11-01T10:00:00+08:00",
            booking_end="2026-11-01T20:00:00+08:00",
        ),
    ]

    booking = service_module.get_booking("booking-1")

    assert booking["conflict"] is True


def test_get_booking_conflict_ignores_other_pending_bookings(fake_db):
    """Narrow guard, not the full Conflict Detection story -- a pending
    booking overlapping another pending one is NOT a conflict here."""
    fake_db.tables["venue_bookings"] = [
        _booking("booking-1", status="pending"),
        _booking(
            "booking-2",
            status="pending",
            booking_start="2026-11-01T10:00:00+08:00",
            booking_end="2026-11-01T20:00:00+08:00",
        ),
    ]

    booking = service_module.get_booking("booking-1")

    assert booking["conflict"] is False


def test_get_booking_conflict_excludes_itself(fake_db):
    """A booking that is ITSELF confirmed must not be reported as
    conflicting with its own row."""
    fake_db.tables["venue_bookings"] = [_booking("booking-1", status="confirmed")]

    booking = service_module.get_booking("booking-1")

    assert booking["conflict"] is False


# -- get_booking / list_bookings_for_event: rejection reason ------------------
# Approval AC2 ("the Coordinator can view it") -- the reason itself lives
# only in venue_booking_status_log (reject_booking's own insert), never
# on the venue_bookings row, so both read paths must join it in.


def test_get_booking_attaches_the_latest_rejection_reason(fake_db):
    fake_db.tables["venue_bookings"] = [_booking("booking-1", status="rejected")]
    fake_db.tables["venue_booking_status_log"] = [
        {
            "booking_id": "booking-1",
            "to_status": "rejected",
            "reason": "Too small for this event.",
            "changed_at": "2026-10-01T09:00:00+00:00",
        },
    ]

    booking = service_module.get_booking("booking-1")

    assert booking["rejection"]["reason"] == "Too small for this event."


def test_get_booking_rejection_is_the_most_recent_one(fake_db):
    """A booking rejected, then rejected again on a later request, shows
    the reason that applies NOW, not the stale first one."""
    fake_db.tables["venue_bookings"] = [_booking("booking-1", status="rejected")]
    fake_db.tables["venue_booking_status_log"] = [
        {"booking_id": "booking-1", "to_status": "rejected", "reason": "First reason.",
         "changed_at": "2026-10-01T09:00:00+00:00"},
        {"booking_id": "booking-1", "to_status": "rejected", "reason": "Second, latest reason.",
         "changed_at": "2026-10-03T09:00:00+00:00"},
    ]

    booking = service_module.get_booking("booking-1")

    assert booking["rejection"]["reason"] == "Second, latest reason."


def test_get_booking_has_no_rejection_field_when_not_rejected(fake_db):
    fake_db.tables["venue_bookings"] = [_booking("booking-1", status="pending")]

    booking = service_module.get_booking("booking-1")

    assert "rejection" not in booking


def test_list_bookings_for_event_attaches_rejection_reasons_too(fake_db):
    fake_db.tables["venue_bookings"] = [
        _booking("rejected-one", status="rejected"),
        _booking("still-pending", status="pending"),
    ]
    fake_db.tables["venue_booking_status_log"] = [
        {"booking_id": "rejected-one", "to_status": "rejected", "reason": "Dates clash.",
         "changed_at": "2026-10-01T09:00:00+00:00"},
    ]

    bookings = service_module.list_bookings_for_event("event-1")
    by_id = {b["id"]: b for b in bookings}

    assert by_id["rejected-one"]["rejection"]["reason"] == "Dates clash."
    assert "rejection" not in by_id["still-pending"]


# -- list_bookings_for_event ---------------------------------------------------


def test_list_bookings_for_event_newest_first(fake_db):
    fake_db.tables["venue_bookings"] = [
        _booking("old", created_at="2026-10-01T00:00:00+00:00"),
        _booking("new", created_at="2026-10-05T00:00:00+00:00"),
    ]

    bookings = service_module.list_bookings_for_event("event-1")

    assert [b["id"] for b in bookings] == ["new", "old"]


# -- list_bookings: role scoping ----------------------------------------------


def test_list_bookings_scopes_coordinator_to_their_own_requests(fake_db):
    fake_db.tables["venue_bookings"] = [
        _booking("mine", requested_by="coord-1"),
        _booking("theirs", requested_by="coord-2"),
    ]

    bookings = service_module.list_bookings(make_user(["event_coordinator"], user_id="coord-1"))

    assert [b["id"] for b in bookings] == ["mine"]


def test_list_bookings_is_unfiltered_for_venue_staff(fake_db):
    fake_db.tables["venue_bookings"] = [
        _booking("a", requested_by="coord-1"),
        _booking("b", requested_by="coord-2"),
    ]

    bookings = service_module.list_bookings(make_user(["venue_staff"], user_id="staff-1"))

    assert {b["id"] for b in bookings} == {"a", "b"}


def test_list_bookings_for_a_user_with_both_roles_is_unfiltered(fake_db):
    """venue_staff's unfiltered view is the wider of the two -- correct
    for a dual-role caller too, same union stance as
    list_event_requests."""
    fake_db.tables["venue_bookings"] = [
        _booking("a", requested_by="coord-1"),
        _booking("b", requested_by="coord-2"),
    ]

    bookings = service_module.list_bookings(make_user(["event_coordinator", "venue_staff"], user_id="coord-1"))

    assert {b["id"] for b in bookings} == {"a", "b"}


def test_list_bookings_status_filter_narrows_within_role_scope(fake_db):
    """The status filter applies on top of the role scoping -- it never
    widens what the caller can see."""
    fake_db.tables["venue_bookings"] = [
        _booking("mine-pending", requested_by="coord-1", status="pending"),
        _booking("mine-confirmed", requested_by="coord-1", status="confirmed"),
        _booking("theirs-pending", requested_by="coord-2", status="pending"),
    ]

    bookings = service_module.list_bookings(make_user(["event_coordinator"], user_id="coord-1"), "pending")

    assert [b["id"] for b in bookings] == ["mine-pending"]


def test_list_bookings_rejects_an_unknown_status_filter(fake_db):
    with pytest.raises(ValidationError, match="status must be one of"):
        service_module.list_bookings(make_user(["venue_staff"]), "archived")


def test_list_bookings_for_a_user_without_a_listing_role_is_empty_and_never_queries(fake_db):
    fake_db.tables["venue_bookings"] = [_booking()]

    assert service_module.list_bookings(make_user(["attendee"])) == []
    assert fake_db.calls == []


# -- confirm_booking -----------------------------------------------------------


def test_confirm_booking_sets_status_and_logs_the_decision(fake_db):
    fake_db.tables["venue_bookings"] = [_booking(status="pending")]
    booking = SimpleNamespace(**_booking(status="pending"))

    result = service_module.confirm_booking("booking-1", booking, "staff-1")

    assert result["status"] == "confirmed"
    assert len(fake_db.inserts) == 1
    log_table, log_row = fake_db.inserts[0]
    assert log_table == "venue_booking_status_log"
    assert {k: v for k, v in log_row.items() if k != "id"} == {
        "booking_id": "booking-1",
        "from_status": "pending",
        "to_status": "confirmed",
        "changed_by": "staff-1",
        "reason": None,
    }


def test_confirm_booking_blocked_by_an_overlapping_confirmed_booking(fake_db):
    fake_db.tables["venue_bookings"] = [
        _booking("booking-1", status="pending"),
        _booking(
            "booking-2",
            status="confirmed",
            booking_start="2026-11-01T10:00:00+08:00",
            booking_end="2026-11-01T20:00:00+08:00",
        ),
    ]
    booking = SimpleNamespace(**_booking("booking-1", status="pending"))

    with pytest.raises(ValidationError):
        service_module.confirm_booking("booking-1", booking, "staff-1")

    assert fake_db.tables["venue_bookings"][0]["status"] == "pending"
    assert fake_db.inserts == []


def test_confirm_booking_not_blocked_by_a_non_overlapping_confirmed_booking(fake_db):
    fake_db.tables["venue_bookings"] = [
        _booking("booking-1", status="pending"),
        _booking(
            "booking-2",
            status="confirmed",
            booking_start="2026-11-02T08:30:00+08:00",
            booking_end="2026-11-02T17:30:00+08:00",
        ),
    ]
    booking = SimpleNamespace(**_booking("booking-1", status="pending"))

    result = service_module.confirm_booking("booking-1", booking, "staff-1")

    assert result["status"] == "confirmed"


def test_second_decision_is_refused_once_no_longer_pending(fake_db):
    """Pending-only race guard, same idiom as
    event_service's own double-decision test: a second decision call
    against a booking that's already been decided finds no matching row
    and is refused."""
    fake_db.tables["venue_bookings"] = [_booking(status="pending")]
    booking = SimpleNamespace(**_booking(status="pending"))
    service_module.confirm_booking("booking-1", booking, "staff-1")

    with pytest.raises(ValidationError):
        service_module.reject_booking("booking-1", booking, "staff-1", "changed my mind")

    assert fake_db.tables["venue_bookings"][0]["status"] == "confirmed"
    assert len(fake_db.inserts) == 1


# -- reject_booking -------------------------------------------------------------


def test_reject_booking_requires_a_reason_and_leaves_status_unchanged(fake_db):
    fake_db.tables["venue_bookings"] = [_booking(status="pending")]
    booking = SimpleNamespace(**_booking(status="pending"))

    with pytest.raises(ValidationError):
        service_module.reject_booking("booking-1", booking, "staff-1", None)

    assert fake_db.tables["venue_bookings"][0]["status"] == "pending"
    assert fake_db.inserts == []


@pytest.mark.parametrize("reason", [None, "", "   ", 42])
def test_reject_booking_rejects_every_blank_or_non_string_reason(fake_db, reason):
    fake_db.tables["venue_bookings"] = [_booking(status="pending")]
    booking = SimpleNamespace(**_booking(status="pending"))

    with pytest.raises(ValidationError):
        service_module.reject_booking("booking-1", booking, "staff-1", reason)


def test_reject_booking_sets_status_and_logs_the_trimmed_reason(fake_db):
    fake_db.tables["venue_bookings"] = [_booking(status="pending")]
    booking = SimpleNamespace(**_booking(status="pending"))

    result = service_module.reject_booking("booking-1", booking, "staff-1", "  Venue too small  ")

    assert result["status"] == "rejected"
    assert fake_db.inserts[0][1]["reason"] == "Venue too small"
    assert fake_db.inserts[0][1]["to_status"] == "rejected"
