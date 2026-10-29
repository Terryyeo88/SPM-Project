"""IS-9 Update Event Information During Planning.

"As an Event Coordinator, I want to update an event's information while it
is being planned so that the record stays the single accurate version
everyone works from."

POST /events/<id> (event.edit) writes the update; POST
/events/<id>/update-preview runs the same checks and writes nothing, so the
page can show the coordinator what the update touches before they commit.

  who      rule_event_edit: the assigned coordinator, until the event is
           completed or cancelled (refused with the reason, via
           explain_event_edit_denial). The organiser edits only their own
           draft or rejected request; everyone else who can see the event
           (the Lead) may view it, not edit it.
  checks   The update is merged onto the session's current details and
           validated as a complete request (the event was submitted
           once), so a partial update is still checked against the fields
           it didn't send. Validation runs before anything is written: a
           refused update leaves the event exactly as it was.
  impact   From planning on (IMPACT_CHECKED_STATUSES): which arrangements
           already made the change touches (venue bookings, equipment
           requests, registrations -- "arrangements" in the preview), and
           what it disturbs among them (plus technical support; "impacts";
           both from app.events.change_impact). Every affected area must be named in
           `acknowledge_impacts` or nothing is written (409). While the
           event is under review or approved the coordinator edits freely:
           nothing is checked or needs acknowledging.
  log      One event_logs entry: what changed (from -> to), who, when,
           "significant" or "ordinary" (event_log.SIGNIFICANT_FIELDS), and
           the impacts acknowledged.
  status   A change to a confirmed event sends it back to planning
           (confirmed -> planning through transition(), with the changed
           fields as the reason in event_status_log).

Name, description and purpose are shared by every session of a request, so
a change to them is applied to the other sessions too (except completed or
cancelled ones, which are read-only), and a confirmed sibling goes back to
planning as well. Venue bookings and equipment requests are never written
here: a change to one arrangement never removes another.

Not one transaction (supabase-py has none to offer): the event write is
conditional on the status the caller was authorised against, so an update
racing a status change is a 409, never an overwrite; the log row and the
status change follow it as separate calls, the trade-off
transitions.transition documents.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.events.change_impact import assess_change_impact, check_acknowledged, touched_arrangements
from app.events.event_log import SIGNIFICANT_FIELDS, comparable, record_event_change, significance
from app.events.event_service import (
    EVENT_FIELDS,
    SHARED_FIELDS,
    _from_database_event,
    _to_database_payload,
    validate_event_payload,
)
from app.events.transitions import transition
from app.extensions import supabase
from app.shared.errors import AppError, ValidationError

# Statuses a coordinator's change can no longer reach (rule_event_edit's
# _COORDINATOR_EDIT_CLOSED), applied to sibling sessions authz never saw.
READ_ONLY_STATUSES = frozenset({"completed", "cancelled"})
# Statuses in which the coordinator's update is checked against the
# arrangements already made. Before planning (under review, approved) the
# details are still being settled, so the coordinator edits them freely.
# Narrower than change_impact.ARRANGED_STATUSES, which IS-21 change requests
# still use from approval on.
# safety_review (Week 7 change #6): arrangements are confirmed by then, so
# edits are checked against them just as in planning and confirmed.
IMPACT_CHECKED_STATUSES = frozenset({"planning", "safety_review", "confirmed"})

_FIELD_LABELS = {
    "name": "name",
    "description": "description",
    "purpose": "purpose",
    "preferred_start_date": "start date",
    "preferred_end_date": "end date",
    "preferred_start_time": "start time",
    "preferred_end_time": "end time",
    "expected_attendance": "expected attendance",
    "accessibility_needs": "accessibility needs",
    "room_layout": "room layout",
    "equipment": "equipment",
    "registration_needs": "registration",
    "registration_start_datetime": "registration opening",
    "registration_end_datetime": "registration closing",
    "special_requests": "special requests",
}


class EventUpdateConflictError(AppError):
    """The event changed status (or was removed) between loading it and
    writing the update. Refresh and retry deliberately; never retried here."""

    status_code = 409
    code = "event_update_conflict"


def _validated(event: SimpleNamespace, payload) -> dict:
    """The session's details with `payload` applied, validated. Raises
    ValidationError (and writes nothing) if they don't hold together."""
    if not isinstance(payload, dict):
        raise ValidationError("The event update body must be a JSON object.")
    unknown = set(payload) - EVENT_FIELDS
    if unknown:
        raise ValidationError(f"Unknown event fields: {', '.join(sorted(unknown))}.")
    # Without NULLs: "not set" is what NULL means, and validation refuses a
    # present-but-None special_requests.
    current = {field: value for field, value in _from_database_event(event).items() if value is not None}
    return validate_event_payload(
        {**current, **payload},
        # A draft may be half-filled; anything past it has been submitted.
        for_submission=event.status != "draft",
        current_room_layout=getattr(event, "room_layout", None),
    )


