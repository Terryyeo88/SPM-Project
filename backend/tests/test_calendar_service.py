"""
Unit tests for app.venues.calendar_service -- View Venue Availability
Calendar (Nawaz, Sprint 2, IS-11).

Local fake client scoped to just the two tables this service reads
(venue_blocks, venue_bookings), same "write a fake scoped to what THIS
service needs" precedent as test_booking_service.py's own module
docstring explains. venue_bookings rows are stored WITH their embedded
"events" dict already attached (as PostgREST's own `events(name,
status)` embed would return it) rather than simulating a join -- this
tests calendar_service's state-derivation logic, not PostgREST's embed
mechanics.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

import app.venues.booking_release as release_module
import app.venues.calendar_service as service_module
from app.shared.errors import ValidationError


class _FakeTable:
    def __init__(self, db, rows):
        self._db = db
        self._rows = rows
        self._filters = []
        self._in_filters = []
        self._op, self._payload, self._want_maybe_single = None, None, False

    def select(self, *_a, **_k):
        return self

    def eq(self, column, value):
        self._filters.append((column, value))
        return self

    def in_(self, column, values):
        self._in_filters.append((column, tuple(values)))
        return self

    def update(self, payload):
        self._op, self._payload = "update", payload
        return self

    def insert(self, payload):
        self._op, self._payload = "insert", payload
        return self

    def maybe_single(self):
        self._want_maybe_single = True
        return self

    def _matches(self, row):
        for column, value in self._filters:
            if row.get(column) != value:
                return False
        for column, values in self._in_filters:
            if row.get(column) not in values:
                return False
        return True

    def execute(self):
        if self._op == "insert":
            new_rows = self._payload if isinstance(self._payload, list) else [self._payload]
            created = [{"id": self._db.new_id(), **row} for row in new_rows]
            self._rows.extend(created)
            return SimpleNamespace(data=created)

        matched = [row for row in self._rows if self._matches(row)]
        if self._op == "update":
            for row in matched:
                row.update(self._payload)
        data = [dict(row) for row in matched]
        if self._want_maybe_single:
            return SimpleNamespace(data=data[0]) if data else None
        return SimpleNamespace(data=data)


class _FakeSupabase:
    def __init__(self, venue_blocks=None, venue_bookings=None):
        self._tables = {
            "venue_blocks": venue_blocks or [],
            "venue_bookings": venue_bookings or [],
        }
        self._next_id = 0

    def table(self, name):
        self._tables.setdefault(name, [])
        return _FakeTable(self, self._tables[name])

    def new_id(self):
        self._next_id += 1
        return f"row-{self._next_id}"


_VENUE = {
    "id": "venue-1",
    "name": "Grand Ballroom",
    "operating_hours_start": "07:00",
    "operating_hours_end": "23:00",
}


def _patch(monkeypatch, fake_supabase, venue=None):
    monkeypatch.setattr(service_module, "supabase", fake_supabase)
    monkeypatch.setattr(service_module, "get_venue", lambda venue_id: venue or _VENUE)
    # release_expired_hold's own writes (the status update + audit log
    # insert) go through app.venues.booking_release's own module-level
    # `supabase` reference, not this module's -- same fake.
    monkeypatch.setattr(release_module, "supabase", fake_supabase)


def test_block_within_range_is_returned_as_blocked(monkeypatch):
    blocks = [
        {
            "id": "block-1",
            "venue_id": "venue-1",
            "reason": "maintenance",
            "note": "Deep clean",
            "block_start": "2026-12-20T00:00:00+00:00",
            "block_end": "2026-12-22T00:00:00+00:00",
        }
    ]
    _patch(monkeypatch, _FakeSupabase(venue_blocks=blocks))

    result = service_module.get_venue_calendar("venue-1", "2026-12-01", "2026-12-31")

    assert len(result["entries"]) == 1
    entry = result["entries"][0]
    assert entry["type"] == "block"
    assert entry["state"] == "blocked"
    assert entry["reason"] == "maintenance"
    assert entry["note"] == "Deep clean"


def test_block_outside_range_is_excluded(monkeypatch):
    blocks = [
        {
            "id": "block-1",
            "venue_id": "venue-1",
            "reason": "maintenance",
            "note": None,
            "block_start": "2026-01-01T00:00:00+00:00",
            "block_end": "2026-01-02T00:00:00+00:00",
        }
    ]
    _patch(monkeypatch, _FakeSupabase(venue_blocks=blocks))

    result = service_module.get_venue_calendar("venue-1", "2026-12-01", "2026-12-31")

    assert result["entries"] == []


def test_confirmed_booking_with_unconfirmed_event_is_tentatively_held(monkeypatch):
    bookings = [
        {
            "id": "booking-1",
            "event_id": "event-1",
            "venue_id": "venue-1",
            "status": "confirmed",
            "booking_start": "2026-12-10T09:00:00+00:00",
            "booking_end": "2026-12-10T13:00:00+00:00",
            "events": {"name": "Product Launch Gala", "status": "planning"},
        }
    ]
    _patch(monkeypatch, _FakeSupabase(venue_bookings=bookings))

    result = service_module.get_venue_calendar("venue-1", "2026-12-01", "2026-12-31")

    assert len(result["entries"]) == 1
    entry = result["entries"][0]
    assert entry["type"] == "booking"
    assert entry["state"] == "tentatively_held"
    assert entry["event_name"] == "Product Launch Gala"
    assert entry["event_id"] == "event-1"


def test_confirmed_booking_with_confirmed_event_is_confirmed(monkeypatch):
    bookings = [
        {
            "id": "booking-1",
            "event_id": "event-1",
            "venue_id": "venue-1",
            "status": "confirmed",
            "booking_start": "2026-12-10T09:00:00+00:00",
            "booking_end": "2026-12-10T13:00:00+00:00",
            "events": {"name": "Product Launch Gala", "status": "confirmed"},
        }
    ]
    _patch(monkeypatch, _FakeSupabase(venue_bookings=bookings))

    result = service_module.get_venue_calendar("venue-1", "2026-12-01", "2026-12-31")

    assert result["entries"][0]["state"] == "confirmed"


def test_pending_booking_is_not_an_entry(monkeypatch):
    """A pending booking hasn't been approved by Venue Staff yet --
    nothing is holding the venue, so it must not render as any
    non-"available" state (see this module's own docstring)."""
    bookings = [
        {
            "id": "booking-1",
            "event_id": "event-1",
            "venue_id": "venue-1",
            "status": "pending",
            "booking_start": "2026-12-10T09:00:00+00:00",
            "booking_end": "2026-12-10T13:00:00+00:00",
            "events": {"name": "Product Launch Gala", "status": "approved"},
        }
    ]
    _patch(monkeypatch, _FakeSupabase(venue_bookings=bookings))

    result = service_module.get_venue_calendar("venue-1", "2026-12-01", "2026-12-31")

    assert result["entries"] == []


def test_booking_does_not_expose_full_event_record(monkeypatch):
    """AC4: "each booked entry identifies the event... without exposing
    internal planning details to users not entitled to see them" -- the
    returned entry must carry only event_id/event_name, nothing else
    from the event row."""
    bookings = [
        {
            "id": "booking-1",
            "event_id": "event-1",
            "venue_id": "venue-1",
            "status": "confirmed",
            "booking_start": "2026-12-10T09:00:00+00:00",
            "booking_end": "2026-12-10T13:00:00+00:00",
            "events": {"name": "Product Launch Gala", "status": "confirmed"},
        }
    ]
    _patch(monkeypatch, _FakeSupabase(venue_bookings=bookings))

    result = service_module.get_venue_calendar("venue-1", "2026-12-01", "2026-12-31")

    assert set(result["entries"][0].keys()) == {"type", "state", "start", "end", "event_id", "event_name"}


def test_response_includes_venue_profile_and_operating_hours(monkeypatch):
    _patch(monkeypatch, _FakeSupabase())

    result = service_module.get_venue_calendar("venue-1", "2026-12-01", "2026-12-31")

    assert result["venue"] == {
        "id": "venue-1",
        "name": "Grand Ballroom",
        "operating_hours_start": "07:00",
        "operating_hours_end": "23:00",
    }


def test_rejects_end_before_start(monkeypatch):
    _patch(monkeypatch, _FakeSupabase())

    with pytest.raises(ValidationError):
        service_module.get_venue_calendar("venue-1", "2026-12-31", "2026-12-01")


def test_rejects_malformed_date(monkeypatch):
    _patch(monkeypatch, _FakeSupabase())

    with pytest.raises(ValidationError):
        service_module.get_venue_calendar("venue-1", "not-a-date", "2026-12-31")


# -- Sprint 3: an expired tentative hold emits NO entry -------------------


def test_expired_hold_on_an_unconfirmed_event_emits_no_entry(monkeypatch):
    """The AC: an expired hold must never read as a live booking -- it
    disappears from the calendar entirely, which IS "the venue becomes
    available again"."""
    old_confirmed_at = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
    bookings = [
        {
            "id": "booking-1",
            "event_id": "event-1",
            "venue_id": "venue-1",
            "status": "confirmed",
            "booking_start": "2026-12-10T09:00:00+00:00",
            "booking_end": "2026-12-10T13:00:00+00:00",
            "confirmed_at": old_confirmed_at,
            "hold_minutes": 60,
            "events": {"name": "Product Launch Gala", "status": "planning"},
        }
    ]
    fake = _FakeSupabase(venue_bookings=bookings)
    _patch(monkeypatch, fake)

    result = service_module.get_venue_calendar("venue-1", "2026-12-01", "2026-12-31")

    assert result["entries"] == []
    assert fake._tables["venue_bookings"][0]["status"] == "released"


def test_a_long_confirmed_event_s_booking_is_never_re_expired(monkeypatch):
    """The guard this whole mechanism depends on: once the EVENT reaches
    confirmed, elapsed hold time is meaningless, however long ago the
    booking was confirmed -- it must still show as a live "confirmed"
    entry, not vanish."""
    ancient_confirmed_at = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    bookings = [
        {
            "id": "booking-1",
            "event_id": "event-1",
            "venue_id": "venue-1",
            "status": "confirmed",
            "booking_start": "2026-12-10T09:00:00+00:00",
            "booking_end": "2026-12-10T13:00:00+00:00",
            "confirmed_at": ancient_confirmed_at,
            "hold_minutes": 60,
            "events": {"name": "Product Launch Gala", "status": "confirmed"},
        }
    ]
    fake = _FakeSupabase(venue_bookings=bookings)
    _patch(monkeypatch, fake)

    result = service_module.get_venue_calendar("venue-1", "2026-12-01", "2026-12-31")

    assert len(result["entries"]) == 1
    assert result["entries"][0]["state"] == "confirmed"
    assert fake._tables["venue_bookings"][0]["status"] == "confirmed"
