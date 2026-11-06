"""Business logic for the venue catalogue: viewing it (View Venue Catalogue,
Nawaz, Sprint 1) and Venue Staff adding, editing and deleting venues
(IS-61 CRUD in Venue Catalogue).

tentative_hold_minutes (Sprint 3, Josiah, "Venue Availability Calendar
Tentative Hold") is edited through the same update_venue path as
setup_minutes/turnaround_minutes, not a separate endpoint -- IS-61 landed
on main as the venue catalogue's one write path while this was in
progress, so there is no longer a case for a second, narrower one just for
Venue Staff's three timing fields. See docs/design-decisions.md for why
this merged that way instead of keeping two.

INVARIANT, worth stating plainly because it is the whole reason "existing
bookings become problematic" needs no new detection code for IS-58/the
tentative hold story: editing setup_minutes/turnaround_minutes/
tentative_hold_minutes NEVER retroactively changes an existing
venue_bookings row. All three are snapshotted onto a booking once --
setup_minutes/turnaround_minutes at request time (create_booking_request),
tentative_hold_minutes at confirm time (confirm_booking) -- and never
re-read from `venues` afterward. Proven by
test_venue_settings_blocking_hold_integration.py::test_editing_venue_settings_does_not_change_existing_booking.
See docs/design-decisions.md for the full reasoning, including the one
soft edge this invariant does NOT cover (a still-PENDING request reviewed
against a venue's now-changed settings, logged in docs/open-questions.md,
not fixed -- fixing it would mean re-reading the venue later, which is
exactly the thing this invariant depends on never happening).

Deleting a venue removes its row from public.venues -- see
supabase/migrations/20261103000000_venue_hard_delete.sql. In the same
transaction:
  - the bookings of ongoing events (not completed, cancelled or rejected)
    are released first -- they become 'cancelled' with
    released_by_venue_deletion set, which is what the coordinator's "book
    another venue" alert on the event details page reads;
  - every booking of the venue, completed and cancelled events' included,
    keeps the venue's name as text (venue_bookings.venue_name) and loses
    only the link (venue_id becomes NULL), so past records still say where
    they were held.
"""

from __future__ import annotations

from datetime import time

from postgrest.exceptions import APIError

from app.events.event_service import ACCESSIBILITY_NEEDS, EQUIPMENT
from app.events.transitions import TransitionConflictError, transition
from app.extensions import supabase
from app.notifications import notification_service
from app.room_layouts.room_layout_service import list_room_layouts
from app.safety.safety_service import withdraw_pending_review
from app.shared.errors import NotFoundError, ValidationError

VENUE_STATUSES = {"available", "occupied", "maintenance"}

# Facilities and accessibility provisions use the same closed sets an event
# session asks for (event_service.EQUIPMENT / ACCESSIBILITY_NEEDS): venue
# search and the suitability checks compare the two lists value for value,
# so a venue listing "Wheelchair Access" would never match a session needing
# "wheelchair_access".
FACILITIES = EQUIPMENT
ACCESSIBILITY_FEATURES = ACCESSIBILITY_NEEDS

DEFAULT_BUFFER_MINUTES = 30
# Setup and turnaround buffers are at least this long: every booking needs
# some time to prepare and reset the room.
MIN_BUFFER_MINUTES = 5
# A tentative hold's default duration (24h) -- same guessed-default posture
# as DEFAULT_BUFFER_MINUTES, flagged in docs/open-questions.md. Matches
# venues.tentative_hold_minutes' own DB default
# (20261019010000_venue_settings_and_hold.sql).
DEFAULT_HOLD_MINUTES = 1440
MIN_HOLD_MINUTES = 1

