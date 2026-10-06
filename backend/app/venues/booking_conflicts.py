"""Booking conflict reporting (IS-16 Detect conflicts in venue bookings).

IS-16 has two jobs, done by two mechanisms on purpose:

- PREVENTION is a database guarantee:
  supabase/migrations/20261006000000_venue_booking_no_overlap.sql adds an
  exclusion constraint, so two confirmed bookings of one venue can never
  hold overlapping periods, however two confirms interleave.
- REPORTING is this module: given a booking, WHICH confirmed bookings does
  it clash with? A constraint can only refuse a write; it can't list what
  a pending request would collide with before anyone tries to confirm it.

booking_service._confirmed_overlap_exists already answers "is there a
clash" (the `conflict` flag on get_booking). What it can't answer is
"which ones", because it stops at the first match. This module answers
that with the same blocking statuses and the same _spans_overlap
predicate, so the list and the flag can't disagree, and both agree with
the constraint (confirmed rows only, end-exclusive periods).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from app.extensions import supabase
from app.venues.booking_service import _BLOCKING_STATUSES, _parse_timestamptz, _spans_overlap


def confirmed_clashes(
    venue_id: str, booking_start: datetime, booking_end: datetime, exclude_booking_id: str | None = None
) -> list[dict]:
    """Every confirmed booking of `venue_id` whose period overlaps
    [booking_start, booking_end), earliest first. `exclude_booking_id`
    leaves out the booking being checked, if it is itself confirmed."""
    clashes = []
    for row in _db_blocking_bookings(venue_id):
        if row["id"] == exclude_booking_id:
            continue
        start = _parse_timestamptz(row["booking_start"])
        end = _parse_timestamptz(row["booking_end"])
        if _spans_overlap(booking_start, booking_end, start, end):
            clashes.append((start, row))
    clashes.sort(key=lambda pair: pair[0])
    return [_shape(row) for _, row in clashes]


def clashes_for_booking(booking: SimpleNamespace) -> list[dict]:
    """confirmed_clashes for an existing booking (as load_booking returns it)."""
    return confirmed_clashes(
        booking.venue_id,
        _parse_timestamptz(booking.booking_start),
        _parse_timestamptz(booking.booking_end),
        exclude_booking_id=booking.id,
    )


def _shape(row: dict) -> dict:
    # The event name is what lets Venue Staff recognise the clashing
    # booking, same reason list_bookings embeds events(name).
    return {
        "id": row["id"],
        "event_id": row["event_id"],
        "event_name": (row.get("events") or {}).get("name"),
        "booking_start": row["booking_start"],
        "booking_end": row["booking_end"],
    }


def _db_blocking_bookings(venue_id: str) -> list[dict]:
    result = (
        supabase.table("venue_bookings")
        .select("id, event_id, booking_start, booking_end, events(name)")
        .eq("venue_id", venue_id)
        .in_("status", _BLOCKING_STATUSES)
        .execute()
    )
    return result.data or []
