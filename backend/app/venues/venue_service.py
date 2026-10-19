"""Business logic for the venue catalogue (View Venue Catalogue, Nawaz,
Sprint 1), plus (Sprint 3, Josiah) Venue Staff editing a venue's own
timing settings -- "Request Venue Booking with Setup and Turnaround
Time"'s real remaining scope, since the automatic apply-at-booking-time
half shipped in Sprint 2 (app.venues.booking_service.create_booking_request).

update_venue_settings is the FIRST write path this module has ever had --
see app/authz/actions.py's venues section, which explicitly anticipated
"no venue.create/edit/delete actions exist yet... whoever builds venue
management later should add those the same way, sourced the same way".
Mirrors app.room_layouts.room_layout_service's shape (the only existing
"Venue Staff manages a resource" precedent in this codebase): a small
field-validating parser, a fetch-or-404 update, Postgres error codes
translated to this module's own errors rather than leaking a raw APIError.

INVARIANT, worth stating plainly because it is the whole reason "existing
bookings become problematic" needs no new detection code here: editing
setup_minutes/turnaround_minutes/tentative_hold_minutes NEVER retroactively
changes an existing venue_bookings row. All three are snapshotted onto a
booking once -- setup_minutes/turnaround_minutes at request time
(create_booking_request), tentative_hold_minutes at confirm time
(confirm_booking) -- and never re-read from `venues` afterward. Proven by
test_booking_service_integration.py::test_editing_venue_settings_does_not_change_existing_booking.
See docs/design-decisions.md for the full reasoning, including the one
soft edge this invariant does NOT cover (a still-PENDING request reviewed
against a venue's now-changed settings, logged in docs/open-questions.md,
not fixed -- fixing it would mean re-reading the venue later, which is
exactly the thing this invariant depends on never happening)."""

from __future__ import annotations

from postgrest.exceptions import APIError

from app.extensions import supabase
from app.shared.errors import NotFoundError, ValidationError

VENUE_STATUSES = {"available", "occupied", "maintenance"}

EDITABLE_VENUE_FIELDS = {"setup_minutes", "turnaround_minutes", "tentative_hold_minutes"}


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
    result = supabase.table("venues").select("*").eq("id", venue_id).maybe_single().execute()
    if result is None or not result.data:
        raise NotFoundError("Venue not found.")
    return result.data


def _settings_from(body) -> dict:
    """Mirrors room_layout_service._name_from's shape: rejects unknown
    keys, requires at least one editable field, validates each present
    value is a positive int. A caller can update any subset of the three
    fields in one call (e.g. just tentative_hold_minutes) -- there's no
    "all three or none" requirement."""
    if not isinstance(body, dict):
        raise ValidationError("The venue settings body must be a JSON object.")
    unknown = set(body) - EDITABLE_VENUE_FIELDS
    if unknown:
        raise ValidationError(f"Unknown venue setting fields: {', '.join(sorted(unknown))}.")
    if not body:
        raise ValidationError(f"Provide at least one of: {', '.join(sorted(EDITABLE_VENUE_FIELDS))}.")
    values = {}
    for field in EDITABLE_VENUE_FIELDS:
        if field not in body:
            continue
        value = body[field]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValidationError(f"{field} must be a positive whole number of minutes.")
        values[field] = value
    return values


def update_venue_settings(venue_id: str, body) -> dict:
    """Venue Staff edit setup_minutes/turnaround_minutes/
    tentative_hold_minutes on an existing venue. 400 (ValidationError),
    not 409 -- unlike room layouts' duplicate-name conflict, there is no
    uniqueness concept here, just input that failed the new CHECK
    constraints (23514) added in
    20261019010000_venue_settings_and_hold.sql."""
    values = _settings_from(body)
    try:
        result = supabase.table("venues").update(values).eq("id", venue_id).select("*").execute()
    except APIError as exc:
        if exc.code == "23514":
            raise ValidationError("Venue settings must be positive whole numbers of minutes.") from exc
        raise
    if not result.data:
        raise NotFoundError("Venue not found.")
    return result.data[0] if isinstance(result.data, list) else result.data
