"""Business logic for Check Equipment Availability (Nawaz, Sprint 2, IS-18).
Read-only: nothing here creates, accepts, rejects or releases a request or
a reservation -- those are the separate "Record Equipment Request" and
"Accept an equipment request and reserve stock" stories. See
supabase/migrations/20261008000000_equipment.sql's header for the tables
this reads and why they look the way they do.

UNIT LEVEL (AC: "Track equipment based on unit level"): every physical item
is its own `equipment` row. "How many are available" is never a stored
number -- it is counted, per equipment type, from the units that can be
lent out at all (status "available") minus the units some OTHER request has
reserved for an overlapping period. That also means the answer can say
WHICH units are free and WHICH event is holding the rest, not just a count.

What counts as "allocated to other confirmed event requests" (AC4): an
`equipment_reservations` row exists only once a request has been accepted
(the Reservation story's job), so any reservation row is a confirmed
allocation. This module deliberately does not re-check the owning
request's status as well -- a reservation row for a request that somehow
was not confirmed is an inconsistency, and the safe reading of it is "that
unit is physically spoken for", not "ignore it and risk double-allocating".
A request's OWN reservations (relevant when checking an already-confirmed
request) are excluded, so a confirmed request does not report itself as
competing with itself.

Overlap is half-open, [start, end): a unit returned at 14:00 is free for a
request starting at 14:00. Same rule as booking_service._spans_overlap and
the database exclusion constraint on equipment_reservations.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.extensions import supabase
from app.shared.errors import NotFoundError, ValidationError

EQUIPMENT_STATUSES = {"available", "maintenance", "retired"}
REQUEST_STATUSES = {"pending", "confirmed", "rejected"}


def _parse_timestamptz(value: str) -> datetime:
    """Same normalisation as booking_service._parse_timestamptz (the "Z"
    replace), plus: a value with no offset is read as UTC, so comparing it
    with an aware one cannot raise."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _spans_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def _one(embedded):
    """A many-to-one PostgREST embed comes back as a dict; tolerate a
    one-element list and a missing embed (None) too."""
    if isinstance(embedded, list):
        return embedded[0] if embedded else {}
    return embedded or {}


# -- equipment records -------------------------------------------------------


def list_equipment(type_name: str | None = None, status: str | None = None) -> list[dict]:
    """Every unit, optionally narrowed to one equipment type name and/or one
    unit status. Shared inventory, so no per-caller scoping (see
    rule_equipment_list)."""
    if status is not None and status not in EQUIPMENT_STATUSES:
        raise ValidationError(f"status must be one of: {', '.join(sorted(EQUIPMENT_STATUSES))}.")
    query = supabase.table("equipment").select("id, asset_tag, status, notes, equipment_type_id, equipment_types(name)")
    if status is not None:
        query = query.eq("status", status)
    rows = query.order("asset_tag").execute().data or []
    units = [
        {
            "id": row["id"],
            "asset_tag": row["asset_tag"],
            "status": row["status"],
            "notes": row.get("notes"),
            "equipment_type_id": row["equipment_type_id"],
            "type": _one(row.get("equipment_types")).get("name"),
        }
        for row in rows
    ]
    if type_name is not None:
        units = [unit for unit in units if unit["type"] == type_name]
    return units


def get_equipment(equipment_id: str) -> dict:
    """One unit plus its occupancy (AC6): every reservation on it, with the
    event it is held for and the period, soonest first. Only the event's id
    and name are selected, never the full event row -- same
    "only what the viewer is entitled to" discipline as
    calendar_service's events(name, status) embed."""
    result = (
        supabase.table("equipment")
        .select("id, asset_tag, status, notes, equipment_type_id, equipment_types(name)")
        .eq("id", equipment_id)
        .maybe_single()
        .execute()
    )
    if result is None or not result.data:
        raise NotFoundError("Equipment not found.")
    row = result.data

    reservations_result = (
        supabase.table("equipment_reservations")
        .select(
            "id, reserved_start, reserved_end, "
            "equipment_request_items(request_id, equipment_requests(event_id, events(name)))"
        )
        .eq("equipment_id", equipment_id)
        .order("reserved_start")
        .execute()
    )
    occupancy = []
    for reservation in reservations_result.data or []:
        request = _one(_one(reservation.get("equipment_request_items")).get("equipment_requests"))
        occupancy.append(
            {
                "reservation_id": reservation["id"],
                "reserved_start": reservation["reserved_start"],
                "reserved_end": reservation["reserved_end"],
                "request_id": _one(reservation.get("equipment_request_items")).get("request_id"),
                "event_id": request.get("event_id"),
                "event_name": _one(request.get("events")).get("name"),
            }
        )

    return {
        "id": row["id"],
        "asset_tag": row["asset_tag"],
        "status": row["status"],
        "notes": row.get("notes"),
        "equipment_type_id": row["equipment_type_id"],
        "type": _one(row.get("equipment_types")).get("name"),
        "occupancy": occupancy,
    }


# -- equipment requests ------------------------------------------------------


def _flatten_item(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "equipment_type_id": item["equipment_type_id"],
        "type": _one(item.get("equipment_types")).get("name"),
        "quantity": item["quantity"],
        "technical_requirements": item.get("technical_requirements"),
    }


def get_request(request_id: str) -> dict:
    """One request with its lines and the event's name (AC1: select a
    request and view the required date and time; AC5: still viewable
    later -- it is a stored row, not a transient result)."""
    result = (
        supabase.table("equipment_requests")
        .select(
            "*, events(name), "
            "equipment_request_items(id, equipment_type_id, quantity, technical_requirements, equipment_types(name))"
        )
        .eq("id", request_id)
        .maybe_single()
        .execute()
    )
    if result is None or not result.data:
        raise NotFoundError("Equipment request not found.")
    row = dict(result.data)
    row["event_name"] = _one(row.pop("events", None)).get("name")
    row["items"] = [_flatten_item(item) for item in row.pop("equipment_request_items", None) or []]
    return row


