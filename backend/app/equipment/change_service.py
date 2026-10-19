"""Update quantity on an existing equipment reservation (Nawaz, Sprint 3,
IS-43).

The Event Coordinator asks to change the quantity on one line of a request
that Technical Support already accepted. The ask is stored as a row in
equipment_change_requests and does NOT touch the confirmed request: until
Technical Support decide it, the reservations stay exactly as they were.

  create_change_request   the coordinator's ask (also "triggers a
                          recalculation": the check is computed fresh
                          whenever the ask is read, see _recalculate)
  list_changes_for_request / list_pending_changes
  accept_change           applies the new quantity: reserves extra units, or
                          releases surplus ones
  reject_change           needs a reason the coordinator can read

Same conventions as accept_request (docs/design-decisions.md): one
reservation row per UNIT, copying the request's needed_start/needed_end,
and availability is counted, never stored.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from postgrest.exceptions import APIError

from app.equipment.equipment_service import (
    _compute_availability,
    _notify_request_decision,
    _one,
    get_request,
)
from app.extensions import supabase
from app.shared.errors import NotFoundError, ValidationError

MAX_REASON_LENGTH = 1000


def _flatten_change(row: dict) -> dict:
    item = _one(row.get("equipment_request_items"))
    request = _one(item.get("equipment_requests"))
    event = _one(request.get("events"))
    return {
        "id": row["id"],
        "request_item_id": row["request_item_id"],
        "request_id": item.get("request_id"),
        "equipment_type_id": item.get("equipment_type_id"),
        "type": _one(item.get("equipment_types")).get("name"),
        "event_name": event.get("name"),
        "requested_by": row["requested_by"],
        "old_quantity": row["old_quantity"],
        "new_quantity": row["new_quantity"],
        "status": row["status"],
        "rejection_reason": row.get("rejection_reason"),
        "decided_at": row.get("decided_at"),
        "created_at": row.get("created_at"),
    }


_CHANGE_SELECT = (
    "*, equipment_request_items(id, request_id, equipment_type_id, quantity, equipment_types(name), "
    "equipment_requests(events(name)))"
)


def _get_change_row(change_id: str) -> dict:
    result = (
        supabase.table("equipment_change_requests").select(_CHANGE_SELECT).eq("id", change_id).maybe_single().execute()
    )
    if result is None or not result.data:
        raise NotFoundError("Change request not found.")
    return dict(result.data)


def load_change_resource(change_id: str) -> SimpleNamespace:
    """The shape @require's loader hands to the policy rules: the change
    plus its request's status and its event's status."""
    change = _flatten_change(_get_change_row(change_id))
    request = get_request(change["request_id"])
    return SimpleNamespace(
        **change,
        request_status=request["status"],
        event_status=request.get("event_status"),
        request_owner=request["requested_by"],
    )


# -- the coordinator's ask ---------------------------------------------------


def create_change_request(request_id: str, item_id, quantity, requested_by: str) -> dict:
    """Record the ask. authz (rule_equipment_change_create) has already
    checked the caller raised the request, it is confirmed, and its event
    is still live."""
    if not isinstance(item_id, str) or not item_id:
        raise ValidationError("Choose which item to change.")
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1:
        raise ValidationError("The new quantity must be a whole number of at least 1.")

    request = get_request(request_id)
    item = next((line for line in request["items"] if line["id"] == item_id), None)
    if item is None:
        raise ValidationError("That item is not part of this request.")
    if quantity == item["quantity"]:
        raise ValidationError(f"The quantity is already {quantity} -- enter a different number.")

    pending = (
        supabase.table("equipment_change_requests")
        .select("id")
        .eq("request_item_id", item_id)
        .eq("status", "pending")
        .execute()
        .data
    )
    if pending:
        raise ValidationError("This item already has a change waiting for Technical Support.")

    try:
        inserted = (
            supabase.table("equipment_change_requests")
            .insert(
                {
                    "request_item_id": item_id,
                    "requested_by": requested_by,
                    "old_quantity": item["quantity"],
                    "new_quantity": quantity,
                }
            )
            .execute()
            .data
        )
    except APIError as exc:
        # The partial unique index: two asks for the same line at once.
        if exc.code == "23505":
            raise ValidationError("This item already has a change waiting for Technical Support.") from exc
        raise
    return _flatten_change(_get_change_row(inserted[0]["id"]))


# -- reading -----------------------------------------------------------------


def _recalculate(change: dict, availability: dict) -> dict:
    """The recalculation the first AC asks for, for ONE pending change.

    `availability` is the request's normal availability check. It already
    leaves the request's own reservations out of "held by others", so
    `available` for the type is the number of units that could cover this
    request in total -- including the ones it already holds. The change is
    therefore accommodated when available >= the NEW quantity. A decrease
    is always accommodated."""
    line = next((i for i in availability["items"] if i["equipment_type_id"] == change["equipment_type_id"]), None)
    available = line["available"] if line else 0
    accommodated = change["new_quantity"] <= change["old_quantity"] or available >= change["new_quantity"]
    return {
        "current": change["old_quantity"],
        "requested": change["new_quantity"],
        "available": available,
        "accommodated": accommodated,
        "shortfall": 0 if accommodated else change["new_quantity"] - available,
    }


def list_changes_for_request(request_id: str) -> list[dict]:
    """Every change asked for on a request, newest first. Pending ones carry
    a fresh `check` so Technical Support see today's availability."""
    request = get_request(request_id)
    item_ids = [item["id"] for item in request["items"]]
    if not item_ids:
        return []
    rows = (
        supabase.table("equipment_change_requests")
        .select(_CHANGE_SELECT)
        .in_("request_item_id", item_ids)
        .order("created_at", desc=True)
        .execute()
        .data
        or []
    )
    changes = [_flatten_change(row) for row in rows]
    if any(change["status"] == "pending" for change in changes):
        availability = _compute_availability(request_id)[0]
        for change in changes:
            if change["status"] == "pending":
                change["check"] = _recalculate(change, availability)
    return changes


