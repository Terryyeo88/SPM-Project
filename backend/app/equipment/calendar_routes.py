"""HTTP route for the equipment availability calendar (IS-47):
GET /equipment/<equipment_id>/calendar?start=YYYY-MM-DD&end=YYYY-MM-DD.

Its own blueprint rather than a route added to app/equipment/routes.py, so
IS-47 doesn't edit IS-18's files -- same reason, and same pattern, as
app/venues/conflict_routes.py. The path has one more segment than
"/equipment/<equipment_id>" and a static last one, so neither route can
shadow the other, and "/equipment/requests/<id>" (static first segment)
still wins for request ids.
"""

from __future__ import annotations

from flask import Blueprint, jsonify, request

from app.authz.actions import EQUIPMENT_CALENDAR_VIEW
from app.authz.decorators import require
from app.equipment.calendar_service import get_equipment_calendar
from app.equipment.equipment_service import get_equipment
from app.shared.errors import NotFoundError, ValidationError

equipment_calendar_bp = Blueprint("equipment_calendar", __name__, url_prefix="/equipment")


# `start`/`end` (YYYY-MM-DD, end inclusive) are both required, as on the
# venue calendar's route: the month shown is the page's choice, not a
# default guessed here.
@equipment_calendar_bp.route("/<equipment_id>/calendar", methods=["GET"])
@require(EQUIPMENT_CALENDAR_VIEW, loader=lambda equipment_id: load_unit(equipment_id))
def get_equipment_calendar_route(unit, equipment_id):
    start = request.args.get("start")
    end = request.args.get("end")
    if not start or not end:
        raise ValidationError("Both 'start' and 'end' query parameters (YYYY-MM-DD) are required.")
    return jsonify(get_equipment_calendar(unit, start, end)), 200


def load_unit(equipment_id: str) -> dict:
    """Loader for @require -- the unit with its occupancy
    (equipment_service.get_equipment), which the calendar then filters, so
    the unit is fetched once. `get_equipment` is looked up through this
    module's namespace so route tests can patch it.

    A missing unit is re-raised with the same message authorise() gives a
    DENY_NOT_FOUND ("Resource not found."), so an unknown unit and a unit
    hidden from a non-staff caller get byte-identical 404s (AC6), not just
    the same status code."""
    try:
        return get_equipment(equipment_id)
    except NotFoundError:
        raise NotFoundError("Resource not found.") from None
