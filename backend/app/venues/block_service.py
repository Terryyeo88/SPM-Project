"""Venue Becomes Unavailable After Booking (Josiah, Sprint 3, Week 7
change #2). Venue Staff mark a venue "blocked" for a period, with a
mandatory reason, even when future bookings already exist against it.

Writes venue_blocks -- a table 20261007000000_venue_calendar.sql already
created for the calendar to READ (IS-11), but which that migration's own
header explicitly left write-less, naming this exact story as the one
that would add creation. See 20261019030000_venue_blocks_write.sql for
the RLS policy this module's writes depend on.

The existing event is NEVER cancelled by creating a block (AC). Instead,
every already-CONFIRMED booking the new block overlaps is released
(app.venues.booking_release.release_bookings_overlapping_block) -- the
coordinator sees it on their own event page (VenueBookingStatus.vue,
same "Request a different venue" link a rejected booking already shows)
and can search for a replacement venue, with the original event
information untouched (AC: "preserve the original event information").

PENDING bookings overlapping the new block are deliberately left alone
here -- a pending request isn't holding the venue yet (same
_BLOCKING_STATUSES=confirmed-only stance
booking_service._confirmed_overlap_exists already takes), so there's
nothing yet to release. It's Venue Staff's own call when they get to
reviewing it; the confirm path is separately guarded
(booking_service._blocked_period_exists, checked by confirm_booking) so
it can never be confirmed INTO the blocked period.
"""

from __future__ import annotations

from datetime import datetime

from app.extensions import supabase
from app.shared.errors import ValidationError
from app.venues.booking_release import release_bookings_overlapping_block
from app.venues.venue_service import get_venue

VENUE_BLOCK_REASONS = {"maintenance", "renovation", "safety_issue", "internal_activity", "other"}


def _parse_timestamptz(value) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValidationError("block_start/block_end must be ISO timestamps.")
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"'{value}' is not a valid timestamp.") from exc


def _block_fields_from(body) -> dict:
    """Validates reason/note/block_start/block_end client-side -- a
    friendlier 400 than relying on the database's own enum/check
    constraints to reject bad input."""
    if not isinstance(body, dict):
        raise ValidationError("The venue block body must be a JSON object.")
    unknown = set(body) - {"reason", "note", "block_start", "block_end"}
    if unknown:
        raise ValidationError(f"Unknown venue block fields: {', '.join(sorted(unknown))}.")
    reason = body.get("reason")
    if reason not in VENUE_BLOCK_REASONS:
        raise ValidationError(f"reason must be one of: {', '.join(sorted(VENUE_BLOCK_REASONS))}.")
    block_start = _parse_timestamptz(body.get("block_start"))
    block_end = _parse_timestamptz(body.get("block_end"))
    if block_end <= block_start:
        raise ValidationError("block_end must be after block_start.")
    note = body.get("note")
    if note is not None and not isinstance(note, str):
        raise ValidationError("note must be a string.")
    return {
        "reason": reason,
        "note": (note or "").strip() or None,
        "block_start": body["block_start"],
        "block_end": body["block_end"],
    }


def _notify_coordinator_venue_blocked(booking: dict) -> None:
    """Hook for the Notification System story (later sprint). No-op
    placeholder, same shape as every other _notify_* stub in this
    codebase -- no real notification plumbing exists anywhere yet."""
    print(f"[notify] venue booking {booking['id']} released: venue blocked")


def create_venue_block(venue_id: str, body, created_by: str) -> dict:
    """Creates the block, then releases every CONFIRMED booking it
    overlaps. Returns {"block": {...}, "released_bookings": [...]} so
    "affected bookings must be identified" (AC) is visibly true in the
    response, not just a side effect a caller has to go looking for."""
    fields = _block_fields_from(body)
    get_venue(venue_id)  # 404s for an unknown venue before writing anything
    result = (
        supabase.table("venue_blocks")
        .insert({"venue_id": venue_id, "created_by": created_by, **fields})
        .select("*")
        .execute()
    )
    if not result.data:
        raise ValidationError("The venue block database operation did not return a block.")
    block = result.data[0] if isinstance(result.data, list) else result.data

    released = release_bookings_overlapping_block(
        venue_id,
        _parse_timestamptz(fields["block_start"]),
        _parse_timestamptz(fields["block_end"]),
        reason=f"Venue blocked: {fields['reason'].replace('_', ' ')}.",
        changed_by=created_by,
    )
    for booking in released:
        _notify_coordinator_venue_blocked(booking)

    return {
        "block": block,
        "released_bookings": [{"booking_id": booking["id"], "event_id": booking["event_id"]} for booking in released],
    }


def list_venue_blocks(venue_id: str) -> list[dict]:
    """Every block for a venue -- the Venue Staff management view.
    Separate from the calendar's own read of venue_blocks
    (app.venues.calendar_service.get_venue_calendar), which already
    exposes blocks to Coordinators too via VENUE_CALENDAR_VIEW; this one
    is Venue Staff's own list, gated on VENUE_BLOCK."""
    get_venue(venue_id)
    result = (
        supabase.table("venue_blocks")
        .select("*")
        .eq("venue_id", venue_id)
        .order("block_start", desc=True)
        .execute()
    )
    return result.data or []
