"""Business logic for venue booking requests and their approval/rejection.

Implements "Request Venue Booking" (Venue Booking Request, Josiah, Sprint
2) and "Approve Venue Bookings" (Venue Booking Approval, Josiah, Sprint
2), plus (Sprint 3) the confirm-time half of "Venue Becomes Unavailable
After Booking" (app.venues.block_service owns the write side -- creating
a block; this module only guards against confirming a pending request
INTO an already-blocked period, see _blocked_period_exists) and the
booking side of "Venue Availability Calendar Tentative Hold" (a confirmed
booking's hold expiry -- see app.venues.booking_release, touched at
every call site in this module that treats status="confirmed" as
"genuinely holding the venue"). NOT implemented here (separate,
unassigned stories -- see docs/design-decisions.md): the full Booking
Conflict Detection story (flagging pending-vs-pending conflicts), and the
calendar display itself (app.venues.calendar_service).

One booking is keyed to one EVENT ROW (session), not to shared_event_id
(the whole multi-session request) -- see
supabase/migrations/20261005100000_venue_bookings.sql's own comment for
why.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace

from postgrest.exceptions import APIError

from app.events.event_service import SINGAPORE_TZ
from app.extensions import supabase
from app.shared.errors import NotFoundError, ValidationError
from app.venues.booking_release import release_expired_hold, touch_expired_holds

BOOKING_STATUSES = {"pending", "confirmed", "rejected", "released"}

# Statuses that count as "this booking is actively holding the venue" for
# overlap purposes. Deliberately CONFIRMED ONLY -- not pending -- this is
# the narrow guard behind Approval AC1 ("the venue is marked unavailable
# for that period"), not the full Booking Conflict Detection story
# (pending-vs-pending flagging is explicitly a separate, unassigned
# story; see this module's own docstring and docs/design-decisions.md).
_BLOCKING_STATUSES = ("confirmed",)


def _parse_date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _parse_time(value: str | None) -> time | None:
    return time.fromisoformat(value) if value else None


def _parse_timestamptz(value: str) -> datetime:
    """Postgres timestamptz values round-trip through supabase-py as ISO
    strings; `datetime.fromisoformat` only accepts a literal "Z" suffix
    on Python 3.11+, so this normalises it first -- same defensive
    conversion app.events.event_service._parse_registration_datetime
    already applies, for the same reason."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _event_window(event: SimpleNamespace) -> tuple[datetime, datetime]:
    """The session's own [start, end) span, in Singapore time, BEFORE any
    setup/turnaround buffer is applied.

    Same date/time fallback rules as coordinator_service._event_span
    (missing end date -> same day; missing time -> start/end of day),
    duplicated rather than imported: that function is module-private in
    another module, and this keeps booking_service independently
    testable without cross-module coupling on another module's private
    helper.

    Made timezone-AWARE (Singapore, same SINGAPORE_TZ used for
    registration_start_datetime/registration_end_datetime in
    event_service.py) rather than naive, because this feeds a
    `timestamptz` column (venue_bookings.booking_start/booking_end) -- a
    naive value would be silently read by Postgres as UTC, shifting it
    by Singapore's 8 hours, exactly the pitfall
    _parse_registration_datetime's own docstring warns about.
    """
    start_date = _parse_date(event.preferred_start_date)
    end_date = _parse_date(getattr(event, "preferred_end_date", None)) or start_date
    start_time = _parse_time(getattr(event, "preferred_start_time", None)) or time.min
    end_time = _parse_time(getattr(event, "preferred_end_time", None)) or time.max
    return (
        datetime.combine(start_date, start_time, tzinfo=SINGAPORE_TZ),
        datetime.combine(end_date, end_time, tzinfo=SINGAPORE_TZ),
    )


def _get_venue(venue_id: str) -> dict:
    result = supabase.table("venues").select("*").eq("id", venue_id).maybe_single().execute()
    if result is None or not result.data:
        raise ValidationError("venue_id does not reference an existing venue.")
    return result.data


