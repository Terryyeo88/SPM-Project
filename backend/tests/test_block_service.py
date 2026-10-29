"""
Unit tests for app.venues.block_service -- Venue Becomes Unavailable
After Booking (Josiah, Sprint 3).
"""

from __future__ import annotations

import pytest

import app.venues.block_service as service_module
import app.venues.booking_release as release_module
from app.shared.errors import NotFoundError, ValidationError


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
        if self.ordering:
            column, desc = self.ordering
            data.sort(key=lambda row: row.get(column) or "", reverse=desc)
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
    monkeypatch.setattr(service_module, "supabase", db)
    # create_venue_block's release step goes through
    # app.venues.booking_release, and its own get_venue call goes through
    # app.venues.venue_service -- both hold their own module-level
    # `supabase` reference, same fake.
    monkeypatch.setattr(release_module, "supabase", db)
    import app.venues.venue_service as venue_service_module

    monkeypatch.setattr(venue_service_module, "supabase", db)
    return db


def _booking(booking_id="booking-1", venue_id="venue-1", event_id="event-1", status="confirmed", **overrides):
    row = {
        "id": booking_id,
        "event_id": event_id,
        "venue_id": venue_id,
        "status": status,
        "booking_start": "2026-11-01T08:30:00+08:00",
        "booking_end": "2026-11-01T17:30:00+08:00",
        "hold_minutes": 60,
        "confirmed_at": None,
    }
    row.update(overrides)
    return row


def _block_body(**overrides):
    body = {
        "reason": "maintenance",
        "note": "Re-flooring",
        "block_start": "2026-11-01T00:00:00+08:00",
        "block_end": "2026-11-02T00:00:00+08:00",
    }
    body.update(overrides)
    return body


# -- _block_fields_from validation ----------------------------------------


def test_create_venue_block_rejects_a_non_object_body(fake_db):
    fake_db.tables["venues"] = [{"id": "venue-1"}]
    with pytest.raises(ValidationError):
        service_module.create_venue_block("venue-1", ["not", "a", "dict"], "staff-1")


def test_create_venue_block_rejects_an_unknown_field(fake_db):
    fake_db.tables["venues"] = [{"id": "venue-1"}]
    with pytest.raises(ValidationError, match="Unknown venue block fields"):
        service_module.create_venue_block("venue-1", _block_body(extra="field"), "staff-1")


def test_create_venue_block_rejects_an_invalid_reason(fake_db):
    fake_db.tables["venues"] = [{"id": "venue-1"}]
    with pytest.raises(ValidationError, match="reason must be one of"):
        service_module.create_venue_block("venue-1", _block_body(reason="not_a_real_reason"), "staff-1")


def test_create_venue_block_rejects_end_before_start(fake_db):
    fake_db.tables["venues"] = [{"id": "venue-1"}]
    with pytest.raises(ValidationError, match="block_end must be after block_start"):
        body = _block_body(block_start="2026-11-02T00:00:00+08:00", block_end="2026-11-01T00:00:00+08:00")
        service_module.create_venue_block("venue-1", body, "staff-1")


@pytest.mark.parametrize("field", ["block_start", "block_end"])
@pytest.mark.parametrize("value", [None, "", 42])
def test_create_venue_block_rejects_a_missing_or_non_string_timestamp(fake_db, field, value):
    fake_db.tables["venues"] = [{"id": "venue-1"}]
    with pytest.raises(ValidationError, match="ISO timestamps"):
        service_module.create_venue_block("venue-1", _block_body(**{field: value}), "staff-1")


@pytest.mark.parametrize("field", ["block_start", "block_end"])
def test_create_venue_block_rejects_a_malformed_timestamp(fake_db, field):
    fake_db.tables["venues"] = [{"id": "venue-1"}]
    with pytest.raises(ValidationError, match="not a valid timestamp"):
        service_module.create_venue_block("venue-1", _block_body(**{field: "not-a-timestamp"}), "staff-1")


