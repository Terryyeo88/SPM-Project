"""Domain-neutral pieces of an availability calendar, shared by every
calendar the API serves (the venue calendar, IS-11, today; the equipment
calendar, IS-47, next). Extracted from app.venues.calendar_service with
its behaviour unchanged -- see docs/design-decisions.md, "Shared calendar
module".

What lives here is only what does not depend on what is being booked:

  parse_calendar_range  the caller's YYYY-MM-DD start/end, validated
                        (malformed date or end before start -> 400) and
                        widened to whole Singapore days: start's midnight
                        through the last instant of end's day (time.max), so
                        `end` is an INCLUSIVE day.
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
from datetime import date, datetime, time, timedelta, timezone

from app.shared.errors import ValidationError

# The timezone a calendar day is measured in. A fixed offset is exact here, not
# a shortcut: Singapore has been UTC+8 with no daylight saving since 1982, so
# there is no transition for it to get wrong on any date a booking can have. It
# also needs no tzdata package on Windows, unlike zoneinfo.
#
# This assumes one timezone for everyone. The start/end dates a caller sends are
# read as Singapore days, and the frontend sends the browser's local dates and
# places entries by the browser's local day (lib/calendar.js). A venue or a user
# outside UTC+8 would break that: the window and the grid would disagree, and
# this constant would have to become per-venue, in the frontend as well.
CALENDAR_TIMEZONE = timezone(timedelta(hours=8), "SGT")


@dataclass(frozen=True)
class CalendarRange:
    """A validated calendar range. `start`/`end` are the caller's own
    strings, echoed back in the response; `range_start`/`range_end` are
    naive Singapore wall-clock times, which entries are compared against."""

    start: str
    end: str
    range_start: datetime
    range_end: datetime

    def overlaps(self, entry_start: datetime, entry_end: datetime) -> bool:
        """Whether an entry's period falls (partly) inside this range.

        PostgREST returns timestamptz values in UTC, so an entry is converted
        to Singapore time first. Otherwise a booking at 00:30 on the 1st,
        which is 16:30 UTC on the day before, would land in the wrong month."""
        return spans_overlap(
            _calendar_wall_clock(entry_start),
            _calendar_wall_clock(entry_end),
            self.range_start,
            self.range_end,
        )


def _calendar_wall_clock(value: datetime) -> datetime:
    """`value` as naive Singapore time. A naive value is taken as already being
    that: astimezone() would read it in the host's timezone."""
    if value.tzinfo is None:
        return value
    return value.astimezone(CALENDAR_TIMEZONE).replace(tzinfo=None)


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
