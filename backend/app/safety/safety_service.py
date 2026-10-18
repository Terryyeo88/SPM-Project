"""Business logic for the Operational Feasibility Check (Week 7 change #6).

"After the venue and technical arrangements have been confirmed, the
Safety Officer must conduct an Operational Safety Check before the event
can proceed to preparation. ... The Safety Officer may approve the event,
reject the safety arrangement, or request changes. If changes are
required, the event returns to the relevant earlier planning stage."
Week 9: "It is similar to Venue and technical approval. The safety officer
role will pick up the event request and perform the necessary checks and
update the status of approval with a comment. The co-ordinator will
decide on the subsequent action."

The flow, per event SESSION (each session has its own venue, capacity,
layout and status -- see the migration's comment):

  1. The assigned coordinator submits the session (submit_for_safety_check)
     once its arrangements are ready: at least one confirmed venue booking,
     and no venue booking or equipment request still pending. That writes a
     pending safety_reviews row and moves the session planning ->
     safety_review.
  2. Any Safety Officer decides (decide_review): approved, rejected or
     changes_requested, with a comment (required unless approving).
     Rejected / changes requested send the session back to planning; the
     coordinator fixes things and submits again (a new row).
  3. Approved leaves the session in safety_review. The coordinator then
     confirms it (POST /events/<id>/confirm), which is only allowed once
     the latest review is approved (is_approved).

Event status is only ever written through app.events.transitions. Like
transitions' own history insert, the review write and the status change
are separate requests, not one database transaction -- see each
function's docstring for how a failure between the two is handled.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from postgrest.exceptions import APIError

from app.equipment.equipment_service import list_requests_for_event
from app.events.transitions import TransitionConflictError, label, transition
from app.extensions import supabase
from app.shared.errors import NotFoundError, ValidationError

TABLE = "safety_reviews"

REVIEW_STATUSES = frozenset({"pending", "approved", "rejected", "changes_requested"})
DECIDED_STATUSES = REVIEW_STATUSES - {"pending"}
# The comment tells the coordinator what to fix, so it is required for
# these two and optional when approving.
COMMENT_REQUIRED = frozenset({"rejected", "changes_requested"})

_COMMENT_MESSAGES = {
    "rejected": "A comment is required to reject a safety arrangement -- tell the coordinator why.",
    "changes_requested": "A comment is required to request changes -- tell the coordinator what to change.",
}

# PostgREST needs the foreign key named when a table has two FKs to the
# same table (submitted_by and reviewed_by both reference profiles).
_REVIEWER = "reviewer:profiles!safety_reviews_reviewed_by_fkey(name)"
_SUBMITTER = "submitter:profiles!safety_reviews_submitted_by_fkey(name)"


def _first(data):
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _flatten_names(row: dict) -> dict:
    """{"reviewer": {"name": ...}} -> "reviewed_by_name": ... (same for the
    submitter), so the frontend reads plain fields."""
    row = dict(row)
    row["reviewed_by_name"] = (row.pop("reviewer", None) or {}).get("name")
    row["submitted_by_name"] = (row.pop("submitter", None) or {}).get("name")
    return row


# -- readiness -----------------------------------------------------------------


def arrangement_problems(event_id: str) -> list[str]:
    """Why this session can't be submitted for a safety check yet, or [] if
    it can. Week 7: the check happens "after the venue and technical
    arrangements have been confirmed":
      - at least one venue booking is confirmed (a session needs a venue);
      - no venue booking is still pending (Venue Staff haven't decided);
      - no equipment request is still pending (Technical Support Staff
        haven't decided). Equipment itself is optional -- a session may
        need none, and requests can't be created in the app yet.
    Rejected bookings and requests don't block: they're history, replaced
    by a newer request if the coordinator still needs one."""
    bookings = supabase.table("venue_bookings").select("id, status").eq("event_id", event_id).execute().data or []
    requests = supabase.table("equipment_requests").select("id, status").eq("event_id", event_id).execute().data or []

    problems = []
    if not any(booking["status"] == "confirmed" for booking in bookings):
        problems.append("No venue booking has been confirmed for this session yet.")
    if any(booking["status"] == "pending" for booking in bookings):
        problems.append("A venue booking is still waiting on Venue Staff.")
    if any(request["status"] == "pending" for request in requests):
        problems.append("An equipment request is still waiting on Technical Support Staff.")
    return problems


# -- reading -------------------------------------------------------------------


def latest_review(event_id: str) -> dict | None:
    result = supabase.table(TABLE).select("*").eq("event_id", event_id).order("submitted_at", desc=True).execute()
    return _first(result.data or [])


def is_approved(event_id: str) -> bool:
    """True if the session's most recent safety review is approved -- the
    gate on confirming it (Week 7: "The event cannot proceed to preparation
    until the Safety Officer has approved it")."""
    latest = latest_review(event_id)
    return bool(latest) and latest["status"] == "approved"


def list_reviews_for_event(event_id: str) -> list[dict]:
    """One session's safety-check history, newest first, for the
    coordinator's Safety Check section on the event page. The route gates
    on EVENT_VIEW for this one event, same split as
    booking_service.list_bookings_for_event."""
    result = (
        supabase.table(TABLE)
        .select(f"*, {_REVIEWER}, {_SUBMITTER}")
        .eq("event_id", event_id)
        .order("submitted_at", desc=True)
        .execute()
    )
    return [_flatten_names(row) for row in result.data or []]


def list_reviews(user, status: str | None = None) -> list[dict]:
    """The Safety Officer's dashboard: every review, newest first, each with
    its session embedded as `event` (the dashboard groups sessions into one
    card per request, like the coordinator's).

    Every Safety Officer sees every review -- there is no assignment step
    (team decision: Week 9's "pick up" is opening it from the shared
    queue, the same way every Venue Staff member sees every booking).
    rule_safety_review_list is role-only, so the role check is repeated
    here as defence in depth, same as booking_service.list_bookings.

    A pending review whose session has left safety_review (it was
    cancelled while waiting) is left out: there is nothing to decide."""
    if status is not None and status not in REVIEW_STATUSES:
        raise ValidationError(f"status must be one of: {', '.join(sorted(REVIEW_STATUSES))}.")
    if "safety_officer" not in set(user.roles):
        return []

    query = supabase.table(TABLE).select(f"*, events(*), {_REVIEWER}, {_SUBMITTER}")
    if status is not None:
        query = query.eq("status", status)
    rows = query.order("submitted_at", desc=True).execute().data or []

    reviews = []
    for row in rows:
        event = row.pop("events", None) or {}
        if row["status"] == "pending" and event.get("status") != "safety_review":
            continue
        reviews.append({**_flatten_names(row), "event": event})
    return reviews


def get_review(review_id: str) -> dict:
    result = supabase.table(TABLE).select("*").eq("id", review_id).maybe_single().execute()
    if result is None or not result.data:
        raise NotFoundError("Safety review not found.")
    return result.data


def review_detail(review: SimpleNamespace) -> dict:
    """Everything the Safety Officer checks for one review (Week 7: "expected
    attendance, venue capacity and layout, emergency access, accessibility
    requirements, equipment placement, crowd movement, and any known venue
    restrictions"): the session itself, its confirmed venue booking(s) with
    the venue record, its equipment requests, and the session's earlier
    safety reviews. The Safety Officer reviews this; they don't enter it
    (Week 9: "The safety officer do not need to input but to approve")."""
    event = _first(supabase.table("events").select("*").eq("id", review.event_id).execute().data or [])
    bookings = (
        supabase.table("venue_bookings")
        .select("*, venues(*)")
        .eq("event_id", review.event_id)
        .eq("status", "confirmed")
        .execute()
        .data
        or []
    )
    history = [row for row in list_reviews_for_event(review.event_id) if row["id"] != review.id]
    names = _first(
        supabase.table(TABLE).select(f"id, {_REVIEWER}, {_SUBMITTER}").eq("id", review.id).execute().data or []
    )
    return {
        **vars(review),
        **_flatten_names(names or {}),
        "event": event,
        "venue_bookings": bookings,
        "equipment_requests": list_requests_for_event(review.event_id),
        "history": history,
    }


# -- writing -------------------------------------------------------------------


def submit_for_safety_check(event: SimpleNamespace, submitted_by: str) -> dict:
    """The coordinator sends one planning session for its safety check.

    authz (rule_safety_review_submit) has already checked the caller is the
    session's assigned coordinator and it is in planning. This checks the
    arrangements are ready, writes the pending review, then moves the
    session planning -> safety_review.

    The pending review is written FIRST: the one-pending-per-session unique
    index is what stops a double submit (two clicks, two tabs) from making
    two. If the status change then fails (the session moved on meanwhile,
    a 409), the review just written is deleted again, so a refused submit
    leaves nothing behind."""
    problems = arrangement_problems(event.id)
    if problems:
        raise ValidationError("This session isn't ready for a safety check. " + " ".join(problems))

    try:
        result = (
            supabase.table(TABLE)
            .insert({"event_id": event.id, "status": "pending", "submitted_by": submitted_by})
            .select("*")
            .execute()
        )
    except APIError as exc:
        if exc.code == "23505":  # safety_reviews_one_pending_per_event
            raise ValidationError("This session is already waiting for a safety check.") from exc
        raise
    review = _first(result.data)
    if not review:
        raise ValidationError("The safety review database operation did not return a review.")

    try:
        updated_event = transition(event.id, "safety_review", submitted_by, expected_from=event.status)
    except Exception:
        supabase.table(TABLE).delete().eq("id", review["id"]).execute()
        raise
    _notify_safety_review(review, "submitted")
    return {"event": updated_event, "review": review}


def _notify_safety_review(review: dict, what: str) -> None:
    """Hook for the Notification System story (later sprint). No-op
    placeholder, same shape as booking_service._notify_booking_decision."""
    print(f"[notify] safety review {review.get('id')} {what}")


def _clean_comment(comment) -> str | None:
    if comment is None:
        return None
    if not isinstance(comment, str):
        raise ValidationError("comment must be text.")
    return comment.strip() or None


def decide_review(review_id: str, review: SimpleNamespace, to_status: str, decided_by: str, comment) -> dict:
    """A Safety Officer approves, rejects or requests changes.

    authz (rule_safety_review_approve / _reject / _request_changes) has
    already checked the caller is a Safety Officer and the review is
    pending. This also checks the session is still in safety_review (it
    could have been cancelled while waiting).

    The review update is conditioned on status still being "pending", so
    two decisions racing each other can't both land -- the second matches
    no row and gets a clear error (same race-proofing as
    booking_service._decide_booking).

    Rejected / changes requested then move the session safety_review ->
    planning (Week 9: "if the safety approval failed, then it will send the
    event back to planning phase"), with the comment as the status-history
    reason. If the session already moved on between the two writes (the
    coordinator cancelled it), the decision still stands and the status is
    left alone. Approved changes no status: the coordinator confirms."""
    if to_status not in DECIDED_STATUSES:
        raise ValidationError(f"decision must be one of: {', '.join(sorted(DECIDED_STATUSES))}.")
    cleaned = _clean_comment(comment)
    if to_status in COMMENT_REQUIRED and not cleaned:
        raise ValidationError(_COMMENT_MESSAGES[to_status])

    event = _first(supabase.table("events").select("id, status").eq("id", review.event_id).execute().data or [])
    if not event:
        raise NotFoundError("Event not found.")
    if event["status"] != "safety_review":
        raise ValidationError(
            f"This session is no longer waiting for a safety check -- it is {label(event['status'])}."
        )

    result = (
        supabase.table(TABLE)
        .update(
            {
                "status": to_status,
                "comment": cleaned,
                "reviewed_by": decided_by,
                "reviewed_at": datetime.now(UTC).isoformat(),
            }
        )
        .eq("id", review_id)
        .eq("status", "pending")
        .select("*")
        .execute()
    )
    decided = _first(result.data)
    if not decided:
        raise ValidationError("This safety review is no longer pending -- refresh to see its current status.")

    if to_status in COMMENT_REQUIRED:
        try:
            transition(review.event_id, "planning", decided_by, reason=cleaned, expected_from="safety_review")
        except TransitionConflictError:
            pass  # the session moved on meanwhile (e.g. cancelled); the decision is recorded either way
    _notify_safety_review(decided, to_status)
    return decided
