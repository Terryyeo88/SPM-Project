"""HTTP routes for the venue catalogue (View Venue Catalogue, Nawaz,
Sprint 1) and venue bookings (Venue Booking Request / Approval, Josiah,
Sprint 2). Catalogue: GET /venues (list, optionally filtered by
?status=) and GET /venues/<venue_id> (single record). IS-61 (Venue Staff
only):

  POST   /venues              -- add a venue
  POST   /venues/<venue_id>   -- edit a venue (only the fields sent change)
  DELETE /venues/<venue_id>   -- delete it; releases ongoing events' bookings

Booking routes use a static "/bookings" prefix, declared BEFORE the
catalogue's own dynamic "/<venue_id>" route below -- otherwise Flask
would match "/venues/bookings" as "/venues/<venue_id>" with
venue_id="bookings", same static-before-dynamic care already taken for
/events/coordinators vs /events/<event_id>."""

from __future__ import annotations

from types import SimpleNamespace

from flask import Blueprint, jsonify, request

from app.auth.context import current_user
from app.authz.actions import (
    VENUE_BOOKING_APPROVE,
    VENUE_BOOKING_CANCEL,
    VENUE_BOOKING_LIST,
    VENUE_BOOKING_REJECT,
    VENUE_BOOKING_VIEW,
    VENUE_CALENDAR_VIEW,
    VENUE_CREATE,
    VENUE_DELETE,
    VENUE_EDIT,
    VENUE_LIST,
    VENUE_VIEW,
)
from app.authz.decorators import require
from app.extensions import supabase
from app.shared.errors import ValidationError
from app.venues.booking_service import (
    BOOKING_STATUSES,
    cancel_booking,
    confirm_booking,
    get_booking,
    list_bookings,
    reject_booking,
)
from app.venues.calendar_service import get_venue_calendar
from app.venues.venue_service import (
    VENUE_STATUSES,
    create_venue,
    delete_venue,
    get_venue,
    list_venues,
    update_venue,
)

venues_bp = Blueprint("venues", __name__, url_prefix="/venues")


# Static path -- must come before GET /venues/<venue_id> below.
@venues_bp.route("/bookings", methods=["GET"])
@require(VENUE_BOOKING_LIST)
def list_venue_bookings_route():
    status = request.args.get("status")
    if status is not None and status not in BOOKING_STATUSES:
        raise ValidationError(f"status must be one of: {', '.join(sorted(BOOKING_STATUSES))}.")
    return jsonify(list_bookings(current_user(), status)), 200


# Static path -- must come before GET /venues/<venue_id> below.
@venues_bp.route("/bookings/<booking_id>", methods=["GET"])
@require(VENUE_BOOKING_VIEW, loader=lambda booking_id: load_booking(booking_id))
def get_venue_booking_route(booking, booking_id):
    return jsonify(vars(booking)), 200


# Static path -- must come before GET /venues/<venue_id> below.
@venues_bp.route("/bookings/<booking_id>/approve", methods=["POST"])
@require(VENUE_BOOKING_APPROVE, loader=lambda booking_id: load_booking(booking_id))
def approve_venue_booking_route(booking, booking_id):
    confirmed = confirm_booking(booking_id, booking, current_user().id)
    return jsonify(confirmed), 200


# Static path -- must come before GET /venues/<venue_id> below.
@venues_bp.route("/bookings/<booking_id>/reject", methods=["POST"])
@require(VENUE_BOOKING_REJECT, loader=lambda booking_id: load_booking(booking_id))
def reject_venue_booking_route(booking, booking_id):
    body = request.get_json(silent=True) or {}
    rejected = reject_booking(booking_id, booking, current_user().id, body.get("reason"))
    return jsonify(rejected), 200


# IS-9: the assigned coordinator cancels one booking (reason required). Only
# that booking changes -- the session's other bookings are left as they are.
# Static path -- must come before GET /venues/<venue_id> below.
@venues_bp.route("/bookings/<booking_id>/cancel", methods=["POST"])
@require(VENUE_BOOKING_CANCEL, loader=lambda booking_id: load_booking_with_event(booking_id))
def cancel_venue_booking_route(booking, booking_id):
    body = request.get_json(silent=True) or {}
    cancelled = cancel_booking(booking_id, booking, current_user().id, body.get("reason"))
    return jsonify(cancelled), 200


