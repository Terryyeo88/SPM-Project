"""HTTP routes for the venue catalogue (View Venue Catalogue, Nawaz,
Sprint 1). Read-only: GET /venues (list, optionally filtered by
?status=) and GET /venues/<venue_id> (single record)."""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.authz.actions import VENUE_LIST, VENUE_VIEW
from app.authz.decorators import require
from app.shared.errors import ValidationError
from app.venues.venue_service import VENUE_STATUSES, get_venue, list_venues

venues_bp = Blueprint("venues", __name__, url_prefix="/venues")


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


def load_venue(venue_id: str) -> dict:
    """Loader for @require -- fetches the venue, raising NotFoundError
    itself for a missing row (see app.authz.decorators' docstring on why
    that's the loader's job). Unlike app.events.routes.load_event this
    doesn't need to wrap the row in a SimpleNamespace/protocol: no venue
    rule reads any attribute off the resource (see rule_venue_view --
    it's role-only, same as rule_venue_list), so the plain dict
    get_venue() already returns is all any caller here ever needs."""
    return get_venue(venue_id)
