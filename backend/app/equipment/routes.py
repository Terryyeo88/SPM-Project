"""HTTP routes for Check Equipment Availability (Nawaz, Sprint 2, IS-18).
All read-only.

  GET /equipment                              -- every unit (?type=, ?status=)
  GET /equipment/requests                     -- requests the caller may see (?status=)
  GET /equipment/requests/<id>                -- one request, with its lines
  GET /equipment/requests/<id>/availability   -- the availability check
  GET /equipment/<id>                         -- one unit plus its occupancy

The static "/requests" paths are declared BEFORE the dynamic "/<id>" one,
otherwise Flask would match "/equipment/requests" as "/equipment/<id>"
with id="requests" -- same static-before-dynamic care as /venues/bookings.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.auth.context import current_user
from app.authz.actions import (
    EQUIPMENT_LIST,
    EQUIPMENT_REQUEST_CHECK_AVAILABILITY,
    EQUIPMENT_REQUEST_LIST,
    EQUIPMENT_REQUEST_VIEW,
    EQUIPMENT_VIEW,
)
from app.authz.decorators import require
from app.equipment.equipment_service import (
    check_availability,
    get_equipment,
    list_equipment,
    list_requests,
    load_request_resource,
)

equipment_bp = Blueprint("equipment", __name__, url_prefix="/equipment")


@equipment_bp.route("", methods=["GET"])
@require(EQUIPMENT_LIST)
def list_equipment_route():
    return jsonify(list_equipment(request.args.get("type"), request.args.get("status"))), 200


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


@equipment_bp.route("/<equipment_id>", methods=["GET"])
@require(EQUIPMENT_VIEW)
def get_equipment_route(equipment_id):
    return jsonify(get_equipment(equipment_id)), 200


def load_request(request_id: str):
    """Loader for @require -- fetches the request (raising NotFoundError
    for a missing row) as an EquipmentRequestLike for the policy rules.
    Looked up through this module-level name so route tests can patch it."""
    return load_request_resource(request_id)
