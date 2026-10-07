"""Business logic for the venue availability calendar (View Venue
Availability Calendar, Nawaz, Sprint 2, IS-11). Read-only -- see
supabase/migrations/20261007000000_venue_calendar.sql's header for why
venue_blocks exists but nothing here can create one (that's "Venue
Becomes Unavailable (blocking)", a separate, unassigned story).

Four states, straight from the AC ("available, tentatively held,
confirmed, or blocked"). Only three of those are ever materialised as a
calendar ENTRY -- "available" is the absence of an entry over a period,
not a row of its own:

  tentatively_held -- a venue_bookings row with status "confirmed" (i.e.
                       Venue Staff approved it -- see booking_service's
                       own docstring on why CONFIRMED is the "holding the
                       venue" status, not "pending"), whose EVENT has not
                       itself reached event status "confirmed" yet.
  confirmed         -- the same booking-confirmed case, but the event
                       has also reached "confirmed". This confirmed/
                       tentatively_held split is exactly the flow the
                       team talked through on the Sept 9 planning call:
                       approved-by-venue-staff first holds tentatively,
                       then flips to confirmed once the EVENT itself
                       confirms -- not a new booking status, a label
                       derived from two tables that already exist.
  blocked           -- a venue_blocks row (see that table's migration).

A "pending" venue_bookings row is deliberately NOT an entry: nothing has
been approved yet, so there is nothing yet to hold the venue -- same
exclusion app.venues.booking_service._BLOCKING_STATUSES already applies
for the overlap guard, reused here for the same reason.
"""

from __future__ import annotations

from datetime import date, datetime, time

from app.extensions import supabase
from app.shared.errors import ValidationError
from app.venues.venue_service import get_venue

# Mirrors booking_service._BLOCKING_STATUSES -- not imported, because
# that name is module-private there and this module should stay
# independently testable without reaching into another module's
# internals, same stance booking_service's own _event_window docstring
# already takes on duplicating coordinator_service's helper.
_HELD_BOOKING_STATUSES = ("confirmed",)


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(f"'{value}' is not a valid date (expected YYYY-MM-DD).") from exc


def _parse_timestamptz(value: str) -> datetime:
    """Same normalisation as booking_service._parse_timestamptz -- see
    that function's own docstring for why the "Z" replace is needed."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def get_venue_calendar(venue_id: str, start: str, end: str) -> dict:
    """Entries for `venue_id` whose period overlaps [start, end) -- start/
    end are plain YYYY-MM-DD date strings (the caller picks day, week, or
    month by how far apart they are; this function doesn't care which,
    matching AC1's "a chosen day, week, or month" with a single range
    query rather than three separate code paths for three granularities).

    Returns the venue's profile fields (so a caller doesn't need a
    second round trip for name/operating hours), plus the entry list.
    """
    start_date = _parse_date(start)
    end_date = _parse_date(end)
    if end_date < start_date:
        raise ValidationError("end must not be before start.")

    venue = get_venue(venue_id)

    # Half-open [range_start, range_end) in UTC-naive terms is good
    # enough here for the overlap filter below -- the DB round trip
    # queries don't need to be timezone-exact, only to over-fetch
    # slightly (a whole extra day at each edge) rather than under-fetch;
    # the precise overlap check against each row's own timestamptz
    # happens in Python afterwards, same two-stage pattern
    # booking_service._confirmed_overlap_exists already uses (fetch by
    # venue_id, then filter spans in Python).
    range_start = datetime.combine(start_date, time.min)
    range_end = datetime.combine(end_date, time.max)

    entries = []

    # -- blocks -----------------------------------------------------
    blocks_result = (
        supabase.table("venue_blocks")
        .select("id, reason, note, block_start, block_end")
        .eq("venue_id", venue_id)
        .execute()
    )
    for row in blocks_result.data or []:
        block_start = _parse_timestamptz(row["block_start"])
        block_end = _parse_timestamptz(row["block_end"])
        if block_start.replace(tzinfo=None) < range_end and range_start < block_end.replace(tzinfo=None):
            entries.append(
                {
                    "type": "block",
                    "state": "blocked",
                    "start": row["block_start"],
                    "end": row["block_end"],
                    "reason": row["reason"],
                    "note": row.get("note"),
                }
            )

    # -- bookings -----------------------------------------------------
    # Embeds events(name, status) -- AC4 ("each booked entry identifies
    # the event it belongs to, without exposing internal planning details
    # to users not entitled to see them") is satisfied by only ever
    # selecting the event's name and status here, never the full event
    # row (description, organiser, coordinator, attendance figures etc.
    # all stay unfetched) -- same "select only what the consumer is
    # entitled to" discipline as booking_service.list_bookings' own
    # events(name)/venues(name) embed.
    bookings_result = (
        supabase.table("venue_bookings")
        .select("id, event_id, booking_start, booking_end, status, events(name, status)")
        .eq("venue_id", venue_id)
        .in_("status", _HELD_BOOKING_STATUSES)
        .execute()
    )
    for row in bookings_result.data or []:
        booking_start = _parse_timestamptz(row["booking_start"])
        booking_end = _parse_timestamptz(row["booking_end"])
        if not (booking_start.replace(tzinfo=None) < range_end and range_start < booking_end.replace(tzinfo=None)):
            continue
        event = row.get("events") or {}
        state = "confirmed" if event.get("status") == "confirmed" else "tentatively_held"
        entries.append(
            {
                "type": "booking",
                "state": state,
                "start": row["booking_start"],
                "end": row["booking_end"],
                "event_id": row["event_id"],
                "event_name": event.get("name"),
            }
        )

    entries.sort(key=lambda entry: entry["start"])

    return {
        "venue": {
            "id": venue["id"],
            "name": venue["name"],
            "operating_hours_start": venue.get("operating_hours_start"),
            "operating_hours_end": venue.get("operating_hours_end"),
        },
        "range": {"start": start, "end": end},
        "entries": entries,
    }
