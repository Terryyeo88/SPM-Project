"""HTTP routes for the venue catalogue (View Venue Catalogue, Nawaz,
Sprint 1), venue bookings (Venue Booking Request / Approval, Josiah,
Sprint 2), venue blocking (Sprint 3, Josiah), and IS-61's venue CRUD:

  POST   /venues              -- add a venue
  POST   /venues/<venue_id>   -- edit a venue (only the fields sent change,
                                  tentative_hold_minutes included -- Sprint 3)
  DELETE /venues/<venue_id>   -- delete it; releases ongoing events' bookings
  GET    /venues/deleted      -- deleted venues, waiting to be permanently deleted
  DELETE /venues/<venue_id>/permanent -- permanently delete a deleted venue

Booking routes use a static "/bookings" prefix, declared BEFORE the
catalogue's own dynamic "/<venue_id>" route below -- otherwise Flask
would match "/venues/bookings" as "/venues/<venue_id>" with
venue_id="bookings", same static-before-dynamic care already taken for
/events/coordinators vs /events/<event_id>. The blocks routes below
DON'T have this problem -- they're nested UNDER the dynamic segment
(/<venue_id>/blocks), a strictly more specific pattern than the bare
/<venue_id>, so Flask/Werkzeug matches them correctly regardless of
declaration order; still declared after /<venue_id>/calendar for
readability, not because order matters here."""

from __future__ import annotations

from types import SimpleNamespace

from flask import Blueprint, jsonify, request

from app.auth.context import current_user
from app.authz.actions import (
    VENUE_BLOCK,
    VENUE_BOOKING_APPROVE,
    VENUE_BOOKING_CANCEL,
    VENUE_BOOKING_LIST,
    VENUE_BOOKING_OVERWRITE,
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
from app.events.transitions import TransitionConflictError, transition
from app.extensions import supabase
from app.notifications import notification_service
from app.safety.safety_service import withdraw_pending_review
from app.shared.errors import ValidationError
from app.venues.block_service import create_venue_block, list_venue_blocks
from app.venues.booking_release import release_booking
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
    list_deleted_venues,
    list_venues,
    permanently_delete_venue,
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


# Overwrite Venue Booking: Venue Staff directly invalidate a CONFIRMED
# booking with a mandatory reason ("the event will not have an unsuitable
# venue"). Distinct from /cancel above (the coordinator's own action, no
# event-status consequence) and from venue blocking (targets a VENUE for a
# time window, see block_service.py): this is Venue Staff unilaterally
# pulling ONE booking out from under a possibly-already-confirmed event.
#
# Reuses booking_release.release_booking for the actual confirmed ->
# released write -- same race-guard and audit-log shape as every other
# release trigger (cancel, hold expiry, block) -- then, unlike any of
# those, also reverts the EVENT if it had already reached "confirmed" OR
# "safety_review". The AC's own literal wording only says "if the event is
# confirmed", and booking_service._revert_confirmed_event (IS-9's
# cancel_booking, the closest sibling) only reverts "confirmed" -- but the
# team decided (2026-11-03) not to waste a Safety Officer's time reviewing
# a session whose venue Venue Staff just pulled out from under it, so this
# route follows venue_service.delete_venue's broader scope instead (IS-61's
# venue deletion, which also withdraws any pending safety review first --
# its check was for arrangements the session no longer has). See
# docs/design-decisions.md for the full history of this decision: it
# started narrower, matching cancel_booking, until the team weighed in.
# cancel_booking itself still only reverts "confirmed" -- this route
# diverging from it is a deliberate, now-resolved choice, not an
# inconsistency to fix later. Not atomic across the writes (release, then
# withdraw, then transition), same non-atomic-by-design stance every other
# release-plus-status-change in this codebase already takes.
# Static path -- must come before GET /venues/<venue_id> below.
@venues_bp.route("/bookings/<booking_id>/overwrite", methods=["POST"])
@require(VENUE_BOOKING_OVERWRITE, loader=lambda booking_id: load_booking_with_event(booking_id))
def overwrite_venue_booking_route(booking, booking_id):
    body = request.get_json(silent=True) or {}
    reason = body.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError("A reason is required to overwrite a venue booking.")
    reason = reason.strip()

    overwritten = release_booking(booking_id, vars(booking), reason, changed_by=current_user().id)

    reverted = False
    event_status = getattr(booking, "event_status", None)
    if event_status in _OVERWRITE_REVERTS_FROM:
        if event_status == "safety_review":
            # Its pending check was for arrangements it no longer has.
            withdraw_pending_review(booking.event_id, current_user().id, reason)
        try:
            transition(
                booking.event_id,
                "planning",
                current_user().id,
                reason=f"Venue booking overwritten by Venue Staff: {reason}",
                expected_from=event_status,
            )
            reverted = True
        except TransitionConflictError:
            pass  # moved on since (e.g. cancelled) -- the overwrite stands either way

    _notify_booking_overwritten(overwritten, reason)
    return jsonify({**overwritten, "event_reverted_to_planning": reverted}), 200


# Same scope as venue_service's own revert-to-planning set (IS-61's
# delete_venue) -- see the route's own docstring above for why this route
# matches that one, not cancel_booking's narrower "confirmed" only.
_OVERWRITE_REVERTS_FROM = ("confirmed", "safety_review")


def _notify_booking_overwritten(overwritten_booking: dict, reason: str) -> None:
    """Overwrite Venue Booking AC3 (notification_service.venue_booking_overwritten)."""
    notification_service.venue_booking_overwritten(overwritten_booking, reason)


def load_booking_with_event(booking_id: str) -> SimpleNamespace:
    """load_booking plus the booking's event's coordinator_id and status
    (as event_coordinator_id / event_status). rule_venue_booking_cancel
    needs coordinator_id (the event's current coordinator cancels, not
    whoever requested the booking); overwrite_venue_booking_route needs
    event_status (to decide whether to revert the event to planning)."""
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


# IS-61: venues deleted from the catalogue but not yet permanently deleted,
# for Venue Staff to permanently delete. Same action as deleting (venue.delete):
# only those who can delete need to see what's waiting to be removed.
# Static path -- must come before GET /venues/<venue_id> below.
@venues_bp.route("/deleted", methods=["GET"])
@require(VENUE_DELETE)
def list_deleted_venues_route():
    return jsonify(list_deleted_venues()), 200


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


# The second step: remove a venue already deleted from the catalogue. Same
# action as deleting, as IS-60's permanent delete shares room_layout.manage.
@venues_bp.route("/<venue_id>/permanent", methods=["DELETE"])
@require(VENUE_DELETE)
def permanently_delete_venue_route(venue_id):
    permanently_delete_venue(venue_id)
    return "", 204


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
