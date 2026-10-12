"""HTTP routes for room layouts.

  GET    /room-layouts                    -- active layouts (?include_inactive=true: Venue Staff only)
  POST   /room-layouts                    -- add one          {"name": ...}
  POST   /room-layouts/<id>               -- rename           {"name": ...}
  DELETE /room-layouts/<id>               -- soft delete
  POST   /room-layouts/<id>/restore       -- undo a soft delete
  DELETE /room-layouts/<id>/permanent     -- permanent delete (soft-deleted, no live events)

Everything but the active list is Venue Staff only (room_layout.manage).
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.auth.context import current_user
from app.authz.actions import ROOM_LAYOUT_LIST, ROOM_LAYOUT_MANAGE
from app.authz.decorators import require
from app.authz.policy import authorise
from app.room_layouts.room_layout_service import (
    create_room_layout,
    delete_room_layout,
    list_room_layouts,
    rename_room_layout,
    restore_room_layout,
    soft_delete_room_layout,
)

room_layouts_bp = Blueprint("room_layouts", __name__, url_prefix="/room-layouts")


@room_layouts_bp.route("", methods=["GET"])
@require(ROOM_LAYOUT_LIST)
def list_room_layouts_route():
    include_inactive = request.args.get("include_inactive") == "true"
    if include_inactive:
        authorise(current_user(), ROOM_LAYOUT_MANAGE)
    return jsonify(list_room_layouts(include_inactive)), 200


@room_layouts_bp.route("", methods=["POST"])
@require(ROOM_LAYOUT_MANAGE)
def create_room_layout_route():
    return jsonify(create_room_layout(request.get_json(silent=True))), 201


@room_layouts_bp.route("/<room_layout_id>", methods=["POST"])
@require(ROOM_LAYOUT_MANAGE)
def rename_room_layout_route(room_layout_id):
    return jsonify(rename_room_layout(room_layout_id, request.get_json(silent=True))), 200


@room_layouts_bp.route("/<room_layout_id>", methods=["DELETE"])
@require(ROOM_LAYOUT_MANAGE)
def soft_delete_room_layout_route(room_layout_id):
    return jsonify(soft_delete_room_layout(room_layout_id)), 200


@room_layouts_bp.route("/<room_layout_id>/restore", methods=["POST"])
@require(ROOM_LAYOUT_MANAGE)
def restore_room_layout_route(room_layout_id):
    return jsonify(restore_room_layout(room_layout_id)), 200


@room_layouts_bp.route("/<room_layout_id>/permanent", methods=["DELETE"])
@require(ROOM_LAYOUT_MANAGE)
def delete_room_layout_route(room_layout_id):
    delete_room_layout(room_layout_id)
    return "", 204
