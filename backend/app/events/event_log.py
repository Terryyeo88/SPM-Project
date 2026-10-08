"""The event audit trail: public.event_logs.

Each entry records WHAT was asked for or changed on an event request
(field: from -> to), WHO did it (changed_by) and WHEN (changed_at), linked
to the whole request by shared_event_id. One entry per change: an approved change to a
shared detail (name, description, purpose) is written to every session,
but logged once.

Each entry is one of two kinds, told apart by WHO made it (the table has
no kind column -- see `kind` in list_event_logs):

  requested  made by the request's organiser, who can't change a submitted
             event directly -- only ask: submitting a change request
             (app.events.change_request_service), or fixing a rejected
             session before resubmitting it for review.
  changed    made by the coordinator, whose edits take effect: a direct
             edit, or approving a change request.

Drafts aren't logged: nothing has been submitted to anyone yet. Status
changes have their own history (event_status_log, app.events.transitions).

public.event_change_requests holds the change requests themselves (and
their review); event_logs is the request's timeline of what was asked for
and what was changed.

Like transitions.transition's history row, the log insert is a separate
PostgREST call from the event write it describes, not one transaction.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.events.event_service import REGISTRATION_WINDOW_FIELDS, _from_database_event, _parse_registration_datetime
from app.extensions import supabase


def group_id(event) -> str:
    """The event request a session belongs to. A legacy event created
    before sessions existed has no shared_event_id: a group of one, keyed by
    its own id (the convention event_service already uses)."""
    if isinstance(event, dict):
        return event.get("shared_event_id") or event["id"]
    return getattr(event, "shared_event_id", None) or event.id


def comparable(field: str, value):
    """Blank and NULL are the same; the same instant is the same whatever
    timezone it's written in ("...Z" from the database, "...+08:00" from
    validation)."""
    if value in (None, ""):
        return None
    if field in REGISTRATION_WINDOW_FIELDS:
        return _parse_registration_datetime(value, field)
    return value


def diff(before: dict, after: dict, fields=None) -> dict:
    """{field: {"from", "to"}} for every field whose value differs."""
    fields = fields if fields is not None else sorted(set(before) | set(after))
    return {
        field: {"from": before.get(field), "to": after.get(field)}
        for field in fields
        if comparable(field, before.get(field)) != comparable(field, after.get(field))
    }


def _details(row) -> dict:
    """A session row (dict or namespace) in the event API's field names."""
    return _from_database_event(row if isinstance(row, SimpleNamespace) else SimpleNamespace(**row))


def record_event_change(before_row, after_row, changed_by: str | None) -> dict | None:
    """Logs what changed between two versions of a session row. Writes
    nothing (and returns None) when no detail actually changed."""
    changes = diff(_details(before_row), _details(after_row))
    if not changes:
        return None
    after = after_row if isinstance(after_row, dict) else vars(after_row)
    entry = {"shared_event_id": group_id(after), "changes": changes, "changed_by": changed_by}
    result = supabase.table("event_logs").insert(entry).execute()
    return (result.data or [entry])[0]


def record_requested_change(event, requested_changes: dict, previous_values: dict, requested_by: str) -> dict:
    """Logs that the organiser ASKED for a change (a change request was
    submitted): the same {field: {from, to}} shape as an applied change, so
    the timeline reads "requested X -> Y", then (if approved) "changed"."""
    entry = {
        "shared_event_id": group_id(event),
        "changes": {
            field: {"from": previous_values.get(field), "to": value} for field, value in requested_changes.items()
        },
        "changed_by": requested_by,
    }
    result = supabase.table("event_logs").insert(entry).execute()
    return (result.data or [entry])[0]


def entry_kind(entry: dict, event) -> str:
    """"requested" for the request's organiser (who can only ask), else
    "changed". A person who is both the organiser and the assigned
    coordinator makes changes that take effect, so they count as changed."""
    by = entry.get("changed_by")
    if by and by == event.organizer_id and by != getattr(event, "coordinator_id", None):
        return "requested"
    return "changed"


def list_event_logs(event: SimpleNamespace) -> list[dict]:
    """Every log entry for this event request, newest first, with the name
    of whoever made it (`profiles`, through changed_by) and its `kind`
    ("requested" or "changed", see entry_kind).

    The caller has already been authorised to view `event` (EVENT_VIEW).
    Entries aren't per session, so that covers the whole request -- which
    has one organiser and one coordinator."""
    result = (
        supabase.table("event_logs")
        .select("*, profiles(name)")
        .eq("shared_event_id", group_id(event))
        .order("changed_at", desc=True)
        .execute()
    )
    return [{**entry, "kind": entry_kind(entry, event)} for entry in result.data or []]
