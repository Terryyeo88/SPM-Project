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

from postgrest.exceptions import APIError

from app.extensions import supabase
from app.shared.errors import NotFoundError, ValidationError

# The event's own [start, end) window, reused rather than re-derived so an
# equipment request and a venue booking for the same session can never
# disagree about when "the session" is (Singapore time, missing end time =
# end of day). Private to booking_service by name only.
from app.venues.booking_service import _event_window

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
    query = supabase.table("equipment_units").select(
        "id, asset_tag, status, notes, equipment_type_id, equipment_types(name)"
    )
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
        supabase.table("equipment_units")
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
            "*, events(name, status), "
            "equipment_request_items(id, equipment_type_id, quantity, technical_requirements, equipment_types(name))"
        )
        .eq("id", request_id)
        .maybe_single()
        .execute()
    )
    if result is None or not result.data:
        raise NotFoundError("Equipment request not found.")
    row = dict(result.data)
    event = _one(row.pop("events", None))
    row["event_name"] = event.get("name")
    row["event_status"] = event.get("status")
    row["items"] = [_flatten_item(item) for item in row.pop("equipment_request_items", None) or []]
    return row


def _allocated_units(raw_items: list[dict]) -> list[dict]:
    """A confirmed request's reserved units, one group per equipment type
    (a request holds at most one line per type -- the
    equipment_request_items_one_per_type constraint), types A-Z and units
    by asset tag. `quantity` counts the reservation rows actually held, not
    the quantity asked for: this is what is allocated."""
    groups = []
    for item in raw_items:
        units = [
            {"id": reservation["equipment_id"], "asset_tag": _one(reservation.get("equipment_units")).get("asset_tag")}
            for reservation in item.get("equipment_reservations") or []
        ]
        if not units:
            continue
        units.sort(key=lambda unit: unit["asset_tag"] or "")
        groups.append(
            {
                "equipment_type_id": item["equipment_type_id"],
                "type": _one(item.get("equipment_types")).get("name"),
                "quantity": len(units),
                "units": units,
            }
        )
    groups.sort(key=lambda group: group["type"] or "")
    return groups


def list_requests_for_event(event_id: str) -> list[dict]:
    """Every equipment request raised for one event session, newest first,
    for the Equipment Booking section of the event page (View Reserved
    Equipment story): what was asked for, its status and -- once confirmed
    -- which units are reserved for it.

    Not scoped per caller like list_requests: the route gates on
    EVENT_VIEW for this one event, same split as
    booking_service.list_bookings_for_event (one event's own history vs
    the cross-event queue).

    Each request carries `items` (the lines asked for), `total_quantity`
    (sum of those lines) and `allocated` (_allocated_units; empty unless
    the request is confirmed, since a reservation row only exists once a
    request has been accepted -- see the module docstring)."""
    result = (
        supabase.table("equipment_requests")
        .select(
            "*, equipment_request_items(id, equipment_type_id, quantity, technical_requirements, "
            "equipment_types(name), equipment_reservations(id, equipment_id, equipment_units(asset_tag)))"
        )
        .eq("event_id", event_id)
        .order("created_at", desc=True)
        .execute()
    )
    requests = []
    for source in result.data or []:
        row = dict(source)
        raw_items = row.pop("equipment_request_items", None) or []
        row["items"] = [_flatten_item(item) for item in raw_items]
        row["total_quantity"] = sum(item["quantity"] for item in row["items"])
        row["allocated"] = _allocated_units(raw_items) if row["status"] == "confirmed" else []
        requests.append(row)
    return requests


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


# -- record a request (IS-17) -------------------------------------------------

MAX_REQUIREMENTS_LENGTH = 2000


def list_equipment_types() -> list[dict]:
    """The kinds of equipment a request can name, A-Z. Feeds the request
    form's picker; a type exists whether or not any unit of it does."""
    result = supabase.table("equipment_types").select("id, name").order("name").execute()
    return list(result.data or [])


