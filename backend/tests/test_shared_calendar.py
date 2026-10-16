"""Unit tests for app.shared.calendar -- the domain-neutral calendar
pieces extracted from app.venues.calendar_service. The venue calendar's
own tests (test_calendar_service.py, test_venue_calendar_routes.py) still
cover them end to end; these pin the shared behaviour directly, including
the boundaries those don't reach."""

from __future__ import annotations

from datetime import datetime, time

import pytest

from app.shared.calendar import CalendarRange, calendar_envelope, parse_calendar_range, spans_overlap
from app.shared.errors import ValidationError


def _at(day: int, hour: int = 0, minute: int = 0) -> datetime:
    return datetime(2026, 12, day, hour, minute)


# -- parse_calendar_range ---------------------------------------------------


def test_range_covers_whole_days_with_an_inclusive_end():
    calendar_range = parse_calendar_range("2026-12-01", "2026-12-31")

    assert calendar_range.start == "2026-12-01"
    assert calendar_range.end == "2026-12-31"
    assert calendar_range.range_start == datetime(2026, 12, 1, 0, 0)
    assert calendar_range.range_end == datetime.combine(_at(31).date(), time.max)


def test_single_day_range_is_allowed():
    calendar_range = parse_calendar_range("2026-12-10", "2026-12-10")

    assert calendar_range.range_start == _at(10)
    assert calendar_range.range_end.date() == _at(10).date()


def test_end_before_start_is_rejected():
    with pytest.raises(ValidationError, match="end must not be before start"):
        parse_calendar_range("2026-12-31", "2026-12-01")


@pytest.mark.parametrize("start, end", [("not-a-date", "2026-12-31"), ("2026-12-01", "2026-13-01")])
def test_malformed_date_is_rejected_naming_the_value(start, end):
    bad = start if start == "not-a-date" else end
    with pytest.raises(ValidationError, match=f"'{bad}' is not a valid date"):
        parse_calendar_range(start, end)


# -- spans_overlap ------------------------------------------------------------


def test_overlapping_spans_overlap():
    assert spans_overlap(_at(1, 9), _at(1, 12), _at(1, 11), _at(1, 14)) is True


def test_span_inside_another_overlaps():
    assert spans_overlap(_at(1, 10), _at(1, 11), _at(1, 9), _at(1, 12)) is True


def test_touching_spans_do_not_overlap_either_way():
    """Half-open: a span ending at 12:00 and one starting at 12:00 are
    back to back, not overlapping -- in both argument orders."""
    assert spans_overlap(_at(1, 9), _at(1, 12), _at(1, 12), _at(1, 14)) is False
    assert spans_overlap(_at(1, 12), _at(1, 14), _at(1, 9), _at(1, 12)) is False


def test_separate_spans_do_not_overlap():
    assert spans_overlap(_at(1, 9), _at(1, 10), _at(1, 11), _at(1, 12)) is False


# -- CalendarRange.overlaps ---------------------------------------------------


def test_entry_ending_exactly_at_range_start_is_outside():
    calendar_range = parse_calendar_range("2026-12-10", "2026-12-10")

    assert calendar_range.overlaps(_at(9, 20), _at(10, 0)) is False


def test_entry_starting_on_the_inclusive_end_day_is_inside():
    calendar_range = parse_calendar_range("2026-12-01", "2026-12-10")

    assert calendar_range.overlaps(_at(10, 23, 30), _at(11, 1)) is True


def test_entry_starting_the_day_after_end_is_outside():
    calendar_range = parse_calendar_range("2026-12-01", "2026-12-10")

    assert calendar_range.overlaps(_at(11, 0), _at(11, 2)) is False


def test_entry_offset_is_dropped_not_converted():
    """Placed by the wall-clock time stored with it: 2026-12-11 01:00+08:00
    is 2026-12-10 17:00 UTC, but it is on the 11th, so outside a range
    ending on the 10th."""
    calendar_range = parse_calendar_range("2026-12-01", "2026-12-10")
    start = datetime.fromisoformat("2026-12-11T01:00:00+08:00")
    end = datetime.fromisoformat("2026-12-11T03:00:00+08:00")

    assert calendar_range.overlaps(start, end) is False


# -- calendar_envelope ---------------------------------------------------------


def test_envelope_puts_the_resource_under_its_own_key():
    calendar_range = CalendarRange("2026-12-01", "2026-12-31", _at(1), _at(31))
    entries = [{"type": "block"}]

    assert calendar_envelope("equipment", {"id": "unit-1"}, calendar_range, entries) == {
        "equipment": {"id": "unit-1"},
        "range": {"start": "2026-12-01", "end": "2026-12-31"},
        "entries": entries,
    }
