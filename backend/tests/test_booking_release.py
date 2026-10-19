"""
Unit tests for app.venues.booking_release -- the shared mechanism behind
all three "take a confirmed venue booking off blocking status" triggers
(event cancelled, tentative hold expired, venue blocked), Josiah, Sprint 3.

Unit-level, local fake client, same shape as test_booking_service.py's
own (duplicated rather than imported -- a plain local fake per test file
is this codebase's own established precedent, see that file's module
docstring).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

import app.venues.booking_release as release_module


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
        self.db.calls.append({"table": self.table, "op": self.op})

        if self.op == "insert":
            new_rows = self.payload if isinstance(self.payload, list) else [self.payload]
            created = []
            for row in new_rows:
                stored = {"id": self.db.new_id(), **row}
                rows.append(stored)
                created.append(dict(stored))
            self.db.inserts.extend((self.table, row) for row in created)
            return type("Result", (), {"data": created})()

        matched = [row for row in rows if self._matches(row)]
        if self.op == "update":
            for row in matched:
                row.update(self.payload)
        data = [dict(row) for row in matched]
        if self.want_maybe_single:
            return type("Result", (), {"data": data[0] if data else None})() if data else None
        return type("Result", (), {"data": data})()


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
    monkeypatch.setattr(release_module, "supabase", db)
    return db


def _booking(booking_id="booking-1", event_id="event-1", status="confirmed", **overrides):
    row = {
        "id": booking_id,
        "event_id": event_id,
        "venue_id": "venue-1",
        "status": status,
        "booking_start": "2026-11-01T08:30:00+08:00",
        "booking_end": "2026-11-01T17:30:00+08:00",
        "hold_minutes": 60,
        "confirmed_at": None,
    }
    row.update(overrides)
    return row


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# -- release_booking -----------------------------------------------------


def test_release_booking_moves_confirmed_to_released_and_logs_it(fake_db):
    fake_db.tables["venue_bookings"] = [_booking(status="confirmed")]

    result = release_module.release_booking("booking-1", _booking(status="confirmed"), "Event cancelled", "user-1")

    assert result["status"] == "released"
    log_inserts = [row for table, row in fake_db.inserts if table == "venue_booking_status_log"]
    assert len(log_inserts) == 1
    assert {k: v for k, v in log_inserts[0].items() if k != "id"} == {
        "booking_id": "booking-1",
        "from_status": "confirmed",
        "to_status": "released",
        "changed_by": "user-1",
        "reason": "Event cancelled",
    }


def test_release_booking_changed_by_none_for_a_system_initiated_release(fake_db):
    fake_db.tables["venue_bookings"] = [_booking(status="confirmed")]

    release_module.release_booking("booking-1", _booking(status="confirmed"), "Tentative hold expired.")

    log_inserts = [row for table, row in fake_db.inserts if table == "venue_booking_status_log"]
    assert log_inserts[0]["changed_by"] is None


def test_release_booking_is_idempotent_and_silent_on_a_lost_race(fake_db):
    """Unlike _decide_booking's strict-and-loud double-decision guard,
    this is a SYSTEM repair -- two readers racing to release the same
    stale row must both succeed quietly, not error."""
    fake_db.tables["venue_bookings"] = [_booking(status="released")]  # already released

    result = release_module.release_booking("booking-1", _booking(status="confirmed"), "Event cancelled")

    assert result["status"] == "released"
    assert fake_db.inserts == []  # no duplicate log entry for a no-op


# -- release_bookings_for_event (plural-safe) -----------------------------


def test_release_bookings_for_event_releases_every_confirmed_booking(fake_db):
    """PLURAL-SAFE: every confirmed booking for the event, not "the" one."""
    fake_db.tables["venue_bookings"] = [
        _booking("booking-1", event_id="event-1", status="confirmed"),
        _booking("booking-2", event_id="event-1", status="confirmed"),
        _booking("booking-3", event_id="event-1", status="rejected"),  # untouched
        _booking("booking-4", event_id="event-2", status="confirmed"),  # different event, untouched
    ]

    released = release_module.release_bookings_for_event("event-1", "Event cancelled", "user-1")

    assert {b["id"] for b in released} == {"booking-1", "booking-2"}
    statuses = {row["id"]: row["status"] for row in fake_db.tables["venue_bookings"]}
    assert statuses["booking-1"] == "released"
    assert statuses["booking-2"] == "released"
    assert statuses["booking-3"] == "rejected"
    assert statuses["booking-4"] == "confirmed"


def test_release_bookings_for_event_is_a_noop_with_no_confirmed_bookings(fake_db):
    fake_db.tables["venue_bookings"] = [_booking("booking-1", event_id="event-1", status="pending")]

    released = release_module.release_bookings_for_event("event-1", "Event cancelled")

    assert released == []


# -- release_bookings_overlapping_block ------------------------------------


def test_release_bookings_overlapping_block_releases_only_overlapping_confirmed_bookings(fake_db):
    fake_db.tables["venue_bookings"] = [
        _booking(
            "overlapping", status="confirmed",
            booking_start="2026-11-01T08:30:00+08:00", booking_end="2026-11-01T17:30:00+08:00",
        ),
        _booking(
            "not-overlapping", status="confirmed",
            booking_start="2026-11-05T08:30:00+08:00", booking_end="2026-11-05T17:30:00+08:00",
        ),
        _booking(
            "pending-overlap", status="pending",
            booking_start="2026-11-01T08:30:00+08:00", booking_end="2026-11-01T17:30:00+08:00",
        ),
    ]
    block_start = datetime.fromisoformat("2026-11-01T00:00:00+08:00")
    block_end = datetime.fromisoformat("2026-11-02T00:00:00+08:00")

    released = release_module.release_bookings_overlapping_block(
        "venue-1", block_start, block_end, "Venue blocked: maintenance."
    )

    assert [b["id"] for b in released] == ["overlapping"]
    statuses = {row["id"]: row["status"] for row in fake_db.tables["venue_bookings"]}
    assert statuses["overlapping"] == "released"
    assert statuses["not-overlapping"] == "confirmed"
    # Pending bookings are deliberately left untouched when a block is
    # created -- see block_service.create_venue_block's own docstring.
    assert statuses["pending-overlap"] == "pending"


# -- release_expired_hold --------------------------------------------------


def test_release_expired_hold_leaves_a_not_yet_expired_booking_alone(fake_db):
    confirmed_at = _iso(datetime.now(UTC) - timedelta(minutes=10))
    booking = _booking(status="confirmed", confirmed_at=confirmed_at, hold_minutes=60)

    result = release_module.release_expired_hold(booking, event_status="planning")

    assert result["status"] == "confirmed"


def test_release_expired_hold_releases_an_expired_booking_whose_event_is_not_yet_confirmed(fake_db):
    fake_db.tables["venue_bookings"] = [_booking(status="confirmed")]
    confirmed_at = _iso(datetime.now(UTC) - timedelta(minutes=120))
    booking = _booking(status="confirmed", confirmed_at=confirmed_at, hold_minutes=60)

    result = release_module.release_expired_hold(booking, event_status="planning")

    assert result["status"] == "released"


@pytest.mark.parametrize("graduated_status", ["confirmed", "completed"])
def test_release_expired_hold_never_revisits_a_graduated_event(fake_db, graduated_status):
    """The single most load-bearing guard in this module: once the event
    itself reaches confirmed/completed, elapsed hold time is meaningless
    and must never be re-applied, however long ago the booking was
    confirmed."""
    confirmed_at = _iso(datetime.now(UTC) - timedelta(days=30))
    booking = _booking(status="confirmed", confirmed_at=confirmed_at, hold_minutes=60)

    result = release_module.release_expired_hold(booking, event_status=graduated_status)

    assert result["status"] == "confirmed"


def test_release_expired_hold_ignores_a_non_confirmed_booking(fake_db):
    booking = _booking(status="pending", confirmed_at=None, hold_minutes=None)

    result = release_module.release_expired_hold(booking)

    assert result["status"] == "pending"


def test_release_expired_hold_ignores_a_confirmed_booking_with_no_confirmed_at(fake_db):
    """Pre-existing rows backfilled without a recoverable confirmed_at
    (see 20261019010000_venue_settings_and_hold.sql) must not be treated
    as perpetually expired."""
    booking = _booking(status="confirmed", confirmed_at=None, hold_minutes=60)

    result = release_module.release_expired_hold(booking)

    assert result["status"] == "confirmed"


def test_release_expired_hold_fetches_event_status_when_not_supplied(fake_db):
    fake_db.tables["events"] = [{"id": "event-1", "status": "planning"}]
    fake_db.tables["venue_bookings"] = [_booking(status="confirmed")]
    confirmed_at = _iso(datetime.now(UTC) - timedelta(minutes=120))
    booking = _booking(status="confirmed", confirmed_at=confirmed_at, hold_minutes=60)

    result = release_module.release_expired_hold(booking)

    assert result["status"] == "released"


# -- touch_expired_holds (batch) -------------------------------------------


def test_touch_expired_holds_batches_event_status_lookups(fake_db):
    """Confirms the batch form doesn't do N+1: one events query for every
    DISTINCT event_id among confirmed rows, not one per row."""
    fake_db.tables["events"] = [
        {"id": "event-1", "status": "planning"},
        {"id": "event-2", "status": "confirmed"},
    ]
    fake_db.tables["venue_bookings"] = [
        _booking("booking-1", event_id="event-1", status="confirmed"),
        _booking("booking-2", event_id="event-1", status="confirmed"),
        _booking("booking-3", event_id="event-2", status="confirmed"),
    ]
    old_confirmed_at = _iso(datetime.now(UTC) - timedelta(minutes=120))
    bookings = [
        _booking("booking-1", event_id="event-1", status="confirmed", confirmed_at=old_confirmed_at, hold_minutes=60),
        _booking("booking-2", event_id="event-1", status="confirmed", confirmed_at=old_confirmed_at, hold_minutes=60),
        _booking("booking-3", event_id="event-2", status="confirmed", confirmed_at=old_confirmed_at, hold_minutes=60),
    ]

    results = release_module.touch_expired_holds(bookings)

    events_queries = [call for call in fake_db.calls if call["table"] == "events"]
    assert len(events_queries) == 1  # one batched query, not three
    by_id = {b["id"]: b for b in results}
    assert by_id["booking-1"]["status"] == "released"  # event-1 still planning -> expired, released
    assert by_id["booking-2"]["status"] == "released"
    assert by_id["booking-3"]["status"] == "confirmed"  # event-2 already confirmed -> graduated, untouched


def test_touch_expired_holds_skips_the_events_query_when_nothing_is_confirmed(fake_db):
    bookings = [_booking("booking-1", status="pending"), _booking("booking-2", status="rejected")]

    results = release_module.touch_expired_holds(bookings)

    assert results == bookings
    assert fake_db.calls == []
