"""Domain-neutral pieces of an availability calendar, shared by every
calendar the API serves (the venue calendar, IS-11, today; the equipment
calendar, IS-47, next). Extracted from app.venues.calendar_service with
its behaviour unchanged -- see docs/design-decisions.md, "Shared calendar
module".

What lives here is only what does not depend on what is being booked:

  parse_calendar_range  the caller's YYYY-MM-DD start/end, validated
                        (malformed date or end before start -> 400) and
                        widened to whole days: start's midnight through the
                        last instant of end's day (time.max), so `end` is
                        an INCLUSIVE day.
  spans_overlap         half-open interval overlap, [a_start, a_end) vs
                        [b_start, b_end).
  calendar_envelope     the response shape,
                        {<resource_key>: {...}, range: {start, end}, entries: [...]}.

What each domain service keeps: its own row queries, how it parses its
rows' timestamps, and how a row becomes an entry with a state (the
venue's confirmed vs tentatively_held, for example).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from app.shared.errors import ValidationError


@dataclass(frozen=True)
class CalendarRange:
    """A validated calendar range. `start`/`end` are the caller's own
    strings, echoed back in the response; `range_start`/`range_end` are
    the naive datetimes entries are compared against."""

    start: str
    end: str
    range_start: datetime
    range_end: datetime

    def overlaps(self, entry_start: datetime, entry_end: datetime) -> bool:
        """Whether an entry's period falls (partly) inside this range.

        The range is naive (whole calendar days), so the entry's own
        offset is dropped rather than converted: an entry is placed by the
        wall-clock time it was stored with. Good enough to choose which
        rows to show for a day/week/month -- not a precise instant
        comparison."""
        return spans_overlap(
            entry_start.replace(tzinfo=None),
            entry_end.replace(tzinfo=None),
            self.range_start,
            self.range_end,
        )


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"'{value}' is not a valid date (expected YYYY-MM-DD).") from exc


def parse_calendar_range(start: str, end: str) -> CalendarRange:
    """Validate a calendar's start/end query values (plain YYYY-MM-DD
    dates; the caller picks day, week or month by how far apart they
    are). Raises ValidationError (400) for a malformed date or an end
    before the start."""
    start_date = _parse_date(start)
    end_date = _parse_date(end)
    if end_date < start_date:
        raise ValidationError("end must not be before start.")
    return CalendarRange(
        start=start,
        end=end,
        range_start=datetime.combine(start_date, time.min),
        range_end=datetime.combine(end_date, time.max),
    )


def spans_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Half-open overlap: a period ending exactly when another starts does
    not overlap it."""
    return a_start < b_end and b_start < a_end


def calendar_envelope(resource_key: str, resource: dict, calendar_range: CalendarRange, entries: list[dict]) -> dict:
    """The calendar response: the resource's profile fields under its own
    key (e.g. "venue"), the range as the caller sent it, and the entries."""
    return {
        resource_key: resource,
        "range": {"start": calendar_range.start, "end": calendar_range.end},
        "entries": entries,
    }
