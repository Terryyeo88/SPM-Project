"""Business logic for the clarification thread on an event request.

Event Review and Approval: "Upon choosing to request for clarification or
amendments, the Event Coordinator can enter comments and submit it for the
Event Organizer to view." and "Given that an event request is under review,
when the Event Coordinator sends feedback for amendments or clarification,
then the Event Organizer is able to answer to the Event Coordinator."

Week 9: the conversation "is happening offline but the system should have a
means for recording the comments for tracking" -- so this is an append-only
log in public.event_clarifications, not a live chat. Nothing here changes
the event's status (Week 4: clarification is part of "under review"), and
nothing here lets the organizer edit the request (rule_event_edit is
untouched): replying only adds a message.

One thread per event REQUEST (shared_event_id), shared by every session,
the same grouping approve/reject already use. Messages are never edited or
deleted.

Callers authorise first via @require:
  - EVENT_REQUEST_CLARIFICATION  the assigned coordinator posts (under_review)
  - EVENT_CLARIFICATION_REPLY    the owning organizer replies (under_review)
  - EVENT_CLARIFICATION_VIEW     either of them reads the thread (any status)
The one check those pure rules can't make -- "the coordinator has asked
something" before the organizer may reply -- needs a database read, so it
is made here, as a ValidationError (400).
"""

from __future__ import annotations

from types import SimpleNamespace

from app.events.event_log import group_id
from app.extensions import supabase
from app.notifications import notification_service
from app.shared.errors import ValidationError

TABLE = "event_clarifications"
MAX_MESSAGE_LENGTH = 1000

COORDINATOR = "coordinator"
ORGANIZER = "organizer"
AUTHOR_ROLES = (COORDINATOR, ORGANIZER)


def _clean_message(value) -> str:
    """AC: a message can't be blank and can't exceed 1000 characters.
    Leading/trailing whitespace is trimmed before both checks, so the limit
    is on what is actually stored (the database check mirrors it)."""
    if value is not None and not isinstance(value, str):
        raise ValidationError("message must be text.")
    cleaned = (value or "").strip()
    if not cleaned:
        raise ValidationError("Enter a message before sending.")
    if len(cleaned) > MAX_MESSAGE_LENGTH:
        raise ValidationError(f"A message can't be longer than {MAX_MESSAGE_LENGTH} characters.")
    return cleaned


def _author_names(author_ids) -> dict[str, str]:
    ids = sorted({author_id for author_id in author_ids if author_id})
    if not ids:
        return {}
    rows = supabase.table("profiles").select("id, name").in_("id", ids).execute().data or []
    return {row["id"]: row.get("name") for row in rows}


def _with_author_names(rows: list[dict]) -> list[dict]:
    names = _author_names(row.get("author_id") for row in rows)
    return [{**row, "author_name": names.get(row.get("author_id"))} for row in rows]


def list_clarifications(event: SimpleNamespace) -> list[dict]:
    """Every message in this request's thread, oldest first, each with its
    author's name (AC: who sent it and when, in the order sent)."""
    result = (
        supabase.table(TABLE)
        .select("*")
        .eq("shared_event_id", group_id(event))
        .order("created_at")
        .execute()
    )
    return _with_author_names(result.data or [])


def _coordinator_has_asked(shared_event_id: str) -> bool:
    result = (
        supabase.table(TABLE)
        .select("clarification_id")
        .eq("shared_event_id", shared_event_id)
        .eq("author_role", COORDINATOR)
        .execute()
    )
    return bool(result.data)


def post_clarification(event: SimpleNamespace, author_id: str, author_role: str, message) -> dict:
    """Adds one message to the request's thread and tells the other side.

    `author_role` is which side the caller is posting as -- the route
    decides it from the action it authorised, never from the request body.
    The organizer can only answer: they can't open a thread (to change
    details themselves they use Request Change)."""
    if author_role not in AUTHOR_ROLES:
        raise ValueError(f"author_role must be one of {AUTHOR_ROLES}, got {author_role!r}")
    cleaned = _clean_message(message)
    shared = group_id(event)
    if author_role == ORGANIZER and not _coordinator_has_asked(shared):
        raise ValidationError(
            "The Event Coordinator hasn't sent a clarification request yet, so there is nothing to reply to. "
            "To change your event details, use Request Change instead."
        )

    row = {
        "shared_event_id": shared,
        "event_id": event.id,
        "author_id": author_id,
        "author_role": author_role,
        "message": cleaned,
    }
    result = supabase.table(TABLE).insert(row).select("*").execute()
    if not result.data:
        raise ValidationError("The clarification could not be saved. Please try again.")
    created = result.data[0] if isinstance(result.data, list) else result.data

    notification_service.clarification_posted(event.id, author_role)
    return _with_author_names([created])[0]