def _spans_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """True if two [start, end) spans overlap at all -- same idiom as
    coordinator_service._spans_overlap, generalised to take raw
    datetimes instead of event dicts (a venue_bookings row already
    stores its own padded span directly, so there's no event-shaped row
    to re-derive it from)."""
    return a_start < b_end and b_start < a_end


def _confirmed_overlap_exists(
    venue_id: str, booking_start: datetime, booking_end: datetime, exclude_booking_id: str | None = None
) -> bool:
    """True if `venue_id` already has another CONFIRMED booking whose
    padded span overlaps [booking_start, booking_end).

    Every fetched row is touched through release_expired_hold FIRST, so a
    stale "confirmed" row whose tentative hold has actually expired never
    counts as blocking -- this is the one place every confirm attempt
    flows through (directly here, or via confirm_booking's own call
    below), so it's where lazy expiry gets enforced for free, before the
    UPDATE that would otherwise hit IS-16's exclusion constraint. See
    app.venues.booking_release and docs/design-decisions.md."""
    result = (
        supabase.table("venue_bookings")
        .select("*")
        .eq("venue_id", venue_id)
        .in_("status", _BLOCKING_STATUSES)
        .execute()
    )
    rows = touch_expired_holds(result.data or [])
    for row in rows:
        if row.get("status") != "confirmed":
            continue  # touched and released above -- no longer holding the venue
        if exclude_booking_id and row["id"] == exclude_booking_id:
            continue
        other_start = _parse_timestamptz(row["booking_start"])
        other_end = _parse_timestamptz(row["booking_end"])
        if _spans_overlap(booking_start, booking_end, other_start, other_end):
            return True
    return False


def _blocked_period_exists(venue_id: str, booking_start: datetime, booking_end: datetime) -> bool:
    """True if `venue_id` has a venue_blocks row overlapping
    [booking_start, booking_end) -- the confirm-time half of "Venue
    Becomes Unavailable After Booking": a pending request is left alone
    when a block is first created (Venue Staff's own call when they get
    to reviewing it -- see block_service.create_venue_block's own
    docstring), but it must never be CONFIRMED into an already-blocked
    period. Checked by confirm_booking alongside _confirmed_overlap_exists."""
    result = (
        supabase.table("venue_blocks")
        .select("block_start, block_end")
        .eq("venue_id", venue_id)
        .execute()
    )
    for row in result.data or []:
        block_start = _parse_timestamptz(row["block_start"])
        block_end = _parse_timestamptz(row["block_end"])
        if _spans_overlap(booking_start, booking_end, block_start, block_end):
            return True
    return False


def create_booking_request(event: SimpleNamespace, venue_id, requested_by: str) -> dict:
    """Creates a pending venue booking for one event session.

    authz (rule_venue_booking_create) has already checked the caller is
    the event's assigned coordinator and the event is in "planning" --
    the coordinator moves it there themselves (Start Planning), so this
    never changes the event's status.
    """
    if not isinstance(venue_id, str) or not venue_id.strip():
        raise ValidationError("venue_id is required.")
    venue = _get_venue(venue_id)

    session_start, session_end = _event_window(event)
    setup = venue["setup_minutes"]
    turnaround = venue["turnaround_minutes"]
    booking_start = session_start - timedelta(minutes=setup)
    booking_end = session_end + timedelta(minutes=turnaround)

    result = (
        supabase.table("venue_bookings")
        .insert(
            {
                "event_id": event.id,
                "venue_id": venue_id,
                "status": "pending",
                "requested_by": requested_by,
                # Snapshotted at creation time -- see the migration's own
                # comment on why this isn't re-read from the venue later.
                "setup_minutes": setup,
                "turnaround_minutes": turnaround,
                "booking_start": booking_start.isoformat(),
                "booking_end": booking_end.isoformat(),
            }
        )
        .select("*")
        .execute()
    )
    if not result.data:
        raise ValidationError("The venue booking database operation did not return a booking.")
    booking = result.data[0] if isinstance(result.data, list) else result.data

    return booking


