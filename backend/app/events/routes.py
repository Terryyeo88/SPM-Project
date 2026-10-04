"""
HTTP routes for the events resource -- currently just coordinator
reassignment (Justin's Sprint 1 ticket). Aaralyn's event CRUD/submit
routes belong in this same module/blueprint.

NOT here: an endpoint for assign_initial_coordinator. Per the story ("the
system automatically assigns"), initial assignment isn't a discrete
user-invoked action with its own authorisation action -- there is no
event.assign_coordinator in app/authz/actions.py, and there shouldn't
be, since it fires as a side effect of an event moving to `submitted`,
not as something a caller directly requests. Whoever wires up
EVENT_SUBMIT should call
app.events.coordinator_service.assign_initial_coordinator(event_id)
after a successful submit; nothing does that yet -- that's an open
integration gap to flag to the team, not something guessed at here.
"""

from __future__ import annotations

from types import SimpleNamespace

from flask import Blueprint, jsonify, request

from app.auth.context import current_user
from app.authz.actions import (
    COORDINATOR_LIST,
    EVENT_APPROVE,
    EVENT_CREATE,
    EVENT_DELETE,
    EVENT_EDIT,
    EVENT_LIST,
    EVENT_REASSIGN_COORDINATOR,
    EVENT_REJECT,
    EVENT_SUBMIT,
    EVENT_VIEW,
    VENUE_BOOKING_CREATE,
)
from app.authz.decorators import require
from app.events.coordinator_service import (
    NoCoordinatorAvailableError,
    list_coordinators,
    reassign_coordinator,
)
from app.events.event_service import (
    approve_event_request,
    create_draft_request,
    create_event_request,
    delete_draft_request,
    edit_event_request,
    list_event_requests,
    list_event_sessions,
    reject_event_request,
    save_draft_request,
    submit_event_request,
)
from app.extensions import supabase
from app.shared.errors import NotFoundError, ValidationError
from app.venues.booking_service import create_booking_request, list_bookings_for_event

events_bp = Blueprint("events", __name__, url_prefix="/events")


@events_bp.route("", methods=["GET"])
@require(EVENT_LIST)
def list_events():
    status = request.args.get("status")
    events = list_event_requests(current_user(), status)
    return jsonify(events), 200


# Static path, so Flask matches it ahead of GET /events/<event_id> below.
@events_bp.route("/coordinators", methods=["GET"])
@require(COORDINATOR_LIST)
def list_coordinators_route():
    return jsonify(list_coordinators()), 200


@events_bp.route("", methods=["POST"])
@require(EVENT_CREATE)
def create_event():
    event = create_event_request(current_user().id, request.get_json(silent=True) or {})
    return jsonify(event), 201


@events_bp.route("/draft", methods=["POST"])
@require(EVENT_CREATE)
def create_draft():
    event = create_draft_request(current_user().id, request.get_json(silent=True) or {})
    return jsonify(event), 201


@events_bp.route("/<event_id>", methods=["POST"])
@require(EVENT_EDIT, loader=lambda event_id: load_event(event_id))
def edit_event(event, event_id):
    updated_event = edit_event_request(event_id, event, request.get_json(silent=True) or {})
    return jsonify(updated_event), 200


@events_bp.route("/<event_id>", methods=["GET"])
@require(EVENT_VIEW, loader=lambda event_id: load_event(event_id))
def get_event(event, event_id):
    return jsonify(vars(event)), 200


# Every session of the same request (rows sharing shared_event_id) that the
# caller may see, plus the shared name/description/purpose.
@events_bp.route("/<event_id>/sessions", methods=["GET"])
@require(EVENT_VIEW, loader=lambda event_id: load_event(event_id))
def get_event_sessions(event, event_id):
    return jsonify(list_event_sessions(event, current_user())), 200


# Venue Booking Request (Josiah, Sprint 2). Gated on VENUE_BOOKING_CREATE,
# not EVENT_EDIT -- see rule_venue_booking_create's own status
# precondition (approved/planning), distinct from event.edit's.
@events_bp.route("/<event_id>/venue-bookings", methods=["POST"])
@require(VENUE_BOOKING_CREATE, loader=lambda event_id: load_event(event_id))
def create_venue_booking(event, event_id):
    body = request.get_json(silent=True) or {}
    booking = create_booking_request(event, body.get("venue_id"), current_user().id)
    return jsonify(booking), 201


# Gated on EVENT_VIEW, not VENUE_BOOKING_LIST -- this is "this event's own
# booking history", scoped to one event the caller can already see, not
# the cross-event queue VENUE_BOOKING_LIST/list_bookings guards (see that
# rule's own *** WARNING *** in rules.py).
@events_bp.route("/<event_id>/venue-bookings", methods=["GET"])
@require(EVENT_VIEW, loader=lambda event_id: load_event(event_id))
def get_venue_bookings_for_event(event, event_id):
    return jsonify(list_bookings_for_event(event_id)), 200