def load_booking_with_event(booking_id: str) -> SimpleNamespace:
    """load_booking plus the booking's event's coordinator_id and status
    (as event_coordinator_id / event_status), which rule_venue_booking_cancel
    needs: the event's current coordinator cancels, not whoever requested
    the booking."""
    booking = load_booking(booking_id)
    rows = supabase.table("events").select("coordinator_id, status").eq("id", booking.event_id).execute().data or []
    event = rows[0] if rows else {}
    booking.event_coordinator_id = event.get("coordinator_id")
    booking.event_status = event.get("status")
    return booking


def load_booking(booking_id: str) -> SimpleNamespace:
    """Loader for @require -- fetches the booking (via get_booking, which
    also raises NotFoundError for a missing row) and exposes it as a
    VenueBookingLike (see app.authz.protocol) so the policy rule can read
    it. Same wrap-in-SimpleNamespace pattern as app.events.routes.load_event
    -- get_booking's extra computed "conflict" field just rides along as
    an unused attribute, same as any other dict field no rule happens to
    read."""
    return SimpleNamespace(**get_booking(booking_id))


@venues_bp.route("", methods=["GET"])
@require(VENUE_LIST)
def list_venues_route():
    status = request.args.get("status")
    if status is not None and status not in VENUE_STATUSES:
        raise ValidationError(f"status must be one of: {', '.join(sorted(VENUE_STATUSES))}.")
    return jsonify(list_venues(status)), 200


@venues_bp.route("/<venue_id>", methods=["GET"])
@require(VENUE_VIEW, loader=lambda venue_id: load_venue(venue_id))
def get_venue_route(venue, venue_id):
    return jsonify(venue), 200


@venues_bp.route("", methods=["POST"])
@require(VENUE_CREATE)
def create_venue_route():
    return jsonify(create_venue(request.get_json(silent=True))), 201


# POST, not PATCH, for an edit -- same as POST /room-layouts/<id>.
@venues_bp.route("/<venue_id>", methods=["POST"])
@require(VENUE_EDIT)
def update_venue_route(venue_id):
    return jsonify(update_venue(venue_id, request.get_json(silent=True))), 200


@venues_bp.route("/<venue_id>", methods=["DELETE"])
@require(VENUE_DELETE)
def delete_venue_route(venue_id):
    return jsonify(delete_venue(venue_id, current_user().id)), 200


# View Venue Availability Calendar (Nawaz, Sprint 2, IS-11). `start`/`end`
# (YYYY-MM-DD, half-open-ish -- see calendar_service.get_venue_calendar's
# own docstring) are both required: the AC's "chosen day, week, or month"
# is a frontend view choice, not something this route guesses a default
# for -- same "the caller states its own range" stance
# app.venues.calendar_service takes.
@venues_bp.route("/<venue_id>/calendar", methods=["GET"])
@require(VENUE_CALENDAR_VIEW, loader=lambda venue_id: load_venue(venue_id))
def get_venue_calendar_route(venue, venue_id):
    start = request.args.get("start")
    end = request.args.get("end")
    if not start or not end:
        raise ValidationError("Both 'start' and 'end' query parameters (YYYY-MM-DD) are required.")
    return jsonify(get_venue_calendar(venue_id, start, end)), 200


def load_venue(venue_id: str) -> dict:
    """Loader for @require -- fetches the venue, raising NotFoundError
    itself for a missing row (see app.authz.decorators' docstring on why
    that's the loader's job). Unlike app.events.routes.load_event this
    doesn't need to wrap the row in a SimpleNamespace/protocol: no venue
    rule reads any attribute off the resource (see rule_venue_view --
    it's role-only, same as rule_venue_list), so the plain dict
    get_venue() already returns is all any caller here ever needs."""
    return get_venue(venue_id)