def _attach_rejection_reasons(rows: list[dict]) -> list[dict]:
    """Adds `rejection` ({"reason", "rejected_at", "rejected_by"}) to each
    rejected booking -- the reason itself lives only in
    venue_booking_status_log (reject_booking records it there, never on
    the venue_bookings row itself), so Approval AC2 ("the Coordinator can
    view it") needs this join. Exact mirror of
    app.events.event_service._attach_rejections, same reasoning: only the
    LATEST rejection of a given booking, since in principle it could be
    rejected, a fresh request made, and rejected again."""
    rejected_ids = [row["id"] for row in rows if row.get("status") == "rejected"]
    if not rejected_ids:
        return rows
    result = (
        supabase.table("venue_booking_status_log")
        .select("booking_id, reason, changed_at, profiles(name)")
        .in_("booking_id", rejected_ids)
        .eq("to_status", "rejected")
        .execute()
    )
    latest = {}
    for entry in sorted(result.data or [], key=lambda entry: entry.get("changed_at") or ""):
        latest[entry["booking_id"]] = entry  # later entries overwrite earlier ones
    for row in rows:
        entry = latest.get(row["id"])
        if row.get("status") == "rejected" and entry:
            row["rejection"] = {
                "reason": entry.get("reason"),
                "rejected_at": entry.get("changed_at"),
                "rejected_by": (entry.get("profiles") or {}).get("name"),
            }
    return rows


def _attach_release_reasons(rows: list[dict]) -> list[dict]:
    """Adds `release` ({"reason", "released_at", "released_by"}) to each
    released booking -- exact mirror of _attach_rejection_reasons, joined
    from the same venue_booking_status_log, but its OWN field (not
    overloading `rejection`): `rejected` must keep meaning only "Venue
    Staff declined it", never a system-initiated release. released_by is
    None for a system-initiated release (expiry, a cancelled event) --
    present only when a Venue Staff action (block creation) supplied a
    real changed_by."""
    released_ids = [row["id"] for row in rows if row.get("status") == "released"]
    if not released_ids:
        return rows
    result = (
        supabase.table("venue_booking_status_log")
        .select("booking_id, reason, changed_at, profiles(name)")
        .in_("booking_id", released_ids)
        .eq("to_status", "released")
        .execute()
    )
    latest = {}
    for entry in sorted(result.data or [], key=lambda entry: entry.get("changed_at") or ""):
        latest[entry["booking_id"]] = entry
    for row in rows:
        entry = latest.get(row["id"])
        if row.get("status") == "released" and entry:
            row["release"] = {
                "reason": entry.get("reason"),
                "released_at": entry.get("changed_at"),
                "released_by": (entry.get("profiles") or {}).get("name"),
            }
    return rows


def get_booking(booking_id: str) -> dict:
    result = supabase.table("venue_bookings").select("*").eq("id", booking_id).maybe_single().execute()
    if result is None or not result.data:
        raise NotFoundError("Venue booking not found.")
    booking = release_expired_hold(result.data)
    # Read-only conflict/blocked flags, surfaced BEFORE a decision is
    # made (not just enforced when confirm_booking is actually called),
    # so Venue Staff see the same conflicts a confirm attempt would hit --
    # the wireframe's "Suitability Check" panel reads these fields.
    booking["conflict"] = _confirmed_overlap_exists(
        booking["venue_id"],
        _parse_timestamptz(booking["booking_start"]),
        _parse_timestamptz(booking["booking_end"]),
        exclude_booking_id=booking["id"],
    )
    booking["blocked"] = _blocked_period_exists(
        booking["venue_id"],
        _parse_timestamptz(booking["booking_start"]),
        _parse_timestamptz(booking["booking_end"]),
    )
    booking = _attach_rejection_reasons([booking])[0]
    return _attach_release_reasons([booking])[0]


def list_bookings_for_event(event_id: str) -> list[dict]:
    result = (
        supabase.table("venue_bookings")
        .select("*")
        .eq("event_id", event_id)
        .order("created_at", desc=True)
        .execute()
    )
    rows = touch_expired_holds(result.data or [])
    rows = _attach_rejection_reasons(rows)
    return _attach_release_reasons(rows)


