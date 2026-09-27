"""Business logic for the venue catalogue (View Venue Catalogue, Nawaz,
Sprint 1). Read-only in Sprint 1 -- no create/edit/delete here because no
story asks for it yet (see app/authz/actions.py's venues section)."""

from __future__ import annotations

from app.extensions import supabase
from app.shared.errors import NotFoundError

VENUE_STATUSES = {"available", "occupied", "maintenance"}


def list_venues(status: str | None = None) -> list[dict]:
    """Every venue in the catalogue, optionally filtered to one
    availability status. No per-caller scoping here (unlike
    events.list_event_requests) -- see rule_venue_list's docstring: the
    catalogue is shared inventory, not scoped to who is asking."""
    query = supabase.table("venues").select("*")
    if status is not None:
        query = query.eq("status", status)
    result = query.order("name").execute()
    return result.data or []


def get_venue(venue_id: str) -> dict:
    result = supabase.table("venues").select("*").eq("id", venue_id).maybe_single().execute()
    if result is None or not result.data:
        raise NotFoundError("Venue not found.")
    return result.data
