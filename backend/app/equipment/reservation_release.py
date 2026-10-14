"""Release reserved equipment when an event is cancelled (Justin, Sprint 3).

Story: "As a Technical Staff member, I want reserved equipment to be
released automatically when an event is cancelled, so that the stock
becomes available again for other events."

Releasing = deleting the event's `equipment_reservations` rows. Nothing
else has to change for the stock to come back, because availability is
never stored -- app.equipment.equipment_service counts every reservation
row as "unit spoken for" (check_availability, get_equipment's occupancy)
and the database exclusion constraint does the same. Once the rows are
gone, those three all see the units as free for that date and time.

Deleting rather than marking released was chosen so that IS-18's code and
the exclusion constraint stay untouched; the cancellation itself is still
recorded (who, when, why) in event_status_log. See docs/design-decisions.md
section "Release Equipment on Cancel".

The equipment_requests and equipment_request_items rows are kept, so the
event page can still show what was asked for (as "Released").
"""

from __future__ import annotations

from app.extensions import supabase


def release_event_equipment(event_id: str) -> int:
    """Delete every equipment reservation held for this event session and
    return how many units were released. Safe to call on an event with no
    requests or no reservations (returns 0), and safe to call twice."""
    requests = supabase.table("equipment_requests").select("id").eq("event_id", event_id).execute().data or []
    request_ids = [row["id"] for row in requests]
    if not request_ids:
        return 0

    items = supabase.table("equipment_request_items").select("id").in_("request_id", request_ids).execute().data or []
    item_ids = [row["id"] for row in items]
    if not item_ids:
        return 0

    deleted = supabase.table("equipment_reservations").delete().in_("request_item_id", item_ids).execute().data or []
    return len(deleted)
