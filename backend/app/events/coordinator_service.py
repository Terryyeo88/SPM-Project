"""
Coordinator Assignment — initial auto-assignment.

Implements "Coordinator is initially assigned to event" (Coordinator
Assignment, Justin, Sprint 1). Acceptance criteria from the user stories
doc, for reference:

  - When an event requires coordinator assignment, the system
    automatically assigns an Event Coordinator.
  - Each event has no more than one Event Coordinator assigned at a time.
  - The assigned Event Coordinator is associated with the relevant event.
  - The assigned Event Coordinator can access the event information
    required to coordinate the event.
  - Assumption noted in the doc: a coordinator needs to be physically
    present, so the system must check they're not already occupied
    (assigned to another active event) at that date/time.

Design decisions made here that the spec deliberately leaves open (per
the Week2/Week4 clarifications: "detail implementation is up to the team
as long as it is fair and technically possible"):

  - "Requires coordinator assignment" = event.status == 'submitted' and
    event.coordinator_id is null.
  - Availability = no OTHER active event (status in ACTIVE_STATUSES)
    already assigned to that coordinator overlaps this event's full
    [preferred_start_date+time, preferred_end_date+time) span (see
    _event_span) -- covers same-day, overnight, and any-length-under-
    24h events uniformly, not just an exact-date match.
  - Selection = workload-based: among the available coordinators, pick
    whoever currently has the fewest active assigned events. This is
    "fair" without needing seniority/experience data, which the client
    clarification explicitly said isn't required.
  - If every coordinator is occupied, the event is left unassigned
    rather than double-booking someone -- the client hasn't specified
    what should happen in that case, so this is flagged as an open
    question rather than guessed at.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional

from app.extensions import supabase

# Statuses that count as "this coordinator is actively on the hook for
# this event" -- draft/rejected/cancelled/completed don't block a slot.
ACTIVE_STATUSES = ("under_review", "approved", "planning", "confirmed")


class NoCoordinatorAvailableError(Exception):
    """Raised when every Event Coordinator is occupied on the event's date."""


def _parse_date(value: Optional[str]) -> Optional[date]:
    return date.fromisoformat(value) if value else None


def _parse_time(value: Optional[str]) -> Optional[time]:
    return time.fromisoformat(value) if value else None


def _event_span(event: dict) -> tuple[datetime, datetime]:
    """The full [start, end) datetime span this event occupies, for
    availability-overlap purposes.

    - A missing preferred_end_date means an ordinary same-day event --
      it falls back to preferred_start_date, per event_service.py's own
      "no end date given" convention.
    - A missing preferred_start_time/preferred_end_time is treated as
      the start/end of that day (time.min / time.max), so a date-only
      event still correctly blocks the whole day(s) it's on -- same
      convention the old date-only check used.

    Combining into real datetimes (rather than comparing dates and times
    separately) is what makes an overnight event -- e.g. 22:00 day 1 to
    06:00 day 2 -- correctly overlap something starting at 23:00 on day
    1 or ending at 01:00 on day 2, even though those pairs don't share a
    single preferred_start_date.
    """
    start_date = _parse_date(event["preferred_start_date"])
    end_date = _parse_date(event.get("preferred_end_date")) or start_date
    start_time = _parse_time(event.get("preferred_start_time")) or time.min
    end_time = _parse_time(event.get("preferred_end_time")) or time.max
    return datetime.combine(start_date, start_time), datetime.combine(end_date, end_time)


def _spans_overlap(a: dict, b: dict) -> bool:
    """True if two events' full date/time spans overlap at all."""
    a_start, a_end = _event_span(a)
    b_start, b_end = _event_span(b)
    return a_start < b_end and b_start < a_end


def _get_event(event_id: str) -> dict:
    result = supabase.table("events").select("*").eq("id", event_id).single().execute()
    if not result.data:
        raise ValueError(f"Event {event_id} not found")
    return result.data


def _get_all_coordinators() -> list[dict]:
    """All profiles holding the event_coordinator role."""
    result = (
        supabase.table("user_roles")
        .select("user_id, profiles(id, name, email)")
        .eq("role", "event_coordinator")
        .execute()
    )
    return [row["profiles"] for row in result.data if row.get("profiles")]


def _get_active_events_for_coordinator(coordinator_id: str, exclude_event_id: str) -> list[dict]:
    result = (
        supabase.table("events")
        .select(
            "id, preferred_start_date, preferred_end_date, "
            "preferred_start_time, preferred_end_time, status"
        )
        .eq("coordinator_id", coordinator_id)
        .neq("id", exclude_event_id)
        .in_("status", ACTIVE_STATUSES)
        .execute()
    )
    return result.data


def _is_available(coordinator_id: str, event: dict) -> bool:
    """A coordinator is available if none of their other active events'
    date/time spans (see _event_span) overlap this event's span."""
    for other in _get_active_events_for_coordinator(coordinator_id, event["id"]):
        if _spans_overlap(event, other):
            return False
    return True


def _workload(coordinator_id: str) -> int:
    """Number of events currently actively assigned to this coordinator --
    used to pick the least-loaded coordinator for a fair auto-assignment."""
    result = (
        supabase.table("events")
        .select("id", count="exact")
        .eq("coordinator_id", coordinator_id)
        .in_("status", ACTIVE_STATUSES)
        .execute()
    )
    return result.count or 0


