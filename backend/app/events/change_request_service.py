"""Business logic for IS-21 Request for Event Change.

"As an Event Organiser, I want to request changes to an event, so that the
event details can be updated when requirements change."

Once a request is submitted the organiser can no longer edit it
(rule_event_edit: draft/rejected only). Instead they file a CHANGE REQUEST:
the fields they want changed and the new values. It is recorded in
public.event_change_requests against the whole event request
(shared_event_id) and the session that needs to change (event_id), and
nothing on public.events moves until the assigned coordinator reviews it:

    approve -> the requested values are written to the event, and what
               changed is logged in public.event_logs (app.events.event_log)
    reject  -> nothing is written; the coordinator's reason is kept

That is how "Given that an event is confirmed, the Event Organiser cannot
directly overwrite the current confirmed event details" holds: the
requested values sit in event_change_requests, never in events, until
approved.

Request body (POST /events/<id>/change-requests):
    {"changes": {<field>: <new value>, ...}, "reason": "optional why"}
Fields are the same names the event API already uses (EVENT_FIELDS), so a
change is validated exactly like an edit: merged onto the session's current
details and checked as a complete request (for_submission=True), since the
event has already been submitted once.

Name, description and purpose are shared by every session of a request
(see app.events.event_service), so an approved change to one of those is
applied to every session; every other field is per session and only
changes the session the request was filed against.

Callers authorise first (EVENT_REQUEST_CHANGE / EVENT_REVIEW_CHANGE /
EVENT_VIEW via @require); this module trusts that `event` is one the caller
may act on, the same trust boundary event_service uses.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.authz.actions import EVENT_VIEW
from app.authz.policy import can
from app.events.change_impact import assess_change_impact
from app.events.event_log import comparable, group_id, record_event_change, record_requested_change
from app.events.event_service import (
    EVENT_FIELDS,
    SHARED_FIELDS,
    _first_row,
    _from_database_event,
    _to_database_payload,
    validate_event_payload,
)
from app.extensions import supabase
from app.shared.errors import AppError, NotFoundError, ValidationError

TABLE = "event_change_requests"
KEY = "event_change_req_id"  # the table's primary key
REQUEST_BODY_FIELDS = {"changes", "reason"}


class ChangeImpactNotAcknowledgedError(AppError):
    """Approving would disturb arrangements already made for the session
    (see app.events.change_impact) that the coordinator hasn't acknowledged
    -- including one that appeared after they loaded the page."""

    status_code = 409
    code = "change_impact_unacknowledged"


class ChangeRequestConflictError(AppError):
    """The change request isn't in the state this action needs: another one
    is already waiting for review, or this one was already decided (a
    double click, or a decision from another tab)."""

    status_code = 409
    code = "change_request_conflict"


def _current_details(event: SimpleNamespace) -> dict:
    """The session's current details in API field names, without NULLs --
    validate_event_payload treats a present-but-None special_requests as
    invalid, and "not set" is what NULL means here anyway."""
    return {field: value for field, value in _from_database_event(event).items() if value is not None}


def _validated_details(event: SimpleNamespace, changes: dict) -> dict:
    """The session's details with `changes` applied, validated as a complete
    request. Raises ValidationError with the usual field messages."""
    return validate_event_payload({**_current_details(event), **changes}, for_submission=True)


def _clean_text(value, field: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValidationError(f"{field} must be a string.")
    return value.strip() if isinstance(value, str) and value.strip() else None


def _pending_for(event_id: str) -> list[dict]:
    result = supabase.table(TABLE).select("*").eq("event_id", event_id).eq("status", "pending").execute()
    return result.data or []


def request_event_change(event: SimpleNamespace, requested_by: str, payload) -> dict:
    """Records a pending change request for this session and returns it.

    Only fields whose value actually changes are recorded (including a
    knock-on change validation makes, e.g. turning registration off clears
    the registration window). `previous_values` snapshots what those
    fields were, so the coordinator reviews a before/after."""
    if not isinstance(payload, dict):
        raise ValidationError("The change request body must be a JSON object.")
    unknown = set(payload) - REQUEST_BODY_FIELDS
    if unknown:
        raise ValidationError(f"Unknown change request fields: {', '.join(sorted(unknown))}.")
    changes = payload.get("changes")
    if not isinstance(changes, dict) or not changes:
        raise ValidationError("changes must be an object naming at least one event detail to change.")
    unknown = set(changes) - EVENT_FIELDS
    if unknown:
        raise ValidationError(f"These event details can't be changed: {', '.join(sorted(unknown))}.")
    reason = _clean_text(payload.get("reason"), "reason")

    current = _from_database_event(event)
    validated = _validated_details(event, changes)
    requested = {
        field: validated.get(field)
        for field in sorted(EVENT_FIELDS)
        if comparable(field, validated.get(field)) != comparable(field, current.get(field))
    }
    if not requested:
        raise ValidationError("The requested changes are the same as the current event details.")

    # Checked here so the organiser gets a clear message; the partial unique
    # index uq_event_change_requests_one_pending_per_event is what holds under
    # a race.
    if _pending_for(event.id):
        raise ChangeRequestConflictError(
            "This session already has a change request waiting for review. "
            "Wait for the coordinator to review it before requesting another change."
        )

    row = {
        "shared_event_id": group_id(event),
        "event_id": event.id,
        "requested_by": requested_by,
        "requested_changes": requested,
        "previous_values": {field: current.get(field) for field in requested},
        "reason": reason,
        "status": "pending",
    }
    change = _first_row(supabase.table(TABLE).insert(row).select("*").execute())
    # The request's timeline: "Change requested by <organiser>".
    record_requested_change(event, requested, row["previous_values"], requested_by)
    return change


def list_change_requests(event: SimpleNamespace, user) -> list[dict]:
    """Every change request recorded for this event request, newest first,
    limited to sessions `user` may view -- the same per-sibling filter
    event_service.list_event_sessions applies.

    Each PENDING change also carries `impact`: what approving it would
    disturb, assessed against the session as it is now (see
    app.events.change_impact), so the coordinator sees it before deciding."""
    shared = group_id(event)
    if getattr(event, "shared_event_id", None):
        rows = supabase.table("events").select("*").eq("shared_event_id", shared).execute().data or []
        sessions = {row["id"]: SimpleNamespace(**row) for row in rows if can(user, EVENT_VIEW, SimpleNamespace(**row))}
    else:
        sessions = {event.id: event}
    result = supabase.table(TABLE).select("*").eq("shared_event_id", shared).order("created_at", desc=True).execute()
    changes = [row for row in result.data or [] if row["event_id"] in sessions]
    for change in changes:
        if change["status"] == "pending":
            change["impact"] = assess_change_impact(sessions[change["event_id"]], change["requested_changes"])
    return changes


def _load_change(event: SimpleNamespace, change_id: str) -> dict:
    """The change request, which must belong to this session -- a change
    filed against another session is a 404 here, not a way to act on an
    event the caller wasn't authorised against."""
    result = supabase.table(TABLE).select("*").eq(KEY, change_id).eq("event_id", event.id).execute()
    if not result.data:
        raise NotFoundError("Change request not found.")
    change = result.data[0]
    if change["status"] != "pending":
        raise ChangeRequestConflictError(f"This change request has already been {change['status']}.")
    return change


