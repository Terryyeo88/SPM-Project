"""
The single guarded path for changing an event's status.

Every status change goes through transition(). Nothing else in the app
should write events.status except the initial insert (see
record_creation below -- a create has no previous status, so it isn't an
edge).

THE EDGE SET IS DATA, NOT BRANCHING. ALLOWED below is the complete list
of legal (from, to) pairs, each sourced from a quoted story. An illegal
transition is a missing entry, not a missing `if` -- so "what can this
event move to next?" is answered by reading one table, and adding an
edge is a one-line, reviewable diff.

ATOMICITY: THE EXPECTED STATUS IS IN THE WHERE CLAUSE. The update is
`UPDATE events SET status = :to WHERE id = :id AND status = :from`, and
we check how many rows it touched. Postgres evaluates that WHERE against
the row's current committed value under a row lock, so if two requests
race from the same starting status, exactly one matches and the other
touches zero rows. Zero rows raises TransitionConflictError (409). We
never retry and never fall back to an unconditional write -- a silent
retry would just re-run the same decision against a state the caller
never saw. Compare the read-then-write the old code did: read status,
decide in Python, then `UPDATE ... WHERE id = :id`. Anything that
changed between the read and the write is overwritten with no error.

NO AUTHORISATION HERE. Callers authorise with @require before calling
this. Authz answers "may this user do this to this event"; the state
machine answers "is this edge legal at all". They fail differently (403
or 404 versus 409 or 400) and are tested differently: authz rules are
pure functions of (user, event), while transition rules are pure
functions of (from, to, reason). Folding one into the other would force
every state-machine test to build users and every authz test to build
edges.

THE HISTORY WRITE IS NOT ATOMIC WITH THE STATUS WRITE -- say it plainly.
They are two separate PostgREST requests, so there is no shared database
transaction. Failure mode: the status update succeeds and then the
event_status_log insert fails (network drop, database error). The event
has moved, but there is no audit row for that move. The caller gets a
500, and retrying gets a 409, because the event is no longer in
from_status. Nothing heals this automatically. The fix, if we ever need
one, is a single Postgres function (RPC) that does both statements in
one transaction. That is deliberately not built here.

DATABASE ACCESS is isolated in the small _db_* functions at the bottom,
the same way app.auth.context isolates its reads, so unit tests
monkeypatch those instead of faking postgrest's fluent builder.
"""

from __future__ import annotations

from typing import Any

from app.extensions import supabase
from app.shared.errors import AppError, NotFoundError, ValidationError

# -- the edge set ----------------------------------------------------------
# (from_status, to_status) -> story text it comes from. Kept as a dict so
# the source travels with the edge; ALLOWED is just its keys.

_EDGE_SOURCES: dict[tuple[str, str], str] = {
    ("draft", "submitted"): "Submitting a completed request changes status to Submitted (organiser, from draft).",
    ("rejected", "submitted"): "A rejected request can be re-submitted for review after the Organizer makes changes.",
    ("submitted", "under_review"): (
        "When a Coordinator is assigned to a submitted request, status auto-changes to under_review; "
        "no manual action."
    ),
    ("under_review", "approved"): "Coordinator can set approved or rejected only if current status is under_review.",
    ("under_review", "rejected"): (
        "Coordinator can set approved or rejected only if current status is under_review; "
        "rejection requires a reason."
    ),
    ("approved", "planning"): "Coordinator can set planning only if current status is approved.",
    ("planning", "confirmed"): "Coordinator can set confirmed only from planning.",
    ("confirmed", "completed"): (
        "Coordinator can set completed only from confirmed; completed events are read-only going forward."
    ),
    # "after approval" read as approved/planning/confirmed, not completed --
    # the same range rule_event_cancel already uses (docs/design-decisions.md
    # §event.cancel, confirmation pending in docs/open-questions.md).
    ("approved", "cancelled"): "Coordinator can cancel after approval; cancellation requires a reason.",
    ("planning", "cancelled"): "Coordinator can cancel after approval; cancellation requires a reason.",
    ("confirmed", "cancelled"): "Coordinator can cancel after approval; cancellation requires a reason.",
}

ALLOWED: frozenset[tuple[str, str]] = frozenset(_EDGE_SOURCES)

# Reason requirements are data too, keyed on the TARGET status, and
# enforced once here rather than at each call site.
REASON_REQUIRED: frozenset[str] = frozenset({"rejected", "cancelled"})


