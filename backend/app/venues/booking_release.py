"""Releasing a CONFIRMED venue booking for a reason other than Venue
Staff rejecting it (Josiah, Sprint 3).

Three triggers share this one mechanism, each calling in from its own
module:
  - an event is cancelled (app.events.routes::cancel_event)
  - a tentative hold expires (app.venues.booking_service, touched at
    every read/decide path that treats "confirmed" as "genuinely holding
    the venue" -- see that module's own comments on each call site)
  - a venue is blocked (app.venues.block_service::create_venue_block)

All three move a booking confirmed -> released (a fourth
venue_booking_status value, distinct from rejected -- see
20261019020000_venue_booking_released_status.sql's own docstring for why
reusing rejected was rejected). Deliberately its own module, not folded
into booking_service.py: it has three callers across three modules
(events/routes.py, block_service.py, booking_service.py itself), the same
"more than one caller outside its own domain" shape that already put
equipment's release-on-cancel in its own file
(app.equipment.reservation_release) rather than inside
equipment_service.py.

Has its OWN small audit-log writer rather than importing
booking_service._record_booking_status_change -- booking_service.py
needs to call INTO this module (to touch-and-release expired holds
before trusting a "confirmed" row), so importing booking_service FROM
here would be circular. Same duplication stance booking_service.py's own
_event_window already takes on coordinator_service._event_span, for the
same reason.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.extensions import supabase

# Statuses an event reaching them means its venue arrangement has
# "graduated" past any hold concept -- a hold must never be revisited
# once the event gets this far, however much (now stale) time has
# elapsed since the booking was confirmed. See release_expired_hold.
_HOLD_GRADUATED_EVENT_STATUSES = ("confirmed", "completed")


def _parse_timestamptz(value: str) -> datetime:
    """Same normalisation as booking_service._parse_timestamptz -- see
    that function's own docstring for why the "Z" replace is needed."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _record_status_change(
    booking_id: str, from_status: str, to_status: str, changed_by: str | None, reason: str
) -> None:
    """Mirrors booking_service._record_booking_status_change exactly --
    same venue_booking_status_log shape. changed_by may be None here (a
    system-initiated release), unlike booking_service's own callers,
    which always pass a real person -- same NULL-means-no-human-actor
    convention app.events.transitions already established for
    event_status_log.changed_by."""
    supabase.table("venue_booking_status_log").insert(
        {
            "booking_id": booking_id,
            "from_status": from_status,
            "to_status": to_status,
            "changed_by": changed_by,
            "reason": reason,
        }
    ).execute()


def release_booking(
    booking_id: str, booking: dict | SimpleNamespace, reason: str, changed_by: str | None = None
) -> dict:
    """confirmed -> released. Race-guarded the same way as
    booking_service._decide_booking (WHERE id=:id AND status='confirmed'),
    but IDEMPOTENT AND SILENT on a lost race, not strict-and-loud:
    _decide_booking guards a USER decision (two people deciding at once
    must be told, loudly, that only one won) -- this guards a SYSTEM
    repair, where two readers racing to lazily fix the same stale row
    both need to succeed quietly, since neither is "deciding" anything,
    they're just catching the database up to a fact that already became
    true (the hold already expired, the event was already cancelled).
    Returns the current row either way -- already-released is not an
    error here."""
    current_status = booking.get("status") if isinstance(booking, dict) else booking.status
    result = (
        supabase.table("venue_bookings")
        .update({"status": "released"})
        .eq("id", booking_id)
        .eq("status", "confirmed")
        .select("*")
        .execute()
    )
    if not result.data:
        # Lost the race, or was never confirmed in the first place -- read
        # back the current row rather than erroring; a caller asking to
        # release something already released gets a no-op, not a 409.
        existing = supabase.table("venue_bookings").select("*").eq("id", booking_id).maybe_single().execute()
        if existing and existing.data:
            return existing.data
        return booking if isinstance(booking, dict) else vars(booking)
    _record_status_change(booking_id, current_status, "released", changed_by, reason)
    return result.data[0] if isinstance(result.data, list) else result.data