@events_bp.route("/<event_id>", methods=["DELETE"])
@require(EVENT_DELETE, loader=lambda event_id: load_event(event_id))
def delete_event(event, event_id):
    delete_draft_request(event_id, event)
    return "", 204


@events_bp.route("/<event_id>/draft", methods=["POST"])
@require(EVENT_EDIT, loader=lambda event_id: load_event(event_id))
def save_draft(event, event_id):
    updated_event = save_draft_request(event_id, event, request.get_json(silent=True) or {})
    return jsonify(updated_event), 200

# event is a SimpleNamespace object representing the loaded event, and event_id is the string
# SimpleNamespace is a small built-in Python object that lets you access dictionary values using dot notation.
# It is only a convenient Python wrapper around the event data.
@events_bp.route("/<event_id>/submit", methods=["POST"])
@require(EVENT_SUBMIT, loader=lambda event_id: load_event(event_id))
def submit_event(event, event_id):
    submitted_event = submit_event_request(event_id, event)
    return jsonify(submitted_event), 200

@events_bp.route("/<event_id>/approve", methods=["POST"])
@require(EVENT_APPROVE, loader=lambda event_id: load_event(event_id))
def approve_event(event, event_id):
    approved = approve_event_request(event_id, event, current_user().id)
    return jsonify(approved), 200


@events_bp.route("/<event_id>/reject", methods=["POST"])
@require(EVENT_REJECT, loader=lambda event_id: load_event(event_id))
def reject_event(event, event_id):
    body = request.get_json(silent=True) or {}
    rejected = reject_event_request(event_id, event, current_user().id, body.get("reason"))
    return jsonify(rejected), 200


# The `load_event` function is a loader for the `@require` decorator.
# It fetches the event from the database and exposes it as an EventLike object (SimpleNamespace)
# so that the policy rule can read it.
# SimpleNamespace(**result.data) makes a SimpleNamespace object from the event data returned by the database query.
# Thus, able to access the event's attributes using dot notation (e.g., event.name, event.description, etc.).
def load_event(event_id: str) -> SimpleNamespace:
    """Loader for @require -- fetches the event and exposes it as an
    EventLike (see app.authz.protocol) so the policy rule can read it.
    Raises NotFoundError itself for a missing row, per @require's own
    docstring on why that's the loader's job: a genuinely missing event
    and one the caller isn't entitled to know about must produce the
    exact same 404."""
    result = supabase.table("events").select("*").eq("id", event_id).maybe_single().execute()
    if result is None or not result.data:
        raise NotFoundError("Event not found.")
    return SimpleNamespace(**result.data)


@events_bp.route("/<event_id>/reassign-coordinator", methods=["POST"])
@require(EVENT_REASSIGN_COORDINATOR, loader=lambda event_id: load_event(event_id))
def reassign_coordinator_route(event, event_id):
    # `@require`'s wrapper forwards the route's own URL kwargs (event_id)
    # to the view alongside the loaded resource -- see
    # tests/test_authz_decorators.py's edit_event example, which is the
    # tested contract. `event_id` isn't needed here (event.id covers it)
    # but the parameter has to exist or Flask can't call this view at all.
    #
    # The loader is wrapped in a lambda (per decorators.py's own docstring
    # example) rather than passed as `loader=load_event` directly -- that
    # would bind this module's *current* `load_event` function object once,
    # at import time, so a test's `monkeypatch.setattr(routes_module,
    # "load_event", ...)` would never be seen by the decorator at all.
    body = request.get_json(silent=True) or {}
    new_coordinator_id = body.get("new_coordinator_id")
    if not new_coordinator_id:
        raise ValidationError("new_coordinator_id is required.")

    # @require has already confirmed the caller IS event.coordinator_id
    # (see rule_event_reassign_coordinator) before this line ever runs --
    # that's the real enforcement now. Passing requested_by here keeps
    # coordinator_service.reassign_coordinator's own existing check
    # satisfied too (defense in depth), without needing to touch that
    # file at all.
    try:
        new_coordinator = reassign_coordinator(
            event_id=event.id,
            new_coordinator_id=new_coordinator_id,
            requested_by=current_user().id,
            reason=body.get("reason"),
        )
    except NoCoordinatorAvailableError as exc:
        raise ValidationError(str(exc)) from exc
    except ValueError as exc:
        raise ValidationError(str(exc)) from exc

    return jsonify({"coordinator": new_coordinator}), 200
