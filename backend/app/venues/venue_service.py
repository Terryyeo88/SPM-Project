"""Business logic for the venue catalogue (View Venue Catalogue, Nawaz,
Sprint 1), plus Venue Staff setting which room layouts a venue supports.

A venue's layouts live in venue_room_layouts (see
supabase/migrations/20261012100000_venue_room_layouts.sql). Every venue this
module returns carries them two ways:
  supported_layouts       -- layout names, what event checks compare against
  supported_room_layouts  -- [{room_layout_id, name, is_active}], for editing
Soft-deleted layouts stay listed: the room can still be set up that way, and
an event that kept a soft-deleted layout must still match its venue."""

from __future__ import annotations

import uuid

from app.extensions import supabase
from app.shared.errors import NotFoundError, ValidationError

VENUE_STATUSES = {"available", "occupied", "maintenance"}

# The venue plus its layouts, through the join table.
VENUE_SELECT = "*, venue_room_layouts(room_layouts(room_layout_id, name, is_active))"
# What another table's embed of a venue needs to know its layouts' names.
VENUE_LAYOUTS_EMBED = "venue_room_layouts(room_layouts(name))"


def supported_layout_names(venue: dict) -> list[str]:
    """Layout names from a venue row fetched with the venue_room_layouts
    embed (VENUE_SELECT or VENUE_LAYOUTS_EMBED), sorted."""
    names = []
    for link in venue.get("venue_room_layouts") or []:
        layout = link.get("room_layouts") or {}
        if isinstance(layout, list):  # tolerate a one-element list embed
            layout = layout[0] if layout else {}
        if layout.get("name"):
            names.append(layout["name"])
    return sorted(names)


def _with_layouts(row: dict) -> dict:
    venue = dict(row)
    layouts = []
    for link in venue.pop("venue_room_layouts", None) or []:
        layout = link.get("room_layouts") or {}
        if isinstance(layout, list):
            layout = layout[0] if layout else {}
        if layout.get("room_layout_id"):
            layouts.append(
                {"room_layout_id": layout["room_layout_id"], "name": layout["name"], "is_active": layout["is_active"]}
            )
    layouts.sort(key=lambda layout: layout["name"])
    venue["supported_room_layouts"] = layouts
    venue["supported_layouts"] = [layout["name"] for layout in layouts]
    return venue


def list_venues(status: str | None = None) -> list[dict]:
    """Every venue in the catalogue, optionally filtered to one
    availability status. No per-caller scoping here (unlike
    events.list_event_requests) -- see rule_venue_list's docstring: the
    catalogue is shared inventory, not scoped to who is asking."""
    query = supabase.table("venues").select(VENUE_SELECT)
    if status is not None:
        query = query.eq("status", status)
    result = query.order("name").execute()
    return [_with_layouts(row) for row in result.data or []]


def get_venue(venue_id: str) -> dict:
    result = supabase.table("venues").select(VENUE_SELECT).eq("id", venue_id).maybe_single().execute()
    if result is None or not result.data:
        raise NotFoundError("Venue not found.")
    return _with_layouts(result.data)


def _room_layout_ids(body) -> set[str]:
    if not isinstance(body, dict):
        raise ValidationError("The request body must be a JSON object.")
    unknown = set(body) - {"room_layout_ids"}
    if unknown:
        raise ValidationError(f"Unknown fields: {', '.join(sorted(unknown))}.")
    ids = body.get("room_layout_ids")
    if not isinstance(ids, list) or any(not isinstance(value, str) for value in ids):
        raise ValidationError("room_layout_ids must be a list of room layout ids.")
    for value in ids:
        try:
            uuid.UUID(value)
        except ValueError as exc:
            raise ValidationError(f"Unknown room layout id: {value}.") from exc
    return set(ids)


def set_venue_room_layouts(venue_id: str, body) -> dict:
    """Venue Staff set exactly which layouts this venue supports
    ({"room_layout_ids": [...]}) and get the venue back.

    Only active layouts can be ADDED; a soft-deleted one the venue already
    lists may stay. Not one transaction (supabase-py has none), so new links
    are written before old ones are removed: a failure part-way leaves an
    extra layout listed, never a missing one."""
    wanted = _room_layout_ids(body)
    get_venue(venue_id)  # 404 for an unknown venue

    current_rows = (
        supabase.table("venue_room_layouts").select("room_layout_id").eq("venue_id", venue_id).execute().data or []
    )
    current = {row["room_layout_id"] for row in current_rows}

    added = wanted - current
    if added:
        found = (
            supabase.table("room_layouts")
            .select("room_layout_id, name, is_active")
            .in_("room_layout_id", sorted(added))
            .execute()
            .data
            or []
        )
        by_id = {row["room_layout_id"]: row for row in found}
        missing = sorted(added - by_id.keys())
        if missing:
            raise ValidationError(f"Unknown room layout id: {missing[0]}.")
        retired = sorted(by_id[layout_id]["name"] for layout_id in added if not by_id[layout_id]["is_active"])
        if retired:
            raise ValidationError(f"Soft-deleted room layouts can't be added to a venue: {', '.join(retired)}.")
        supabase.table("venue_room_layouts").insert(
            [{"venue_id": venue_id, "room_layout_id": layout_id} for layout_id in sorted(added)]
        ).execute()

    removed = current - wanted
    if removed:
        (
            supabase.table("venue_room_layouts")
            .delete()
            .eq("venue_id", venue_id)
            .in_("room_layout_id", sorted(removed))
            .execute()
        )

    return get_venue(venue_id)