def _validate_request_items(raw_items) -> list[dict]:
    """The lines of a new request, checked and normalised -- BEFORE
    anything is written, so a bad line leaves nothing half-created.

    AC: "System prevents submitting a request if quantity is missing or
    zero for a selected equipment item". Stricter than that, deliberately:
    quantity must be a whole number (not "3", not 2.5, not true), because
    equipment_request_items.quantity is an integer with check (> 0) and a
    sloppy value would otherwise surface as a database error. One line per
    type (the table's unique(request_id, equipment_type_id)) -- a duplicate
    is rejected, not silently merged, so the coordinator sees the ambiguity.
    """
    if not isinstance(raw_items, list) or not raw_items:
        raise ValidationError("Add at least one equipment item to the request.")
    items = []
    seen = set()
    for index, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            raise ValidationError(f"Item {index} is not valid.")
        type_id = raw.get("equipment_type_id")
        if not isinstance(type_id, str) or not type_id.strip():
            raise ValidationError(f"Item {index}: choose an equipment type.")
        type_id = type_id.strip()
        if type_id in seen:
            raise ValidationError("Each equipment type can only appear once; combine the quantities instead.")
        seen.add(type_id)
        quantity = raw.get("quantity")
        if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
            raise ValidationError(f"Item {index}: quantity must be a whole number of at least 1.")
        requirements = raw.get("technical_requirements")
        if requirements is not None and not isinstance(requirements, str):
            raise ValidationError(f"Item {index}: technical requirements must be text.")
        requirements = (requirements or "").strip() or None
        if requirements and len(requirements) > MAX_REQUIREMENTS_LENGTH:
            raise ValidationError(
                f"Item {index}: technical requirements are too long (limit {MAX_REQUIREMENTS_LENGTH} characters)."
            )
        items.append({"equipment_type_id": type_id, "quantity": quantity, "technical_requirements": requirements})
    return items


def create_request(event: SimpleNamespace, raw_items, requested_by: str) -> dict:
    """Record Equipment Request for Event (IS-17): a new "pending" request
    for one event session, with one line per kind of equipment.

    authz (rule_equipment_request_create) has already checked the caller is
    the event's assigned coordinator and the event is in "planning".

    The needed period is the session's own window, snapshotted onto the
    request (see the migration's comment on needed_start/needed_end) --
    the coordinator does not type dates, because the request is for THIS
    session and its date and time are already on the event.

    Two inserts (the request, then its lines) with no transaction available
    through the REST client, so if the lines fail the request row is
    deleted again: a request with no lines would sit in Technical Support's
    queue asking for nothing. Nothing here reserves a unit -- accepting is
    the separate Reservation story -- so there is nothing else to undo.
    """
    items = _validate_request_items(raw_items)

    wanted = [item["equipment_type_id"] for item in items]
    found = supabase.table("equipment_types").select("id").in_("id", wanted).execute()
    known = {row["id"] for row in (found.data or [])}
    if any(type_id not in known for type_id in wanted):
        raise ValidationError("One of the equipment types does not exist.")

    needed_start, needed_end = _event_window(event)
    created = (
        supabase.table("equipment_requests")
        .insert(
            {
                "event_id": event.id,
                "requested_by": requested_by,
                "status": "pending",
                "needed_start": needed_start.isoformat(),
                "needed_end": needed_end.isoformat(),
            }
        )
        .select("*")
        .execute()
    )
    if not created.data:
        raise ValidationError("The equipment request database operation did not return a request.")
    request_row = created.data[0] if isinstance(created.data, list) else created.data

    try:
        supabase.table("equipment_request_items").insert(
            [{**item, "request_id": request_row["id"]} for item in items]
        ).execute()
    except Exception:
        supabase.table("equipment_requests").delete().eq("id", request_row["id"]).execute()
        raise

    return get_request(request_row["id"])


# -- availability check (the story) -----------------------------------------


def check_availability(request_id: str) -> dict:
    """The availability check as the API returns it; see
    _compute_availability for what is in each item."""
    return _compute_availability(request_id)[0]