_REQUIRED_ON_CREATE = ("name", "location", "capacity")
EDITABLE_FIELDS = frozenset(
    {
        "name",
        "location",
        "capacity",
        "facilities",
        "accessibility_features",
        "supported_layouts",
        "status",
        "setup_minutes",
        "turnaround_minutes",
        "tentative_hold_minutes",
        "operating_hours_start",
        "operating_hours_end",
    }
)
# Operating hours (IS-11 AC5, 6 Nov): one daily window per venue, the same
# every day. Optional -- both empty means no restriction -- but set as a
# pair. A closing time earlier than the opening time closes the next day
# (an overnight window, e.g. 20:00-01:00, or 08:00-00:00 for "until
# midnight"); the two can't be the same. New booking requests must fit
# inside it (booking_service.create_booking_request);
# existing bookings are left as they are when the hours change.
_HOURS_FIELDS = ("operating_hours_start", "operating_hours_end")

# Sessions that leave their stage when they lose a venue booking: a session
# can't stay confirmed, or under a safety check, without the venue it was
# confirmed or submitted with. Both go back to planning, where the
# coordinator can book another venue (rule_venue_booking_create).
_REVERT_TO_PLANNING = ("confirmed", "safety_review")


_DELETED_MESSAGE = "This venue has been deleted from the catalogue."


# -- reading -------------------------------------------------------------------


def list_venues(status: str | None = None) -> list[dict]:
    """Every venue in the catalogue, optionally filtered to one
    availability status. No per-caller scoping here (unlike
    events.list_event_requests) -- see rule_venue_list's docstring: the
    catalogue is shared inventory, not scoped to who is asking."""
    query = supabase.table("venues").select("*")
    if status is not None:
        query = query.eq("status", status)
    result = query.order("name").execute()
    return result.data or []


def get_venue(venue_id: str) -> dict:
    """One venue. A deleted venue's row is gone, so it is a 404; its old
    bookings show its name from venue_bookings.venue_name instead."""
    result = supabase.table("venues").select("*").eq("id", venue_id).maybe_single().execute()
    if result is None or not result.data:
        raise NotFoundError("Venue not found.")
    return result.data


# -- validation ----------------------------------------------------------------


def _text(record: dict, field: str, label: str) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label} is required.")
    return value.strip()


def _whole_number(record: dict, field: str, label: str, minimum: int, unit: str = "") -> int:
    value = record.get(field)
    # bool is an int subclass; True is not a capacity.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{label} must be a whole number.")
    if value < minimum:
        raise ValidationError(f"{label} must be at least {minimum}{unit}.")
    return value


def _choices(record: dict, field: str, label: str, allowed) -> list[str]:
    """A list drawn from `allowed`, duplicates dropped, order kept."""
    value = record.get(field) or []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValidationError(f"{label} must be a list of names.")
    unknown = sorted({item for item in value if item not in allowed})
    if unknown:
        raise ValidationError(
            f"Unknown {label.lower()}: {', '.join(unknown)}. Choose from: {', '.join(sorted(allowed))}."
        )
    return list(dict.fromkeys(value))


def _clock_time(record: dict, field: str, label: str) -> time | None:
    """A time of day ("08:00" or "08:00:00"), or None when left empty."""
    value = record.get(field)
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{label} must be a time of day, like 08:00.")
    try:
        return time.fromisoformat(value.strip())
    except ValueError:
        raise ValidationError(f"{label} must be a time of day, like 08:00.") from None


def _operating_hours(record: dict) -> dict:
    """Both operating-hours fields, checked as a pair (see _HOURS_FIELDS)."""
    opens = _clock_time(record, "operating_hours_start", "Opening time")
    closes = _clock_time(record, "operating_hours_end", "Closing time")
    if (opens is None) != (closes is None):
        raise ValidationError("Set both an opening and a closing time, or leave both empty.")
    if opens is not None and closes == opens:
        raise ValidationError(
            "Opening and closing times can't be the same. Leave both empty if the venue has no set hours."
        )
    return {
        "operating_hours_start": opens.isoformat("minutes") if opens else None,
        "operating_hours_end": closes.isoformat("minutes") if closes else None,
    }


