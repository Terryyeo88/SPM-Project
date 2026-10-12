"""Room layouts (theatre, classroom, ...): the list Venue Staff manage and
event requests pick from. See supabase/migrations/20261012000000_room_layouts.sql
for the table and the triggers behind it.

Deleting is two steps:
  - soft delete (is_active = false): the layout can't be picked for new
    requests any more, but events already using it keep it.
  - permanent delete: only once it's soft-deleted AND every event still
    using it is completed or cancelled. The database enforces both (whoever
    runs the DELETE); this module turns its refusals into a 409. Events that
    used the layout keep its name in events.room_layout.
"""

from __future__ import annotations

from postgrest.exceptions import APIError

from app.extensions import supabase
from app.shared.errors import AppError, NotFoundError, ValidationError

TABLE = "room_layouts"
KEY = "room_layout_id"


class RoomLayoutConflictError(AppError):
    """The change clashes with the layout's current state: a duplicate
    name, or a permanent delete the database refused."""

    status_code = 409
    code = "room_layout_conflict"


def _name_from(body) -> str:
    if not isinstance(body, dict):
        raise ValidationError("The room layout body must be a JSON object.")
    unknown = set(body) - {"name"}
    if unknown:
        raise ValidationError(f"Unknown room layout fields: {', '.join(sorted(unknown))}.")
    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValidationError("name must be a non-empty string.")
    return name.strip()


def _duplicate_name(exc: APIError, name: str) -> None:
    """Unique violation on lower(name) -> 409. The clash may be with a
    soft-deleted layout, which a Venue Staff member can't see in the
    picker -- so the message says to restore it instead."""
    if exc.code == "23505":
        raise RoomLayoutConflictError(
            f'A room layout named "{name}" already exists. If it was deleted, restore it instead.'
        ) from exc


def list_room_layouts(include_inactive: bool = False) -> list[dict]:
    """Active layouts by name; with include_inactive, soft-deleted ones too."""
    query = supabase.table(TABLE).select("*")
    if not include_inactive:
        query = query.eq("is_active", True)
    return query.order("name").execute().data or []


def get_room_layout(room_layout_id: str) -> dict:
    result = supabase.table(TABLE).select("*").eq(KEY, room_layout_id).maybe_single().execute()
    if result is None or not result.data:
        raise NotFoundError("Room layout not found.")
    return result.data


def create_room_layout(body) -> dict:
    name = _name_from(body)
    try:
        result = supabase.table(TABLE).insert({"name": name}).select("*").execute()
    except APIError as exc:
        _duplicate_name(exc, name)
        raise
    return result.data[0] if isinstance(result.data, list) else result.data


def _update(room_layout_id: str, values: dict) -> dict:
    result = supabase.table(TABLE).update(values).eq(KEY, room_layout_id).select("*").execute()
    if not result.data:
        raise NotFoundError("Room layout not found.")
    return result.data[0] if isinstance(result.data, list) else result.data


def rename_room_layout(room_layout_id: str, body) -> dict:
    """Renaming reaches every event still linked to the layout and every
    venue that lists it (database trigger) -- it's the same layout, now
    called something else."""
    name = _name_from(body)
    try:
        return _update(room_layout_id, {"name": name})
    except APIError as exc:
        _duplicate_name(exc, name)
        raise


def soft_delete_room_layout(room_layout_id: str) -> dict:
    return _update(room_layout_id, {"is_active": False})


def restore_room_layout(room_layout_id: str) -> dict:
    return _update(room_layout_id, {"is_active": True})


def delete_room_layout(room_layout_id: str) -> None:
    """Permanently delete a soft-deleted layout that no live event uses.
    The active check is repeated here only for a clearer message; the
    database trigger is what actually enforces both conditions."""
    layout = get_room_layout(room_layout_id)
    if layout["is_active"]:
        raise RoomLayoutConflictError(
            f'Room layout "{layout["name"]}" must be soft-deleted before it can be permanently deleted.'
        )
    try:
        supabase.table(TABLE).delete().eq(KEY, room_layout_id).execute()
    except APIError as exc:
        # 23503: events that aren't completed/cancelled still use it.
        # 23514: it was restored between the check above and the delete.
        if exc.code in ("23503", "23514"):
            raise RoomLayoutConflictError(exc.message) from exc
        raise