def has_live_confirmed_booking(event_id: str) -> bool:
    """True if `event_id` has at least one CONFIRMED venue booking that
    genuinely still holds a venue, after touching away any expired
    tentative holds. The gate behind events/routes.py::confirm_event
    (Sprint 3): without this, an event could reach "confirmed" status
    with a venue booking that already expired, directly violating the
    Tentative Hold AC ("an expired hold should not be treated as a
    confirmed booking") -- see docs/design-decisions.md for how this gap
    was found. PLURAL-SAFE: true if ANY confirmed booking remains, not
    tied to exactly one."""
    result = supabase.table("venue_bookings").select("*").eq("event_id", event_id).eq("status", "confirmed").execute()
    touched = touch_expired_holds(result.data or [])
    return any(row.get("status") == "confirmed" for row in touched)


def list_bookings(user, status: str | None = None) -> list[dict]:
    """Every booking the caller is entitled to see, scoped per role --
    see rule_venue_booking_list's own comment: the role-only authz check
    does not mean "every booking", THIS function's per-row scoping is the
    real gate, same division of responsibility as
    event_service.list_event_requests:
      - event_coordinator sees bookings THEY requested
      - venue_staff sees every booking (no per-venue-staff-assignment
        table exists yet -- see docs/open-questions.md)
    A user holding both roles sees the union, same structural stance
    app.authz.rules takes everywhere else."""
    if status is not None and status not in BOOKING_STATUSES:
        raise ValidationError(f"status must be one of: {', '.join(sorted(BOOKING_STATUSES))}.")

    roles = set(user.roles)
    if "venue_staff" not in roles and "event_coordinator" not in roles:
        # Defence in depth behind rule_venue_booking_list, same "fail
        # closed" stance as list_event_requests's own equivalent comment.
        return []

    # Embeds the event's and venue's own name -- the queue spans many
    # events/venues at once (unlike list_bookings_for_event, already
    # scoped to one known event), so Venue Staff need something to
    # recognise each row by other than a bare event_id/venue_id. Same
    # embed idiom as event_service._attach_rejections' profiles(name),
    # relying on venue_bookings having exactly one FK to each table so
    # PostgREST needs no explicit relationship hint.
    query = supabase.table("venue_bookings").select("*, events(name), venues(name)")
    if "venue_staff" not in roles:
        # Coordinator-only caller: scoped to their own requests. A
        # venue_staff caller (with or without also holding
        # event_coordinator) sees everything, per the union above --
        # unfiltered is the wider of the two, so it's correct for both.
        query = query.eq("requested_by", user.id)
    # The status filter is NOT pushed into the query -- it's applied
    # below, AFTER touch_expired_holds. Filtering at the database layer
    # first would use each row's possibly-stale DB status: a booking
    # whose hold just expired would still read "confirmed" in Postgres
    # until something touches it, so a caller asking for status="released"
    # could miss it, and a caller asking for status="confirmed" could get
    # a row that's actually expired. Touching the whole scoped set first
    # means the filter always sees current, not stale, state.
    result = query.order("created_at", desc=True).execute()
    rows = touch_expired_holds(result.data or [])
    if status is not None:
        rows = [row for row in rows if row.get("status") == status]
    return rows


def _record_booking_status_change(
    booking_id: str, from_status: str, to_status: str, changed_by: str, reason: str | None = None
) -> None:
    """Audit trail -- see
    supabase/migrations/20261005100000_venue_bookings.sql for why this
    mirrors event_status_log's shape rather than
    coordinator_assignment_log's."""
    supabase.table("venue_booking_status_log").insert(
        {
            "booking_id": booking_id,
            "from_status": from_status,
            "to_status": to_status,
            "changed_by": changed_by,
            "reason": reason,
        }
    ).execute()


def _notify_booking_decision(booking: dict, decision: str) -> None:
    """Hook for the Notification System story (Justin, later sprint).
    No-op placeholder, same shape as
    coordinator_service._notify_coordinator_assigned -- no real
    notification plumbing exists anywhere in this codebase yet."""
    print(f"[notify] venue booking {booking['id']} {decision}")


