"""HTTP routes for the venue catalogue (View Venue Catalogue, Nawaz,
Sprint 1), venue bookings (Venue Booking Request / Approval, Josiah,
Sprint 2), and (Sprint 3, Josiah) venue settings editing + venue blocking.
Read-only catalogue: GET /venues (list, optionally filtered by ?status=)
and GET /venues/<venue_id> (single record).

Booking routes use a static "/bookings" prefix, declared BEFORE the
catalogue's own dynamic "/<venue_id>" route below -- otherwise Flask
would match "/venues/bookings" as "/venues/<venue_id>" with
venue_id="bookings", same static-before-dynamic care already taken for
/events/coordinators vs /events/<event_id>. The settings/blocks routes
below DON'T have this problem -- they're nested UNDER the dynamic
segment (/<venue_id>/settings, /<venue_id>/blocks), a strictly more
specific pattern than the bare /<venue_id>, so Flask/Werkzeug matches
them correctly regardless of declaration order; still declared after
/<venue_id>/calendar for readability, not because order matters here."""

from __future__ import annotations

from types import SimpleNamespace

from flask import Blueprint, jsonify, request

from app.auth.context import current_user
from app.authz.actions import (
    VENUE_BLOCK,
    VENUE_BOOKING_APPROVE,
    VENUE_BOOKING_LIST,
    VENUE_BOOKING_REJECT,
    VENUE_BOOKING_VIEW,
    VENUE_CALENDAR_VIEW,
    VENUE_LIST,
    VENUE_MANAGE,
    VENUE_VIEW,
)
from app.authz.decorators import require
from app.shared.errors import ValidationError
from app.venues.block_service import create_venue_block, list_venue_blocks
from app.venues.booking_service import (
    BOOKING_STATUSES,
    confirm_booking,
    get_booking,
    list_bookings,
    reject_booking,
)
from app.venues.calendar_service import get_venue_calendar
from app.venues.venue_service import VENUE_STATUSES, get_venue, list_venues, update_venue_settings

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


# Request Venue Booking with Setup and Turnaround Time (Josiah, Sprint 3,
# Week 7 #1) -- Venue Staff edit a venue's own timing settings. No loader
# needed (role-only, like room_layout.manage) -- an unknown venue_id 404s
# from inside update_venue_settings itself.
@venues_bp.route("/<venue_id>/settings", methods=["POST"])
@require(VENUE_MANAGE)
def update_venue_settings_route(venue_id):
    return jsonify(update_venue_settings(venue_id, request.get_json(silent=True))), 200


# Venue Becomes Unavailable After Booking (Josiah, Sprint 3, Week 7 #2).
@venues_bp.route("/<venue_id>/blocks", methods=["GET"])
@require(VENUE_BLOCK)
def list_venue_blocks_route(venue_id):
    return jsonify(list_venue_blocks(venue_id)), 200


@venues_bp.route("/<venue_id>/blocks", methods=["POST"])
@require(VENUE_BLOCK)
def create_venue_block_route(venue_id):
    return jsonify(create_venue_block(venue_id, request.get_json(silent=True), current_user().id)), 201


def load_venue(venue_id: str) -> dict:
    """Loader for @require -- fetches the venue, raising NotFoundError
    itself for a missing row (see app.authz.decorators' docstring on why
    that's the loader's job). Unlike app.events.routes.load_event this
    doesn't need to wrap the row in a SimpleNamespace/protocol: no venue
    rule reads any attribute off the resource (see rule_venue_view --
    it's role-only, same as rule_venue_list), so the plain dict
    get_venue() already returns is all any caller here ever needs."""
    return get_venue(venue_id)