def _changes(event: SimpleNamespace, validated: dict) -> dict:
    """field -> new value, for every detail the update actually changes."""
    current = _from_database_event(event)
    return {
        field: validated.get(field)
        for field in sorted(EVENT_FIELDS)
        if comparable(field, validated.get(field)) != comparable(field, current.get(field))
    }


def describe_fields(fields) -> str:
    return ", ".join(_FIELD_LABELS.get(field, field) for field in sorted(fields))


def _impacts(event: SimpleNamespace, changes: dict) -> list[dict]:
    if not changes or event.status not in IMPACT_CHECKED_STATUSES:
        return []
    return assess_change_impact(event, changes)


def _arrangements(event: SimpleNamespace, changes: dict) -> list[dict]:
    if not changes or event.status not in IMPACT_CHECKED_STATUSES:
        return []
    return touched_arrangements(event, changes)


def revert_to_planning(event_id: str, status: str, changed_fields, actor: str | None) -> dict | None:
    """IS-9: a change to a confirmed event's details sends it back to
    planning. Returns the updated row, or None if it wasn't confirmed."""
    if status != "confirmed":
        return None
    return transition(
        event_id,
        "planning",
        actor,
        reason=f"Event details changed after confirmation ({describe_fields(changed_fields)}).",
        expected_from="confirmed",
    )


def apply_shared_details(event: SimpleNamespace, shared_changes: dict, actor: str | None) -> None:
    """Writes a changed name/description/purpose to the request's other
    sessions -- those still open to changes -- and sends any confirmed one
    back to planning. Logged once, by the caller, for the whole request."""
    if not shared_changes or not getattr(event, "shared_event_id", None):
        return
    siblings = (
        supabase.table("events")
        .select("id, status")
        .eq("shared_event_id", event.shared_event_id)
        .eq("organizer_id", event.organizer_id)
        .neq("id", event.id)
        .execute()
        .data
        or []
    )
    for sibling in siblings:
        if sibling["status"] in READ_ONLY_STATUSES:
            continue
        written = (
            supabase.table("events")
            .update(shared_changes)
            .eq("id", sibling["id"])
            .eq("status", sibling["status"])
            .execute()
        )
        if written.data:
            revert_to_planning(sibling["id"], sibling["status"], shared_changes, actor)


def preview_event_update(event: SimpleNamespace, payload) -> dict:
    """What saving `payload` would do, without writing anything:

        {"changes": {field: {"from", "to"}},
         "significance": "significant" | "ordinary" | None,
         "significant_fields": [...],
         "impacts": [...],            # see app.events.change_impact
         "arrangements": [...],       # every arrangement it touches, conflict
                                      # or not (change_impact.touched_arrangements)
         "impacts_checked": bool,     # False before planning: edited freely
         "reverts_to_planning": bool}

    Raises ValidationError exactly as the update itself would."""
    validated = _validated(event, payload)
    changes = _changes(event, validated)
    current = _from_database_event(event)
    return {
        "changes": {field: {"from": current.get(field), "to": value} for field, value in changes.items()},
        "significance": significance(changes),
        "significant_fields": sorted(set(changes) & SIGNIFICANT_FIELDS),
        "impacts": _impacts(event, changes),
        "arrangements": _arrangements(event, changes),
        "impacts_checked": event.status in IMPACT_CHECKED_STATUSES,
        "reverts_to_planning": bool(changes) and event.status == "confirmed",
    }


def update_event(event: SimpleNamespace, payload, updated_by: str, acknowledge_impacts=None) -> dict:
    """Applies an update to one session and returns its row as it now is
    (status included, if it went back to planning). An update that changes
    nothing writes nothing.

    Raises:
      ValidationError                  the update doesn't validate
      ChangeImpactNotAcknowledgedError an affected arrangement wasn't named
                                       in `acknowledge_impacts`
      EventUpdateConflictError         the event left its status meanwhile
    """
    validated = _validated(event, payload)
    changes = _changes(event, validated)
    if not changes:
        return dict(vars(event))

    impacts = _impacts(event, changes)
    check_acknowledged(impacts, acknowledge_impacts)

    written = (
        supabase.table("events")
        .update(_to_database_payload(validated))
        .eq("id", event.id)
        .eq("status", event.status)
        .select("*")
        .execute()
    )
    if not written.data:
        raise EventUpdateConflictError(
            "This event was changed or removed while you were editing it -- refresh to see its current details."
        )
    updated = written.data[0]

    if event.status != "draft":  # drafts haven't been submitted to anyone yet
        record_event_change(event, updated, updated_by, impacts or None)
    # Only the coordinator's update reaches the other sessions: an organiser
    # fixing a rejected session must not rename sessions already decided.
    if updated_by == getattr(event, "coordinator_id", None):
        apply_shared_details(event, {field: changes[field] for field in SHARED_FIELDS if field in changes}, updated_by)
    return revert_to_planning(event.id, event.status, changes, updated_by) or updated