def _decide_booking(
    booking_id: str, booking: SimpleNamespace, to_status: str, decided_by: str, reason, extra_fields: dict | None = None
):
    """Moves a pending booking to `to_status`. The authz rule
    (rule_venue_booking_approve/reject) has already checked the caller is
    venue_staff and the booking is pending. The update is ALSO
    conditioned on status still being "pending", same race-proofing as
    app.events.event_service._decide: two decisions racing each other
    (a double click, or approve and reject from two tabs) can't both
    land -- the second matches no row and gets a clear error instead of
    silently winning.

    extra_fields is merged into the same UPDATE -- confirm_booking uses
    it to snapshot hold_minutes/confirmed_at atomically with the status
    change, not as a second write, so there is never a window where a
    row reads status="confirmed" with a still-null confirmed_at.
    """
    try:
        result = (
            supabase.table("venue_bookings")
            .update({"status": to_status, **(extra_fields or {})})
            .eq("id", booking_id)
            .eq("status", "pending")
            .select("*")
            .execute()
        )
    except APIError as exc:
        # IS-16's exclusion constraint refused the confirm: another confirm
        # of an overlapping booking got there first, past the app check
        # above. 23P01 normally; 40P01 when both reached the constraint
        # before either committed (see docs/design-decisions.md).
        if exc.code in ("23P01", "40P01"):
            raise ValidationError(
                "This venue already has a confirmed booking overlapping this period -- it cannot be confirmed."
            ) from exc
        raise
    if not result.data:
        raise ValidationError("This booking is no longer pending -- refresh to see its current status.")
    _record_booking_status_change(booking_id, booking.status, to_status, decided_by, reason)
    return result.data[0] if isinstance(result.data, list) else result.data


def confirm_booking(booking_id: str, booking: SimpleNamespace, decided_by: str) -> dict:
    """Venue Booking Approval: Venue Staff approve -> "confirmed".

    Does NOT transition the event's own status to "confirmed" -- that
    Event Status Management story explicitly also needs equipment
    approval ("once venue AND equipment requests are approved"), a
    different, unbuilt story's call to make. See
    docs/design-decisions.md.

    Snapshots the venue's CURRENT tentative_hold_minutes onto the
    booking, and confirmed_at = now(), together with the status change
    (same "snapshot once, never re-read" stance setup_minutes/
    turnaround_minutes already take at request time) -- this is what the
    hold-expiry tracking in app.venues.booking_release reads. A later
    edit to the venue's own tentative_hold_minutes never changes an
    already-confirmed booking's deadline.
    """
    if _confirmed_overlap_exists(
        booking.venue_id,
        _parse_timestamptz(booking.booking_start),
        _parse_timestamptz(booking.booking_end),
        exclude_booking_id=booking_id,
    ):
        raise ValidationError(
            "This venue already has a confirmed booking overlapping this period -- it cannot be confirmed."
        )
    if _blocked_period_exists(
        booking.venue_id,
        _parse_timestamptz(booking.booking_start),
        _parse_timestamptz(booking.booking_end),
    ):
        raise ValidationError(
            "This venue has been blocked for part of this period -- it cannot be confirmed."
        )
    venue = _get_venue(booking.venue_id)
    extra_fields = {
        "hold_minutes": venue["tentative_hold_minutes"],
        "confirmed_at": datetime.now(UTC).isoformat(),
    }
    decided = _decide_booking(booking_id, booking, "confirmed", decided_by, None, extra_fields=extra_fields)
    _notify_booking_decision(decided, "confirmed")
    return decided


def reject_booking(booking_id: str, booking: SimpleNamespace, decided_by: str, reason) -> dict:
    """Venue Booking Approval: Venue Staff reject -> "rejected". A reason
    is required (AC2: "they must provide a reason, and the Coordinator
    can view it")."""
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError("A reason is required to reject a venue booking.")
    decided = _decide_booking(booking_id, booking, "rejected", decided_by, reason.strip())
    _notify_booking_decision(decided, "rejected")
    return decided