def _validated(record: dict, kept_layouts=()) -> dict:
    """Every editable field of a whole venue record, checked and cleaned.

    `kept_layouts` are layouts the venue already lists: they may stay even if
    Venue Staff have since soft-deleted them (the room can still be set up
    that way -- see 20261012100000_venue_supported_layouts.sql), but only
    active layouts can be newly added. A venue supports at least one."""
    layouts = record.get("supported_layouts") or []
    if not isinstance(layouts, list) or not all(isinstance(item, str) for item in layouts):
        raise ValidationError("Supported room layouts must be a list of names.")
    if not layouts:
        raise ValidationError("Choose at least one supported room layout.")
    offered = {row["name"] for row in list_room_layouts()} | set(kept_layouts)
    unknown = sorted({name for name in layouts if name not in offered})
    if unknown:
        raise ValidationError(f"Unknown room layout: {', '.join(unknown)}. Refresh the page to see the current list.")

    status = record.get("status")
    if status not in VENUE_STATUSES:
        raise ValidationError(f"status must be one of: {', '.join(sorted(VENUE_STATUSES))}.")

    return {
        "name": _text(record, "name", "Name"),
        "location": _text(record, "location", "Location"),
        "capacity": _whole_number(record, "capacity", "Maximum capacity", 1),
        "facilities": _choices(record, "facilities", "Facilities", FACILITIES),
        "accessibility_features": _choices(
            record, "accessibility_features", "Accessibility provisions", ACCESSIBILITY_FEATURES
        ),
        "supported_layouts": list(dict.fromkeys(layouts)),
        "status": status,
        "setup_minutes": _whole_number(record, "setup_minutes", "Setup time", MIN_BUFFER_MINUTES, " minutes"),
        "turnaround_minutes": _whole_number(
            record, "turnaround_minutes", "Turnaround time", MIN_BUFFER_MINUTES, " minutes"
        ),
        "tentative_hold_minutes": _whole_number(
            record, "tentative_hold_minutes", "Tentative hold duration", MIN_HOLD_MINUTES, " minutes"
        ),
        **_operating_hours(record),
    }


def _body(body) -> dict:
    if not isinstance(body, dict):
        raise ValidationError("The venue body must be a JSON object.")
    unknown = set(body) - EDITABLE_FIELDS
    if unknown:
        raise ValidationError(f"Unknown venue fields: {', '.join(sorted(unknown))}.")
    return body