def _notify_coordinator_assigned(event: dict, coordinator: dict) -> None:
    """Hook for the Notification System story (also Justin, later sprint).
    No-op placeholder for now -- swap this for the real notification call
    once that story exists."""
    print(f"[notify] {coordinator['name']} assigned to event '{event['name']}'")


def _get_coordinator_profile(coordinator_id: str) -> dict:
    """Fetch a profile and confirm it holds the event_coordinator role."""
    result = (
        supabase.table("user_roles")
        .select("profiles(id, name, email)")
        .eq("user_id", coordinator_id)
        .eq("role", "event_coordinator")
        .execute()
    )
    if not result.data or not result.data[0].get("profiles"):
        raise ValueError(f"User {coordinator_id} is not an Event Coordinator.")
    return result.data[0]["profiles"]


def assign_initial_coordinator(event_id: str) -> dict:
    """
    Auto-assign an Event Coordinator to the given event.

    Returns the assigned coordinator's profile dict (id, name, email).

    Raises:
        ValueError                  - event not found, or already has a coordinator
        NoCoordinatorAvailableError - no coordinators exist, or all are occupied
    """
    event = _get_event(event_id)

    if event.get("coordinator_id"):
        raise ValueError(
            f"Event {event_id} already has a coordinator assigned "
            "(use the reassignment flow instead)."
        )

    coordinators = _get_all_coordinators()
    if not coordinators:
        raise NoCoordinatorAvailableError("No users hold the event_coordinator role yet.")

    available = [c for c in coordinators if _is_available(c["id"], event)]
    if not available:
        raise NoCoordinatorAvailableError(
            f"Every coordinator is already occupied on {event.get('preferred_start_date')}."
        )

    # Fair, workload-based pick: fewest active events first, stable tiebreak by id.
    chosen = min(available, key=lambda c: (_workload(c["id"]), c["id"]))

    supabase.table("events").update(
        {
            "coordinator_id": chosen["id"],
            # Assignment is what moves a submitted request into review,
            # per Event Status Management (Aaralyn) / Week4 clarification.
            "status": "under_review" if event["status"] == "submitted" else event["status"],
        }
    ).eq("id", event_id).execute()

    supabase.table("coordinator_assignment_log").insert(
        {
            "event_id": event_id,
            "previous_coordinator_id": None,
            "new_coordinator_id": chosen["id"],
            "reason": "initial auto-assignment",
        }
    ).execute()

    _notify_coordinator_assigned(event, chosen)

    return chosen


def reassign_coordinator(
    event_id: str,
    new_coordinator_id: str,
    requested_by: Optional[str] = None,
    reason: Optional[str] = None,
) -> dict:
    """
    Reassign an event's Event Coordinator to someone else.

    Implements "Coordinator needs reassignment": the event keeps exactly
    one coordinator throughout, the new one takes over, and the previous
    one is fully unassigned. Per the Week4 clarifications, the actual
    decision to hand off happens OFFLINE between coordinators ("the
    original co-ordinator can make the change and request the new
    co-ordinator to accept the change... detail process and UI
    implementation is up to the team") -- so this function just records
    the outcome once it's agreed; it doesn't run any in-system
    approval/accept step, and a coordinator can't decline via the system
    either (also confirmed in the clarifications).

    Args:
        event_id: the event being reassigned.
        new_coordinator_id: profile id of the incoming coordinator.
        requested_by: profile id of whoever is making the change. If
            given, this is enforced to be the event's CURRENT
            coordinator, per the clarification above. Pass None to skip
            this check (e.g. before auth/roles are wired up, or for an
            admin override).
        reason: optional free-text reason, stored in the audit log.

    Returns the new coordinator's profile dict (id, name, email).

    Raises:
        ValueError                  - event or new coordinator not found; event has
                                       no existing coordinator yet (use
                                       assign_initial_coordinator instead); new
                                       coordinator is the same as the current one;
                                       requested_by isn't the current coordinator;
                                       or new_coordinator_id doesn't hold the
                                       event_coordinator role
        NoCoordinatorAvailableError - the new coordinator is already occupied on
                                       that date
    """
    event = _get_event(event_id)
    previous_coordinator_id = event.get("coordinator_id")

    if not previous_coordinator_id:
        raise ValueError(
            f"Event {event_id} has no coordinator yet -- "
            "use assign_initial_coordinator instead."
        )

    if requested_by and requested_by != previous_coordinator_id:
        raise ValueError("Only the currently assigned coordinator can reassign this event.")

    if new_coordinator_id == previous_coordinator_id:
        raise ValueError("Event is already assigned to that coordinator.")

    new_coordinator = _get_coordinator_profile(new_coordinator_id)

    if not _is_available(new_coordinator_id, event):
        raise NoCoordinatorAvailableError(
            f"{new_coordinator['name']} is already occupied on {event.get('preferred_start_date')}."
        )

    # coordinator_id is a single column, so this update alone enforces
    # "no more than one coordinator at a time" and "previous coordinator
    # is no longer assigned" in one step. Status is deliberately left
    # untouched -- reassignment doesn't change where the event is in its
    # lifecycle, only who's running it.
    supabase.table("events").update(
        {"coordinator_id": new_coordinator_id}
    ).eq("id", event_id).execute()

    supabase.table("coordinator_assignment_log").insert(
        {
            "event_id": event_id,
            "previous_coordinator_id": previous_coordinator_id,
            "new_coordinator_id": new_coordinator_id,
            "reason": reason or "reassignment",
        }
    ).execute()

    _notify_coordinator_assigned(event, new_coordinator)

    return new_coordinator