def list_pending_changes() -> list[dict]:
    """The Technical Support queue: every pending change, oldest first."""
    rows = (
        supabase.table("equipment_change_requests")
        .select(_CHANGE_SELECT)
        .eq("status", "pending")
        .order("created_at")
        .execute()
        .data
        or []
    )
    return [_flatten_change(row) for row in rows]


# -- deciding ----------------------------------------------------------------


def _claim(change_id: str, fields: dict) -> None:
    """Move the change out of "pending", conditioned on it still being
    pending. Matches no row if someone decided it a moment ago."""
    updated = (
        supabase.table("equipment_change_requests")
        .update({**fields, "decided_at": datetime.now(UTC).isoformat()})
        .eq("id", change_id)
        .eq("status", "pending")
        .select("*")
        .execute()
    )
    if not updated.data:
        raise ValidationError("This change is no longer pending -- refresh to see its current status.")


def _unclaim(change_id: str) -> None:
    supabase.table("equipment_change_requests").update(
        {"status": "pending", "decided_by": None, "decided_at": None}
    ).eq("id", change_id).execute()


def accept_change(change_id: str, decided_by: str) -> dict:
    """Apply the new quantity (AC2: "the event record reflects the new
    reserved quantity"). authz has checked Technical Support, pending, and a
    live event.

    Increase: availability is recalculated and, if the extra units are
    there, one reservation row per extra unit is written (lowest asset tag
    first, copying the request's period). Decrease: the surplus units, the
    highest asset tags, are released. Either way the line's quantity is
    then updated, so the event page and the availability arithmetic agree.

    Order, since there is no transaction through the REST client: write
    the extra reservations (the exclusion constraint is the backstop if
    another request grabs a unit meanwhile), then claim the change
    (conditioned on still pending), then update the line. If a later step
    fails the earlier ones are undone, so a half-applied change is not
    left behind.
    """
    change = _flatten_change(_get_change_row(change_id))
    request = get_request(change["request_id"])
    item = next(line for line in request["items"] if line["id"] == change["request_item_id"])
    old, new = item["quantity"], change["new_quantity"]
    if old != change["old_quantity"]:
        raise ValidationError("The quantity on this item has changed since the ask -- reject it and ask again.")

    own = (
        supabase.table("equipment_reservations")
        .select("id, equipment_id, equipment_units(asset_tag)")
        .eq("request_item_id", item["id"])
        .execute()
        .data
        or []
    )

    inserted_ids: list[str] = []
    released: list[dict] = []
    if new > old:
        result, free_by_type, _ = _compute_availability(change["request_id"])
        line = next(i for i in result["items"] if i["equipment_type_id"] == item["equipment_type_id"])
        if line["available"] < new:
            raise ValidationError(
                f"There is not enough equipment available for that change "
                f"({item['type']}: {new} wanted, {line['available']} available)."
            )
        held_ids = {row["equipment_id"] for row in own}
        extra = [unit for unit in free_by_type[item["equipment_type_id"]] if unit["id"] not in held_ids][: new - old]
        if len(extra) < new - old:
            raise ValidationError("Not enough free units to add -- check availability again.")
        try:
            inserted = (
                supabase.table("equipment_reservations")
                .insert(
                    [
                        {
                            "equipment_id": unit["id"],
                            "request_item_id": item["id"],
                            "reserved_start": request["needed_start"],
                            "reserved_end": request["needed_end"],
                        }
                        for unit in extra
                    ]
                )
                .execute()
                .data
                or []
            )
        except APIError as exc:
            if exc.code in ("23P01", "40P01"):
                raise ValidationError(
                    "Some of that equipment was just reserved for another event -- check availability again."
                ) from exc
            raise
        inserted_ids = [row["id"] for row in inserted]
    elif new < old:
        by_tag = sorted(own, key=lambda row: _one(row.get("equipment_units")).get("asset_tag") or "")
        released = by_tag[new:]

    try:
        _claim(change_id, {"status": "accepted", "decided_by": decided_by})
    except Exception:
        if inserted_ids:
            supabase.table("equipment_reservations").delete().in_("id", inserted_ids).execute()
        raise

    try:
        if released:
            supabase.table("equipment_reservations").delete().in_("id", [row["id"] for row in released]).execute()
        supabase.table("equipment_request_items").update({"quantity": new}).eq("id", item["id"]).execute()
    except Exception:
        _unclaim(change_id)
        if inserted_ids:
            supabase.table("equipment_reservations").delete().in_("id", inserted_ids).execute()
        raise

    _notify_request_decision(change["request_id"], "change accepted")
    return {**_flatten_change(_get_change_row(change_id)), "request": get_request(change["request_id"])}


def reject_change(change_id: str, reason, decided_by: str) -> dict:
    """Reject the change with an explanation the coordinator can read (AC3).
    Nothing is reserved or released; the request stays as it was."""
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError("A reason is required to reject a change.")
    reason = reason.strip()
    if len(reason) > MAX_REASON_LENGTH:
        raise ValidationError(f"The reason is too long (limit {MAX_REASON_LENGTH} characters).")

    change = _flatten_change(_get_change_row(change_id))
    _claim(change_id, {"status": "rejected", "rejection_reason": reason, "decided_by": decided_by})
    _notify_request_decision(change["request_id"], "change rejected")
    return _flatten_change(_get_change_row(change_id))