def _compute_availability(request_id: str) -> tuple[dict, dict[str, list[dict]], dict]:
    """Returns (the check result, the free units per equipment type, the
    request). The free units carry their ids, which accepting a request
    needs to reserve them and which the API result deliberately leaves
    out (it lists asset tags).

    For each equipment type on the request: how many are requested, how
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
            supabase.table("equipment_units")
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
    free_by_type: dict[str, list[dict]] = {}
    for item in items:
        units = units_by_type.get(item["equipment_type_id"], [])
        out_of_service = [unit for unit in units if unit["status"] != "available"]
        usable = [unit for unit in units if unit["status"] == "available"]
        free = [unit for unit in usable if unit["id"] not in held]
        conflicts = [
            {"asset_tag": unit["asset_tag"], **hold} for unit in usable for hold in held.get(unit["id"], [])
        ]
        available = len(free)
        free_by_type[item["equipment_type_id"]] = free
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

    result = {
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
    return result, free_by_type, request


# -- accept a request and reserve stock (IS-19) -----------------------------


def accept_request(request_id: str) -> dict:
    """Accept an equipment request and reserve stock (IS-19): the request
    becomes "confirmed" and a specific unit is reserved for every piece of
    equipment it asks for.

    authz (rule_equipment_request_accept) has already checked the caller is
    Technical Support Staff, the request is "pending" (AC: "Only requests
    in a pending status can be accepted") and its event is still in
    planning (a cancelled or moved-on event must not take stock).

    Follows the conventions the event page and the release story already
    rely on (docs/design-decisions.md, "Conventions this relies on"):
      1. one reservation row per UNIT, not per quantity;
      2. the request becomes "confirmed" when its reservation rows are
         written, never before;
      3. each reservation copies the request's needed_start/needed_end, so
         "available quantity ... scoped to the event's date and time" falls
         out of the existing availability arithmetic with no stored count.

    Refuses outright when any line cannot be covered (IS-41 is the story
    that turns this into a warning with a reject); nothing is reserved in
    that case, so a request is accepted whole or not at all.

    Units are taken lowest asset tag first, so which units a request gets
    is predictable. There is no transaction through the REST client, so
    the order is: reserve the units, then flip the status conditioned on
    the request still being "pending". If the status flip finds nothing to
    update (two people accepting at once) the units just reserved are
    deleted again. The database exclusion constraint is the backstop if
    two DIFFERENT requests race for the same unit: it refuses the second
    insert and nothing is half-reserved.
    """
    result, free_by_type, request = _compute_availability(request_id)
    if not result["all_sufficient"]:
        short = "; ".join(
            f"{item['type']}: {item['requested']} requested, {item['available']} available"
            for item in result["items"]
            if not item["sufficient"]
        )
        raise ValidationError(f"There is not enough equipment available for this request ({short}).")

    reservations = []
    allocated = []
    for item in request["items"]:
        chosen = free_by_type[item["equipment_type_id"]][: item["quantity"]]
        allocated.append(
            {
                "equipment_type_id": item["equipment_type_id"],
                "type": item["type"],
                "quantity": len(chosen),
                "units": [{"id": unit["id"], "asset_tag": unit["asset_tag"]} for unit in chosen],
            }
        )
        reservations.extend(
            {
                "equipment_id": unit["id"],
                "request_item_id": item["id"],
                "reserved_start": request["needed_start"],
                "reserved_end": request["needed_end"],
            }
            for unit in chosen
        )

    try:
        inserted = supabase.table("equipment_reservations").insert(reservations).execute().data or []
    except APIError as exc:
        # The exclusion constraint refused: another request took one of
        # these units for an overlapping period between the check above and
        # this write. 40P01 when both reached it before either committed.
        if exc.code in ("23P01", "40P01"):
            raise ValidationError(
                "Some of that equipment was just reserved for another event -- check availability again."
            ) from exc
        raise

    try:
        updated = (
            supabase.table("equipment_requests")
            .update({"status": "confirmed"})
            .eq("id", request_id)
            .eq("status", "pending")
            .select("*")
            .execute()
        )
        if not updated.data:
            raise ValidationError("This request is no longer pending -- refresh to see its current status.")
    except Exception:
        reserved_ids = [row["id"] for row in inserted]
        if reserved_ids:
            supabase.table("equipment_reservations").delete().in_("id", reserved_ids).execute()
        raise

    _notify_request_decision(request_id, "confirmed")
    return {**get_request(request_id), "allocated": allocated}


MAX_REJECTION_REASON_LENGTH = 1000


def reject_request(request_id: str, reason, decided_by: str) -> dict:
    """Reject an equipment request with an explanation (IS-41): the request
    becomes "rejected" and the coordinator can read why.

    authz (rule_equipment_request_reject) has already checked the caller is
    Technical Support Staff and the request is "pending".

    AC: "Rejecting requires an explanation that's sent to the Event
    Coordinator". The reason is required (blank or whitespace-only is
    refused) and stored on the request (see the migration), where the
    coordinator's Equipment Booking section reads it. "Sent" is the
    notification placeholder below plus that visibility: no notification
    system exists yet.

    Nothing is reserved while a request is pending, so there is nothing to
    release. The update is conditioned on the request still being
    "pending", same race-proofing as accept_request: if someone accepted it
    a moment ago this matches no row and says so, instead of overwriting a
    confirmed request (and its reservations) with a rejection.
    """
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError("A reason is required to reject an equipment request.")
    reason = reason.strip()
    if len(reason) > MAX_REJECTION_REASON_LENGTH:
        raise ValidationError(f"The reason is too long (limit {MAX_REJECTION_REASON_LENGTH} characters).")

    updated = (
        supabase.table("equipment_requests")
        .update(
            {
                "status": "rejected",
                "rejection_reason": reason,
                "decided_by": decided_by,
                "decided_at": datetime.now(UTC).isoformat(),
            }
        )
        .eq("id", request_id)
        .eq("status", "pending")
        .select("*")
        .execute()
    )
    if not updated.data:
        raise ValidationError("This request is no longer pending -- refresh to see its current status.")

    _notify_request_decision(request_id, "rejected")
    return get_request(request_id)


def _notify_request_decision(request_id: str, decision: str) -> None:
    """Hook for the Notification System story. No-op placeholder, same
    shape as booking_service._notify_booking_decision -- no notification
    plumbing exists anywhere in this codebase yet."""
    print(f"[notify] equipment request {request_id} {decision}")