def _claim(change_id: str, status: str, reviewed_by: str, comment: str | None, **extra) -> dict:
    """UPDATE event_change_requests SET status = :status ...
    WHERE event_change_req_id = :id AND status = 'pending' -- the same
    conditional-write idea as transitions.transition, so two decisions
    racing each other can't both land."""
    result = (
        supabase.table(TABLE)
        .update(
            {
                "status": status,
                "reviewed_by": reviewed_by,
                "review_comment": comment,
                "reviewed_at": datetime.now(UTC).isoformat(),
                **extra,
            }
        )
        .eq(KEY, change_id)
        .eq("status", "pending")
        .execute()
    )
    if not result.data:
        raise ChangeRequestConflictError("This change request was already reviewed -- refresh to see the outcome.")
    return result.data[0]


def _check_acknowledged(impacts: list[dict], acknowledged) -> None:
    """Every impacted area must be acknowledged by name -- a plain "yes"
    would also wave through an impact that appeared after the coordinator
    loaded the page (a new registration, a booking just confirmed)."""
    if acknowledged is not None and (
        not isinstance(acknowledged, list) or not all(isinstance(area, str) for area in acknowledged)
    ):
        raise ValidationError("acknowledge_impacts must be a list of impact areas.")
    unacknowledged = sorted({impact["area"] for impact in impacts} - set(acknowledged or []))
    if unacknowledged:
        raise ChangeImpactNotAcknowledgedError(
            "This change affects arrangements already made for the event ("
            + ", ".join(area.replace("_", " ") for area in unacknowledged)
            + "). Review them and acknowledge before approving."
        )


def approve_change_request(
    event: SimpleNamespace, change_id: str, reviewed_by: str, comment=None, acknowledge_impacts=None
) -> dict:
    """Approves a pending change and writes it to the event.

    If the change would disturb arrangements already made for the session
    (venue booking, registrations, equipment, technical support -- see
    app.events.change_impact), every affected area must be named in
    `acknowledge_impacts`, or nothing is written (409). The impacts the
    coordinator accepted are recorded on the change request.

    What changed is logged once in event_logs (what, who, when) -- even
    when a shared detail is written to every session of the request.

    Re-validated against the session's details as they are NOW, not as they
    were when the change was requested: the coordinator may have edited the
    event since, or a requested date may have passed. If it no longer
    validates, nothing is written and the coordinator should reject it.

    Not one transaction (supabase-py has none to offer): the change request
    is claimed first, then the event is written, so a lost race never
    writes the event at all. If the event write itself fails after the
    claim, the change request reads approved without having been applied --
    the same trade-off transitions.transition documents for its history row.

    Returns {"change_request": ..., "event": <the updated session row>}."""
    comment = _clean_text(comment, "comment")
    change = _load_change(event, change_id)
    validated = _validated_details(event, change["requested_changes"])
    impacts = assess_change_impact(event, change["requested_changes"])
    _check_acknowledged(impacts, acknowledge_impacts)
    claimed = _claim(change[KEY], "approved", reviewed_by, comment, acknowledged_impacts=impacts or None)

    database_payload = _to_database_payload(validated)
    updated = _first_row(supabase.table("events").update(database_payload).eq("id", event.id).select("*").execute())
    record_event_change(event, updated, reviewed_by)

    shared_changes = {field: validated[field] for field in SHARED_FIELDS if field in change["requested_changes"]}
    if shared_changes and getattr(event, "shared_event_id", None):
        (
            supabase.table("events")
            .update(shared_changes)
            .eq("shared_event_id", event.shared_event_id)
            .eq("organizer_id", event.organizer_id)
            .neq("id", event.id)
            .execute()
        )
    return {"change_request": claimed, "event": updated}


def reject_change_request(event: SimpleNamespace, change_id: str, reviewed_by: str, reason) -> dict:
    """Rejects a pending change; the event is not touched. A reason is
    required so the organiser knows why (the same rule as rejecting an
    event request)."""
    reason = _clean_text(reason, "reason")
    if not reason:
        raise ValidationError("A reason is required to reject a change request.")
    change = _load_change(event, change_id)
    return _claim(change[KEY], "rejected", reviewed_by, reason)