def list_requests(user, status: str | None = None) -> list[dict]:
    """Every request the caller is entitled to see, scoped per role -- the
    role-only authz check (rule_equipment_request_list) does NOT mean
    "every request"; this per-row scoping is the real gate, same
    division of labour as booking_service.list_bookings:
      - technical_support_staff sees every request
      - event_coordinator sees requests THEY raised
    A user holding both sees the union, i.e. everything."""
    if status is not None and status not in REQUEST_STATUSES:
        raise ValidationError(f"status must be one of: {', '.join(sorted(REQUEST_STATUSES))}.")

    roles = set(user.roles)
    if "technical_support_staff" not in roles and "event_coordinator" not in roles:
        # Defence in depth behind the rule; fail closed.
        return []

    query = supabase.table("equipment_requests").select(
        "*, events(name), equipment_request_items(quantity, equipment_types(name))"
    )
    if "technical_support_staff" not in roles:
        query = query.eq("requested_by", user.id)
    if status is not None:
        query = query.eq("status", status)
    rows = query.order("created_at", desc=True).execute().data or []

    requests = []
    for source in rows:
        row = dict(source)
        row["event_name"] = _one(row.pop("events", None)).get("name")
        row["items"] = [
            {"type": _one(item.get("equipment_types")).get("name"), "quantity": item["quantity"]}
            for item in row.pop("equipment_request_items", None) or []
        ]
        requests.append(row)
    return requests


def load_request_resource(request_id: str) -> SimpleNamespace:
    """The shape @require's loader hands to the policy rules."""
    return SimpleNamespace(**get_request(request_id))


# -- availability check (the story) -----------------------------------------


def check_availability(request_id: str) -> dict:
    """For each equipment type on the request: how many are requested, how
    many units are available for the request's date/time, and whether that
    is enough (AC2, AC3, AC4).

    Per item:
      requested          -- quantity asked for
      total_units        -- every unit of this type, whatever its state
      out_of_service     -- units whose status is not "available"
      reserved_by_others -- usable units reserved for an overlapping period
                            by a DIFFERENT request
      available          -- total_units - out_of_service - reserved_by_others
      sufficient         -- available >= requested
      shortfall          -- how many short, 0 when sufficient
      available_units    -- asset tags of the units that are free
      conflicts          -- which units are held, for which event, and when
    """
    request = get_request(request_id)
    needed_start = _parse_timestamptz(request["needed_start"])
    needed_end = _parse_timestamptz(request["needed_end"])
    items = request["items"]

    type_ids = sorted({item["equipment_type_id"] for item in items})
    units_by_type: dict[str, list[dict]] = {type_id: [] for type_id in type_ids}
    if type_ids:
        units = (
            supabase.table("equipment")
            .select("id, asset_tag, status, equipment_type_id")
            .in_("equipment_type_id", type_ids)
            .order("asset_tag")
            .execute()
            .data
            or []
        )
        for unit in units:
            units_by_type[unit["equipment_type_id"]].append(unit)

    usable_unit_ids = [
        unit["id"] for units in units_by_type.values() for unit in units if unit["status"] == "available"
    ]
    # unit id -> overlapping reservations by OTHER requests
    held: dict[str, list[dict]] = {}
    if usable_unit_ids:
        reservations = (
            supabase.table("equipment_reservations")
            .select(
                "id, equipment_id, reserved_start, reserved_end, "
                "equipment_request_items(request_id, equipment_requests(event_id, events(name)))"
            )
            .in_("equipment_id", usable_unit_ids)
            .execute()
            .data
            or []
        )
        for reservation in reservations:
            owning_item = _one(reservation.get("equipment_request_items"))
            if owning_item.get("request_id") == request_id:
                continue
            if not _spans_overlap(
                needed_start,
                needed_end,
                _parse_timestamptz(reservation["reserved_start"]),
                _parse_timestamptz(reservation["reserved_end"]),
            ):
                continue
            owning_request = _one(owning_item.get("equipment_requests"))
            held.setdefault(reservation["equipment_id"], []).append(
                {
                    "event_id": owning_request.get("event_id"),
                    "event_name": _one(owning_request.get("events")).get("name"),
                    "reserved_start": reservation["reserved_start"],
                    "reserved_end": reservation["reserved_end"],
                }
            )

    checked = []
    for item in items:
        units = units_by_type.get(item["equipment_type_id"], [])
        out_of_service = [unit for unit in units if unit["status"] != "available"]
        usable = [unit for unit in units if unit["status"] == "available"]
        free = [unit for unit in usable if unit["id"] not in held]
        conflicts = [
            {"asset_tag": unit["asset_tag"], **hold} for unit in usable for hold in held.get(unit["id"], [])
        ]
        available = len(free)
        checked.append(
            {
                "equipment_type_id": item["equipment_type_id"],
                "type": item["type"],
                "requested": item["quantity"],
                "total_units": len(units),
                "out_of_service": len(out_of_service),
                "reserved_by_others": len(usable) - len(free),
                "available": available,
                "sufficient": available >= item["quantity"],
                "shortfall": max(item["quantity"] - available, 0),
                "available_units": [unit["asset_tag"] for unit in free],
                "conflicts": conflicts,
            }
        )

    return {
        "request": {
            "id": request["id"],
            "status": request["status"],
            "event_id": request["event_id"],
            "event_name": request["event_name"],
            "needed_start": request["needed_start"],
            "needed_end": request["needed_end"],
        },
        "items": checked,
        "all_sufficient": all(entry["sufficient"] for entry in checked),
    }