def _first(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _write(query) -> dict | None:
    """Runs an insert/update and returns the row (None if it matched none).
    The database's own layout check (a layout deleted meanwhile) and buffer
    check become a 400."""
    try:
        result = query.select("*").execute()
    except APIError as exc:
        if exc.code in ("23503", "23514"):
            raise ValidationError(exc.message) from exc
        raise
    return _first(result.data)


# -- add / edit ----------------------------------------------------------------


def create_venue(body) -> dict:
    """IS-61 AC1: Venue Staff add a venue. Name, location and capacity are
    required; everything else defaults (no facilities, available, 30-minute
    setup and turnaround, a 24h tentative hold, no operating-hours
    restriction unless opening and closing times are given)."""
    body = _body(body)
    missing = [field for field in _REQUIRED_ON_CREATE if body.get(field) in (None, "")]
    if missing:
        raise ValidationError(f"Missing required venue fields: {', '.join(missing)}.")
    record = {
        "status": "available",
        "setup_minutes": DEFAULT_BUFFER_MINUTES,
        "turnaround_minutes": DEFAULT_BUFFER_MINUTES,
        "tentative_hold_minutes": DEFAULT_HOLD_MINUTES,
        **body,
    }
    validated = _validated(record)
    if validated["operating_hours_start"] is None:
        # No hours given: leave both columns to their NULL default.
        for field in _HOURS_FIELDS:
            del validated[field]
    row = _write(supabase.table("venues").insert(validated))
    if not row:
        raise ValidationError("The venue database operation did not return a venue.")
    return row


def update_venue(venue_id: str, body) -> dict:
    """IS-61 AC2: Venue Staff edit a venue's details, including (Sprint 3)
    its tentative hold duration. Only the fields sent change, but the whole
    record is re-checked, so the result is always a valid venue.

    Existing bookings aren't touched: each booking snapshotted the venue's
    setup/turnaround minutes when it was made (see
    20261005100000_venue_bookings.sql) and its tentative_hold_minutes at
    confirm time (app.venues.booking_service.confirm_booking), so a changed
    value applies to new bookings/confirmations only -- see this module's
    own docstring for the invariant this depends on."""
    body = _body(body)
    if not body:
        raise ValidationError("Nothing to update.")
    current = get_venue(venue_id)
    merged = _validated({**current, **body}, kept_layouts=current.get("supported_layouts") or [])
    changes = {field: merged[field] for field in body}
    if any(field in body for field in _HOURS_FIELDS):
        # The pair is checked together, so it is written together.
        changes.update({field: merged[field] for field in _HOURS_FIELDS})
    row = _write(supabase.table("venues").update(changes).eq("id", venue_id))
    if not row:
        # Deleted between the read and the write: a delete racing this edit wins.
        raise NotFoundError(_DELETED_MESSAGE)
    return row


# -- delete --------------------------------------------------------------------


def delete_venue(venue_id: str, deleted_by: str) -> dict:
    """IS-61 AC3/AC4: Venue Staff delete a venue: its row is removed from
    the catalogue, and every booking of it keeps the venue's name as text.
    Ongoing events that booked it lose their booking, and their coordinator
    is alerted on the event details page to book another venue.

    The booking releases and the delete happen in one database transaction
    (delete_venue() in 20261103000000_venue_hard_delete.sql). Then each released
    session that was confirmed, or under a safety check, goes back to
    planning through transitions.transition() -- the only place event status
    is written -- so the coordinator can book again. Like every other status
    write in this codebase that follows another write, that part is not in
    the same transaction (see transitions' module docstring); a session that
    moved on meanwhile (e.g. was cancelled) is left as it is.

    Returns {"venue", "released_bookings", "returned_to_planning"}."""
    outcome = _db_delete_venue(venue_id, deleted_by)
    if outcome["outcome"] == "not_found":
        raise NotFoundError("Venue not found.")

    venue = outcome["venue"]
    released = outcome.get("released") or []
    reason = f'Venue "{venue["name"]}" was deleted from the venue catalogue, so its booking was released.'

    returned = []
    sessions = {row["event_id"]: row["event_status"] for row in released}
    for event_id, event_status in sessions.items():
        if event_status not in _REVERT_TO_PLANNING:
            continue
        if event_status == "safety_review":
            # Its pending check was for arrangements it no longer has; left
            # pending it would also block resubmitting (one pending review
            # per session).
            withdraw_pending_review(event_id, deleted_by, reason)
        try:
            transition(event_id, "planning", deleted_by, reason=reason, expected_from=event_status)
        except TransitionConflictError:
            continue  # moved on since (e.g. cancelled); the release stands either way
        returned.append(event_id)

    for row in released:
        _notify_venue_deleted(row, venue)
    return {"venue": venue, "released_bookings": released, "returned_to_planning": returned}


def _notify_venue_deleted(released_booking: dict, venue: dict) -> None:
    """The session's coordinator gets an in-app notification (IS-69,
    notification_service.venue_booking_released). The alert on the event
    details page (VenueRemovedAlert.vue), read from the booking's
    released_by_venue_deletion flag, is unchanged."""
    notification_service.venue_booking_released(released_booking, venue)


# -- database access (isolated so unit tests don't fake the query builder) --


def _db_delete_venue(venue_id: str, deleted_by: str) -> dict:
    return supabase.rpc("delete_venue", {"p_venue_id": venue_id, "p_deleted_by": deleted_by}).execute().data
