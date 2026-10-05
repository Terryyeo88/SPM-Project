"""HTTP route for booking conflict reporting (IS-16):
GET /venues/bookings/<booking_id>/conflicts.

Its own blueprint rather than a route added to app/venues/routes.py, so
IS-16 doesn't edit IS-14's files (PR #18). The path sits under the static
"/venues/bookings" prefix and has more segments than the catalogue's
"/venues/<venue_id>", so neither route can shadow the other.

Gated on VENUE_BOOKING_VIEW: whoever may view a booking (Venue Staff, or
the coordinator who requested it) may see what it clashes with.
"""

from __future__ import annotations

from flask import Blueprint, jsonify

from app.authz.actions import VENUE_BOOKING_VIEW
from app.authz.decorators import require
from app.venues.booking_conflicts import clashes_for_booking
from app.venues.routes import load_booking

booking_conflicts_bp = Blueprint("booking_conflicts", __name__, url_prefix="/venues/bookings")


@booking_conflicts_bp.route("/<booking_id>/conflicts", methods=["GET"])
@require(VENUE_BOOKING_VIEW, loader=lambda booking_id: load_booking(booking_id))
def get_booking_conflicts(booking, booking_id):
    return jsonify(clashes_for_booking(booking)), 200