def release_bookings_for_event(event_id: str, reason: str, changed_by: str | None = None) -> list[dict]:
    """Every CONFIRMED booking for event_id, released -- PLURAL-SAFE
    (operates on "every", not "the", confirmed booking for this event),
    future-proofed for the unassigned Multiple Venues for One Event
    story without extra cost now. Used by events/routes.py::cancel_event."""
    result = supabase.table("venue_bookings").select("*").eq("event_id", event_id).eq("status", "confirmed").execute()
    return [release_booking(row["id"], row, reason, changed_by) for row in (result.data or [])]


def release_bookings_overlapping_block(
    venue_id: str, block_start: datetime, block_end: datetime, reason: str, changed_by: str | None = None
) -> list[dict]:
    """Every CONFIRMED booking for venue_id whose padded span overlaps
    [block_start, block_end), released. PENDING bookings are deliberately
    untouched here -- see block_service.create_venue_block's own
    docstring for why. Used by block_service.create_venue_block."""
    result = supabase.table("venue_bookings").select("*").eq("venue_id", venue_id).eq("status", "confirmed").execute()
    released = []
    for row in result.data or []:
        booking_start = _parse_timestamptz(row["booking_start"])
        booking_end = _parse_timestamptz(row["booking_end"])
        if booking_start < block_end and block_start < booking_end:
            released.append(release_booking(row["id"], row, reason, changed_by))
    return released


def _event_status(event_id: str) -> str | None:
    result = supabase.table("events").select("status").eq("id", event_id).maybe_single().execute()
    if result is None or not result.data:
        return None
    return result.data["status"]


def release_expired_hold(booking: dict, event_status: str | None = None) -> dict:
    """If booking is confirmed, its hold has elapsed, AND its event has
    NOT already reached confirmed/completed, lazily release it (system-
    initiated: changed_by=None) and return the updated row; otherwise
    return booking unchanged.

    The event-status guard is not optional decoration: without it, an
    event that confirmed long ago (arbitrarily past its booking's
    original hold_minutes window, which stopped mattering the moment it
    confirmed) would be incorrectly re-"expired" on every future touch.
    A hold "graduates" once its event reaches confirmed -- past that
    point elapsed time against hold_minutes is meaningless and must never
    be revisited. See docs/design-decisions.md for the full reasoning,
    and events/routes.py::confirm_event for the gate that depends on this
    guard being correct.

    event_status is optional -- pass it when the caller already has the
    event loaded (e.g. events/routes.py::confirm_event, which is deciding
    based on exactly this event) to skip a redundant query; fetched from
    `events` otherwise.
    """
    if booking.get("status") != "confirmed":
        return booking
    confirmed_at = booking.get("confirmed_at")
    hold_minutes = booking.get("hold_minutes")
    if not confirmed_at or hold_minutes is None:
        return booking
    deadline = _parse_timestamptz(confirmed_at) + timedelta(minutes=hold_minutes)
    if datetime.now(UTC) < deadline:
        return booking
    status = event_status if event_status is not None else _event_status(booking["event_id"])
    if status in _HOLD_GRADUATED_EVENT_STATUSES:
        return booking
    return release_booking(booking["id"], booking, "Tentative hold expired.", changed_by=None)


def touch_expired_holds(bookings: list[dict]) -> list[dict]:
    """Batch form of release_expired_hold for a list of rows that may
    span several events -- batches the event-status lookups (one query
    for every distinct event_id among confirmed rows, not N+1) before
    calling release_expired_hold per row. Used wherever a list of
    bookings is read: booking_service.list_bookings_for_event/
    list_bookings, calendar_service.get_venue_calendar,
    change_impact._venue_impacts, safety_service's confirmed-booking
    checks."""
    confirmed_event_ids = {row["event_id"] for row in bookings if row.get("status") == "confirmed"}
    if not confirmed_event_ids:
        return bookings
    result = supabase.table("events").select("id, status").in_("id", list(confirmed_event_ids)).execute()
    statuses = {row["id"]: row["status"] for row in (result.data or [])}
    return [release_expired_hold(row, event_status=statuses.get(row["event_id"])) for row in bookings]