def test_create_venue_block_rejects_a_non_string_note(fake_db):
    fake_db.tables["venues"] = [{"id": "venue-1"}]
    with pytest.raises(ValidationError, match="note must be a string"):
        service_module.create_venue_block("venue-1", _block_body(note=42), "staff-1")


def test_create_venue_block_raises_not_found_for_an_unknown_venue(fake_db):
    with pytest.raises(NotFoundError):
        service_module.create_venue_block("does-not-exist", _block_body(), "staff-1")


# -- create_venue_block: happy path + release side effect -----------------


def test_create_venue_block_inserts_the_block(fake_db):
    fake_db.tables["venues"] = [{"id": "venue-1"}]

    result = service_module.create_venue_block("venue-1", _block_body(), "staff-1")

    assert result["block"]["venue_id"] == "venue-1"
    assert result["block"]["reason"] == "maintenance"
    assert result["block"]["created_by"] == "staff-1"
    assert result["released_bookings"] == []


def test_create_venue_block_releases_overlapping_confirmed_bookings_and_reports_them(fake_db):
    fake_db.tables["venues"] = [{"id": "venue-1"}]
    fake_db.tables["venue_bookings"] = [_booking("booking-1", status="confirmed")]

    result = service_module.create_venue_block("venue-1", _block_body(), "staff-1")

    assert result["released_bookings"] == [{"booking_id": "booking-1", "event_id": "event-1"}]
    assert fake_db.tables["venue_bookings"][0]["status"] == "released"


def test_create_venue_block_does_not_touch_a_non_overlapping_confirmed_booking(fake_db):
    fake_db.tables["venues"] = [{"id": "venue-1"}]
    fake_db.tables["venue_bookings"] = [
        _booking(
            "booking-1", status="confirmed",
            booking_start="2026-11-10T08:30:00+08:00", booking_end="2026-11-10T17:30:00+08:00",
        )
    ]

    result = service_module.create_venue_block("venue-1", _block_body(), "staff-1")

    assert result["released_bookings"] == []
    assert fake_db.tables["venue_bookings"][0]["status"] == "confirmed"


def test_create_venue_block_does_not_touch_an_overlapping_pending_booking(fake_db):
    """Decided scope: a pending request is left alone when a block is
    created -- only guarded at confirm time (booking_service._blocked_period_exists)."""
    fake_db.tables["venues"] = [{"id": "venue-1"}]
    fake_db.tables["venue_bookings"] = [_booking("booking-1", status="pending")]

    result = service_module.create_venue_block("venue-1", _block_body(), "staff-1")

    assert result["released_bookings"] == []
    assert fake_db.tables["venue_bookings"][0]["status"] == "pending"


def test_create_venue_block_does_not_cancel_the_event(fake_db):
    """AC: the existing event must NOT automatically be cancelled."""
    fake_db.tables["venues"] = [{"id": "venue-1"}]
    fake_db.tables["venue_bookings"] = [_booking("booking-1", status="confirmed")]

    service_module.create_venue_block("venue-1", _block_body(), "staff-1")

    assert not any(call["table"] == "events" and call["op"] == "update" for call in fake_db.calls)


# -- list_venue_blocks ------------------------------------------------------


def test_list_venue_blocks_newest_first(fake_db):
    fake_db.tables["venues"] = [{"id": "venue-1"}]
    fake_db.tables["venue_blocks"] = [
        {"id": "old", "venue_id": "venue-1", "block_start": "2026-11-01T00:00:00+08:00"},
        {"id": "new", "venue_id": "venue-1", "block_start": "2026-11-05T00:00:00+08:00"},
    ]

    blocks = service_module.list_venue_blocks("venue-1")

    assert [b["id"] for b in blocks] == ["new", "old"]


def test_list_venue_blocks_raises_not_found_for_an_unknown_venue(fake_db):
    with pytest.raises(NotFoundError):
        service_module.list_venue_blocks("does-not-exist")
