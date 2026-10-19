"""HTTP routes for Check Equipment Availability (Nawaz, Sprint 2, IS-18).
All read-only.

  GET /equipment                              -- every unit (?type=, ?status=)
  GET /equipment/types                        -- the kinds of equipment a request can name
  GET /equipment/requests                     -- requests the caller may see (?status=)
  GET /equipment/requests/<id>                -- one request, with its lines
  GET /equipment/requests/<id>/availability   -- the availability check
  POST /equipment/requests/<id>/accept        -- accept and reserve stock (IS-19)
  POST /equipment/requests/<id>/reject        -- reject with a reason (IS-41)
  GET /equipment/requests/<id>/change-requests  -- quantity changes asked for (IS-43)
  POST /equipment/requests/<id>/change-requests -- coordinator asks to change a line's quantity
  GET /equipment/change-requests               -- Technical Support's pending queue
  POST /equipment/change-requests/<id>/accept   -- apply the new quantity
  POST /equipment/change-requests/<id>/reject   -- reject with a reason
  GET /equipment/<id>                         -- one unit plus its occupancy

The static "/requests" paths are declared BEFORE the dynamic "/<id>" one,
otherwise Flask would match "/equipment/requests" as "/equipment/<id>"
with id="requests" -- same static-before-dynamic care as /venues/bookings.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.auth.context import current_user
from app.authz.actions import (
    EQUIPMENT_CHANGE_ACCEPT,
    EQUIPMENT_CHANGE_CREATE,
    EQUIPMENT_CHANGE_LIST,
    EQUIPMENT_CHANGE_REJECT,
    EQUIPMENT_LIST,
    EQUIPMENT_REQUEST_ACCEPT,
    EQUIPMENT_REQUEST_CHECK_AVAILABILITY,
    EQUIPMENT_REQUEST_LIST,
    EQUIPMENT_REQUEST_REJECT,
    EQUIPMENT_REQUEST_VIEW,
    EQUIPMENT_TYPE_LIST,
    EQUIPMENT_VIEW,
)
from app.authz.decorators import require
from app.equipment.change_service import (
    accept_change,
    create_change_request,
    list_changes_for_request,
    list_pending_changes,
    load_change_resource,
    reject_change,
)
from app.equipment.equipment_service import (
    accept_request,
    check_availability,
    get_equipment,
    list_equipment,
    list_equipment_types,
    list_requests,
    load_request_resource,
    reject_request,
)

equipment_bp = Blueprint("equipment", __name__, url_prefix="/equipment")


@equipment_bp.route("", methods=["GET"])
@require(EQUIPMENT_LIST)
def list_equipment_route():
    return jsonify(list_equipment(request.args.get("type"), request.args.get("status"))), 200


# Static path -- must come before GET /equipment/<equipment_id> below.
@equipment_bp.route("/types", methods=["GET"])
@require(EQUIPMENT_TYPE_LIST)
def list_equipment_types_route():
    return jsonify(list_equipment_types()), 200


# Static path -- must come before GET /equipment/<equipment_id> below.
@equipment_bp.route("/requests", methods=["GET"])
@require(EQUIPMENT_REQUEST_LIST)
def list_equipment_requests_route():
    return jsonify(list_requests(current_user(), request.args.get("status"))), 200


# Static path -- must come before GET /equipment/<equipment_id> below.
@equipment_bp.route("/requests/<request_id>", methods=["GET"])
@require(EQUIPMENT_REQUEST_VIEW, loader=lambda request_id: load_request(request_id))
def get_equipment_request_route(equipment_request, request_id):
    return jsonify(vars(equipment_request)), 200


# Static path -- must come before GET /equipment/<equipment_id> below.
@equipment_bp.route("/requests/<request_id>/availability", methods=["GET"])
@require(EQUIPMENT_REQUEST_CHECK_AVAILABILITY, loader=lambda request_id: load_request(request_id))
def check_equipment_request_availability_route(equipment_request, request_id):
    return jsonify(check_availability(request_id)), 200


# Static path -- must come before GET /equipment/<equipment_id> below.
@equipment_bp.route("/requests/<request_id>/accept", methods=["POST"])
@require(EQUIPMENT_REQUEST_ACCEPT, loader=lambda request_id: load_request(request_id))
def accept_equipment_request_route(equipment_request, request_id):
    return jsonify(accept_request(request_id)), 200


# Static path -- must come before GET /equipment/<equipment_id> below.
@equipment_bp.route("/requests/<request_id>/reject", methods=["POST"])
@require(EQUIPMENT_REQUEST_REJECT, loader=lambda request_id: load_request(request_id))
def reject_equipment_request_route(equipment_request, request_id):
    body = request.get_json(silent=True) or {}
    return jsonify(reject_request(request_id, body.get("reason"), current_user().id)), 200


# IS-43. Static paths -- before GET /equipment/<equipment_id> below.
@equipment_bp.route("/requests/<request_id>/change-requests", methods=["GET"])
@require(EQUIPMENT_REQUEST_VIEW, loader=lambda request_id: load_request(request_id))
def list_request_changes_route(equipment_request, request_id):
    return jsonify(list_changes_for_request(request_id)), 200


@equipment_bp.route("/requests/<request_id>/change-requests", methods=["POST"])
@require(EQUIPMENT_CHANGE_CREATE, loader=lambda request_id: load_request(request_id))
def create_request_change_route(equipment_request, request_id):
    body = request.get_json(silent=True) or {}
    created = create_change_request(request_id, body.get("item_id"), body.get("quantity"), current_user().id)
    return jsonify(created), 201


@equipment_bp.route("/change-requests", methods=["GET"])
@require(EQUIPMENT_CHANGE_LIST)
def list_pending_changes_route():
    return jsonify(list_pending_changes()), 200


@equipment_bp.route("/change-requests/<change_id>/accept", methods=["POST"])
@require(EQUIPMENT_CHANGE_ACCEPT, loader=lambda change_id: load_change_resource(change_id))
def accept_change_route(change, change_id):
    return jsonify(accept_change(change_id, current_user().id)), 200


@equipment_bp.route("/change-requests/<change_id>/reject", methods=["POST"])
@require(EQUIPMENT_CHANGE_REJECT, loader=lambda change_id: load_change_resource(change_id))
def reject_change_route(change, change_id):
    body = request.get_json(silent=True) or {}
    return jsonify(reject_change(change_id, body.get("reason"), current_user().id)), 200


@equipment_bp.route("/<equipment_id>", methods=["GET"])
@require(EQUIPMENT_VIEW)
def get_equipment_route(equipment_id):
    return jsonify(get_equipment(equipment_id)), 200


def load_request(request_id: str):
    """Loader for @require -- fetches the request (raising NotFoundError
    for a missing row) as an EquipmentRequestLike for the policy rules.
    Looked up through this module-level name so route tests can patch it."""
    return load_request_resource(request_id)
