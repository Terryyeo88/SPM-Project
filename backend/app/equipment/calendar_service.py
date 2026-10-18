"""Business logic for the equipment availability calendar (IS-47: View
Equipment Availability Calendar). Read-only, and the equipment twin of
app.venues.calendar_service: range parsing, the range filter and the
response shape all come from app.shared.calendar; what is equipment
specific -- which rows, and what state an entry has -- is here.

One state only, "reserved": an equipment_reservations row, i.e. a request
that was accepted and had this specific unit allocated to it. Two states
the wireframe draws are deliberately not built (docs/open-questions.md):

  pending      -- a pending equipment_request names a TYPE and a quantity,
                  not a unit; a unit is allocated only when its reservation
                  row is created. So there is nothing to place on one
                  unit's calendar -- the same reason the venue calendar
                  leaves pending bookings out.
  maintenance  -- there is no dated unavailability for equipment (no
                  equivalent of venue_blocks); equipment_units.status is one
                  current value. It is returned in the resource block for
                  the page's status pill, not as calendar entries.

The rows come from equipment_service.get_equipment, which already joins
each reservation through its request item and request to the event's name.
The route's @require loader fetches the unit that way once, and the loaded
unit is passed in here, so the calendar costs no second round trip.

Two overlap tests now live side by side in the equipment package. This
module filters with app.shared.calendar's CalendarRange.overlaps (the
calendar's: offsets dropped, wall-clock time against whole days, as the
venue calendar does). equipment_service.check_availability keeps its own
_spans_overlap over timezone-aware instants, because it compares two
booked periods, not a period with a calendar page. See
docs/design-decisions.md.
"""

from __future__ import annotations

from app.equipment.equipment_service import _parse_timestamptz
from app.shared.calendar import calendar_envelope, parse_calendar_range


def get_equipment_calendar(unit: dict, start: str, end: str) -> dict:
    """Reservations of `unit` (as returned by
    equipment_service.get_equipment, with its occupancy) whose period
    overlaps the whole days start..end (YYYY-MM-DD, end inclusive).

    Raises ValidationError (400) for a malformed date or an end before the
    start. Returns {equipment: {...}, range: {start, end}, entries: [...]}.
    """
    calendar_range = parse_calendar_range(start, end)

    entries = []
    for reservation in unit.get("occupancy") or []:
        reserved_start = _parse_timestamptz(reservation["reserved_start"])
        reserved_end = _parse_timestamptz(reservation["reserved_end"])
        if not calendar_range.overlaps(reserved_start, reserved_end):
            continue
        entries.append(
            {
                "type": "reservation",
                "state": "reserved",
                "start": reservation["reserved_start"],
                "end": reservation["reserved_end"],
                "event_id": reservation.get("event_id"),
                "event_name": reservation.get("event_name"),
            }
        )

    entries.sort(key=lambda entry: entry["start"])

    # No location: equipment_units has no such column (docs/open-questions.md).
    return calendar_envelope(
        "equipment",
        {
            "id": unit["id"],
            "asset_tag": unit["asset_tag"],
            "type": unit.get("type"),
            "notes": unit.get("notes"),
            "status": unit["status"],
        },
        calendar_range,
        entries,
    )
