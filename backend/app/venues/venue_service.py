"""Business logic for the venue catalogue: viewing it (View Venue Catalogue,
Nawaz, Sprint 1) and Venue Staff adding, editing and deleting venues
(IS-61 CRUD in Venue Catalogue).

Deleting is a soft delete (venues.deleted_at) -- see
supabase/migrations/20261023100000_venue_catalogue_crud.sql for why. A
deleted venue:
  - leaves the catalogue (list_venues) and can't be edited or booked;
  - is still returned by get_venue, flagged with deleted_at, so old
    bookings can still show where they were;
  - releases the bookings of ongoing events (not completed, cancelled or
    rejected) -- they become 'cancelled' with released_by_venue_deletion
    set, which is what the coordinator's "book another venue" alert on the
    event details page reads.
"""

from __future__ import annotations

from postgrest.exceptions import APIError

from app.events.event_service import ACCESSIBILITY_NEEDS, EQUIPMENT
from app.events.transitions import TransitionConflictError, transition
from app.extensions import supabase
from app.room_layouts.room_layout_service import list_room_layouts
from app.safety.safety_service import withdraw_pending_review
from app.shared.errors import AppError, NotFoundError, ValidationError

VENUE_STATUSES = {"available", "occupied", "maintenance"}

# Facilities and accessibility provisions use the same closed sets an event
# session asks for (event_service.EQUIPMENT / ACCESSIBILITY_NEEDS): venue
# search and the suitability checks compare the two lists value for value,
# so a venue listing "Wheelchair Access" would never match a session needing
# "wheelchair_access".
FACILITIES = EQUIPMENT
ACCESSIBILITY_FEATURES = ACCESSIBILITY_NEEDS

DEFAULT_BUFFER_MINUTES = 30

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
    }
)
# Not editable here: operating_hours_start/end (IS-11). Nothing but the
# venue calendar's note reads them, so IS-61 leaves them out of the form
# and the API -- a new venue has no set hours (both NULL), and an edit
# leaves a venue's existing hours as they are.

# Sessions that leave their stage when they lose a venue booking: a session
# can't stay confirmed, or under a safety check, without the venue it was
# confirmed or submitted with. Both go back to planning, where the
# coordinator can book another venue (rule_venue_booking_create).
_REVERT_TO_PLANNING = ("confirmed", "safety_review")


_DELETED_EDIT_MESSAGE = "This venue has been deleted from the catalogue, so it can no longer be edited."


class VenueDeletedError(AppError):
    """The venue was deleted from the catalogue, so it can't be changed."""

    status_code = 409
    code = "venue_deleted"


# -- reading -------------------------------------------------------------------


def list_venues(status: str | None = None) -> list[dict]:
    """Every venue in the catalogue, optionally filtered to one
    availability status. Deleted venues aren't in the catalogue. No
    per-caller scoping here (unlike events.list_event_requests) -- see
    rule_venue_list's docstring: the catalogue is shared inventory, not
    scoped to who is asking."""
    query = supabase.table("venues").select("*").is_("deleted_at", "null")
    if status is not None:
        query = query.eq("status", status)
    result = query.order("name").execute()
    return result.data or []


def get_venue(venue_id: str) -> dict:
    """One venue, deleted or not (deleted_at says which) -- a booking made
    before the delete still needs to show its venue."""
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


def _whole_number(record: dict, field: str, label: str, minimum: int) -> int:
    value = record.get(field)
    # bool is an int subclass; True is not a capacity.
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{label} must be a whole number.")
    if value < minimum:
        raise ValidationError(f"{label} must be at least {minimum}.")
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


def _validated(record: dict, kept_layouts=()) -> dict:
    """Every editable field of a whole venue record, checked and cleaned.

    `kept_layouts` are layouts the venue already lists: they may stay even if
    Venue Staff have since soft-deleted them (the room can still be set up
    that way -- see 20261012100000_venue_supported_layouts.sql), but only
    active layouts can be newly added."""
    layouts = record.get("supported_layouts") or []
    if not isinstance(layouts, list) or not all(isinstance(item, str) for item in layouts):
        raise ValidationError("Supported room layouts must be a list of names.")
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
        "setup_minutes": _whole_number(record, "setup_minutes", "Setup time", 0),
        "turnaround_minutes": _whole_number(record, "turnaround_minutes", "Turnaround time", 0),
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
    setup and turnaround, no operating-hours restriction)."""
    body = _body(body)
    missing = [field for field in _REQUIRED_ON_CREATE if body.get(field) in (None, "")]
    if missing:
        raise ValidationError(f"Missing required venue fields: {', '.join(missing)}.")
    record = {
        "status": "available",
        "setup_minutes": DEFAULT_BUFFER_MINUTES,
        "turnaround_minutes": DEFAULT_BUFFER_MINUTES,
        **body,
    }
    row = _write(supabase.table("venues").insert(_validated(record)))
    if not row:
        raise ValidationError("The venue database operation did not return a venue.")
    return row


def update_venue(venue_id: str, body) -> dict:
    """IS-61 AC2: Venue Staff edit a venue's details. Only the fields sent
    change, but the whole record is re-checked, so the result is always a
    valid venue.

    Existing bookings aren't touched: each booking snapshotted the venue's
    setup/turnaround minutes when it was made (see
    20261005100000_venue_bookings.sql), so a changed buffer applies to new
    bookings only."""
    body = _body(body)
    if not body:
        raise ValidationError("Nothing to update.")
    current = get_venue(venue_id)
    if current.get("deleted_at"):
        raise VenueDeletedError(_DELETED_EDIT_MESSAGE)
    merged = _validated({**current, **body}, kept_layouts=current.get("supported_layouts") or [])
    changes = {field: merged[field] for field in body}
    # Conditioned on not deleted: a delete racing this edit wins.
    row = _write(supabase.table("venues").update(changes).eq("id", venue_id).is_("deleted_at", "null"))
    if not row:
        raise VenueDeletedError(_DELETED_EDIT_MESSAGE)
    return row


# -- delete --------------------------------------------------------------------


def delete_venue(venue_id: str, deleted_by: str) -> dict:
    """IS-61 AC3/AC4: Venue Staff delete a venue. Ongoing events that booked
    it lose their booking, and their coordinator is alerted on the event
    details page to book another venue.

    The soft delete and the booking releases happen in one database
    transaction (delete_venue() in the migration). Then each released
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
    if outcome["outcome"] == "already_deleted":
        raise VenueDeletedError("This venue has already been deleted from the catalogue.")

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
    """Hook for the Notification System story, same no-op shape as
    booking_service._notify_booking_decision. The coordinator's alert itself
    is on the event details page (VenueRemovedAlert.vue), read from the
    booking's released_by_venue_deletion flag."""
    print(f"[notify] venue booking {released_booking['booking_id']} released: venue {venue['id']} deleted")


# -- database access (isolated so unit tests don't fake the query builder) --


def _db_delete_venue(venue_id: str, deleted_by: str) -> dict:
    return supabase.rpc("delete_venue", {"p_venue_id": venue_id, "p_deleted_by": deleted_by}).execute().data
