"""
IS-74: the calendar window is measured in Singapore days. Bookings and blocks
are given in UTC, as PostgREST returns them, at the instants where a Singapore
day and its UTC date disagree. No host-timezone dependence: every value here
carries an explicit offset, and the conversion uses a fixed one.

The frontend half of these same instants is
frontend/src/views/venues/VenueCalendarView.test.js.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

import app.venues.booking_release as release_module
import app.venues.calendar_service as service_module
from app.shared.calendar import CALENDAR_TIMEZONE, parse_calendar_range
from tests.fake_supabase import FakeSupabase

NOVEMBER = ("2026-11-01", "2026-11-30")
OCTOBER = ("2026-10-01", "2026-10-31")
FIRST_OF_NOVEMBER = ("2026-11-01", "2026-11-01")
LAST_OF_OCTOBER = ("2026-10-31", "2026-10-31")
LAST_OF_NOVEMBER = ("2026-11-30", "2026-11-30")
FIRST_OF_DECEMBER = ("2026-12-01", "2026-12-01")

LAST_DAY_2300 = ("2026-11-30T15:00:00+00:00", "2026-11-30T15:30:00+00:00")
FIRST_DAY_0030 = ("2026-10-31T16:30:00+00:00", "2026-10-31T17:30:00+00:00")
PREVIOUS_DAY_2300 = ("2026-10-31T15:00:00+00:00", "2026-10-31T15:30:00+00:00")
NEXT_DAY_0030 = ("2026-11-01T16:30:00+00:00", "2026-11-01T17:30:00+00:00")


def _venue_calendar(monkeypatch, spans, query) -> list[str]:
    """Event names `get_venue_calendar` returns for `query`, each span being
    (name, (start, end)) as a confirmed booking of a confirmed event."""
    fake = FakeSupabase()
    fake.tables["venue_bookings"] = [
        {
            "id": f"booking-{name}",
            "venue_id": "venue-1",
            "event_id": name,
            "booking_start": start,
            "booking_end": end,
            "status": "confirmed",
            "confirmed_at": "2026-10-01T00:00:00+00:00",
            "hold_minutes": None,
            "events": {"name": name, "status": "confirmed"},
        }
        for name, (start, end) in spans
    ]
    fake.tables["venue_blocks"] = []
    monkeypatch.setattr(service_module, "supabase", fake)
    monkeypatch.setattr(release_module, "supabase", fake)
    monkeypatch.setattr(service_module, "get_venue", lambda venue_id: {"id": venue_id, "name": "Grand Ballroom"})
    return [entry["event_name"] for entry in service_module.get_venue_calendar("venue-1", *query)["entries"]]


def test_the_calendar_timezone_is_utc_plus_8_every_day_of_the_year():
    """A fixed offset, so no season or host setting can move it."""
    for month in (1, 7):
        assert datetime(2026, month, 15, tzinfo=CALENDAR_TIMEZONE).utcoffset().total_seconds() == 8 * 3600


@pytest.mark.parametrize(
    "query, expected",
    [
        (NOVEMBER, ["last day 23:00"]),
        (LAST_OF_NOVEMBER, ["last day 23:00"]),
        (FIRST_OF_DECEMBER, []),
    ],
)
def test_a_2300_booking_on_the_last_day_is_in_that_month_and_day(monkeypatch, query, expected):
    assert _venue_calendar(monkeypatch, [("last day 23:00", LAST_DAY_2300)], query) == expected


@pytest.mark.parametrize(
    "query, expected",
    [
        (NOVEMBER, ["first day 00:30"]),
        (FIRST_OF_NOVEMBER, ["first day 00:30"]),
        (OCTOBER, []),
        (LAST_OF_OCTOBER, []),
    ],
)
def test_a_0030_booking_on_the_first_day_is_in_that_month_and_not_the_previous(monkeypatch, query, expected):
    assert _venue_calendar(monkeypatch, [("first day 00:30", FIRST_DAY_0030)], query) == expected


def test_a_day_query_returns_that_day_only_with_nothing_from_either_side(monkeypatch):
    spans = [
        ("previous day 23:00", PREVIOUS_DAY_2300),
        ("first day 00:30", FIRST_DAY_0030),
        ("next day 00:30", NEXT_DAY_0030),
    ]

    assert _venue_calendar(monkeypatch, spans, FIRST_OF_NOVEMBER) == ["first day 00:30"]


def test_blocks_use_the_same_window_as_bookings(monkeypatch):
    fake = FakeSupabase()
    fake.tables["venue_bookings"] = []
    fake.tables["venue_blocks"] = [
        {
            "id": "block-1",
            "venue_id": "venue-1",
            "reason": "maintenance",
            "note": None,
            "block_start": FIRST_DAY_0030[0],
            "block_end": FIRST_DAY_0030[1],
        }
    ]
    monkeypatch.setattr(service_module, "supabase", fake)
    monkeypatch.setattr(service_module, "get_venue", lambda venue_id: {"id": venue_id, "name": "Grand Ballroom"})

    assert len(service_module.get_venue_calendar("venue-1", *NOVEMBER)["entries"]) == 1
    assert service_module.get_venue_calendar("venue-1", *OCTOBER)["entries"] == []


# -- the exact edges, in UTC ---------------------------------------------------
# 2026-11-01 as a Singapore day is 10-31 16:00 UTC up to 11-01 16:00 UTC.


def _utc(*parts) -> datetime:
    return datetime(*parts, tzinfo=UTC)


def test_period_ending_exactly_at_the_singapore_midnight_it_starts_from_is_outside():
    calendar_range = parse_calendar_range(*FIRST_OF_NOVEMBER)

    assert calendar_range.overlaps(_utc(2026, 10, 31, 15), _utc(2026, 10, 31, 16)) is False


def test_period_ending_one_microsecond_after_that_midnight_is_inside():
    calendar_range = parse_calendar_range(*FIRST_OF_NOVEMBER)

    assert calendar_range.overlaps(_utc(2026, 10, 31, 15), _utc(2026, 10, 31, 16, 0, 0, 1)) is True


def test_period_starting_at_the_singapore_days_last_instant_is_outside():
    """The window's end is time.max, compared strictly."""
    calendar_range = parse_calendar_range(*FIRST_OF_NOVEMBER)

    assert calendar_range.overlaps(_utc(2026, 11, 1, 15, 59, 59, 999999), _utc(2026, 11, 1, 17)) is False


def test_period_starting_one_microsecond_before_that_is_inside():
    calendar_range = parse_calendar_range(*FIRST_OF_NOVEMBER)

    assert calendar_range.overlaps(_utc(2026, 11, 1, 15, 59, 59, 999998), _utc(2026, 11, 1, 17)) is True