class TransitionConflictError(AppError):
    """The event was not in the status this transition expected when the
    write ran, because someone else moved it first. Refresh and retry
    deliberately; this is never retried automatically."""

    status_code = 409
    code = "status_conflict"


class IllegalTransitionError(AppError):
    """The (from, to) pair is not in ALLOWED. With @require checking
    status preconditions first this is normally unreachable from a route.
    Seeing it means a caller asked for an edge no story permits."""

    status_code = 409
    code = "illegal_transition"


def is_allowed(from_status: str, to_status: str) -> bool:
    return (from_status, to_status) in ALLOWED


def _clean_reason(to_status: str, reason: Any) -> str | None:
    if reason is not None and not isinstance(reason, str):
        raise ValidationError("reason must be a string.")
    cleaned = reason.strip() if isinstance(reason, str) else None
    if to_status in REASON_REQUIRED and not cleaned:
        raise ValidationError(f"A reason is required to move an event to {to_status}.")
    return cleaned or None


def transition(
    event_id: str,
    to_status: str,
    actor: str,
    reason: str | None = None,
    expected_from: str | None = None,
) -> dict:
    """Move one event from its current status to `to_status`, atomically.

    `actor` is the profile id of the person the change is attributed to,
    and is recorded as event_status_log.changed_by. Every transition we
    build passes a real person, so NULL there means "no human actor"
    (see docs/design-decisions.md).

    `expected_from` is the status the caller believes the event is in,
    typically the status @require's loader just authorised against.
    Pass it whenever you have it. The write is then conditional on
    exactly the state that was authorised. If it's omitted, the current
    status is read first and the write is conditional on THAT value.
    Either way the write is never unconditional.

    Returns the updated event row. Raises:
      ValidationError          missing/invalid reason where one is required
      IllegalTransitionError   (from, to) not in ALLOWED
      NotFoundError            no such event (only when expected_from is omitted)
      TransitionConflictError  the event wasn't in from_status when the write ran
    """
    cleaned_reason = _clean_reason(to_status, reason)

    from_status = expected_from if expected_from is not None else _db_current_status(event_id)
    if not is_allowed(from_status, to_status):
        raise IllegalTransitionError(f"An event cannot move from {from_status} to {to_status}.")

    updated = _db_conditional_update(event_id, from_status, to_status)
    if updated is None:
        raise TransitionConflictError(
            f"This event is no longer {from_status} -- someone else changed it. Refresh to see its current status."
        )

    # Not atomic with the update above -- see the module docstring.
    _db_insert_history(event_id, from_status, to_status, actor, cleaned_reason)
    return updated


def record_creation(event_id: str, actor: str) -> None:
    """History row for an event's initial insert (from_status NULL -> draft).
    Not a transition: there is no previous status to condition on, so it
    does not go through ALLOWED or transition()."""
    _db_insert_history(event_id, None, "draft", actor, None)


def status_history(event_id: str) -> list[dict]:
    """Every recorded status change for one event, oldest first."""
    return _db_list_history(event_id)


# -- database access (isolated so unit tests don't fake the query builder) --


def _db_current_status(event_id: str) -> str:
    # maybe_single().execute() returns None itself (not a result with
    # data=None) when zero rows match -- guard both.
    result = supabase.table("events").select("status").eq("id", event_id).maybe_single().execute()
    if result is None or not result.data:
        raise NotFoundError("Event not found.")
    return result.data["status"]


def _db_conditional_update(event_id: str, from_status: str, to_status: str) -> dict | None:
    """UPDATE events SET status = to WHERE id = :id AND status = :from.
    Returns the updated row, or None if zero rows matched."""
    result = (
        supabase.table("events")
        .update({"status": to_status})
        .eq("id", event_id)
        .eq("status", from_status)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def _db_insert_history(
    event_id: str, from_status: str | None, to_status: str, actor: str, reason: str | None
) -> None:
    supabase.table("event_status_log").insert(
        {
            "event_id": event_id,
            "from_status": from_status,
            "to_status": to_status,
            "changed_by": actor,
            "reason": reason,
        }
    ).execute()


def _db_list_history(event_id: str) -> list[dict]:
    result = (
        supabase.table("event_status_log")
        .select("from_status, to_status, changed_by, reason, changed_at")
        .eq("event_id", event_id)
        .order("changed_at")
        .execute()
    )
    return result.data or []
