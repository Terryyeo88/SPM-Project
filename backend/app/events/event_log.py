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

IS-9: each entry is also classified "significant" (it touches the date,
time, expected attendance, venue requirements or equipment requirements --
SIGNIFICANT_FIELDS) or "ordinary" (anything else), stored in
`significance`. A coordinator's update also keeps the impacts they
acknowledged before saving, in `acknowledged_impacts`.

Each entry also records WHICH session it was made on (`event_id`), so a
multi-session request's history can say "Session 2"; list_event_logs
labels it (see _session_label).

public.event_change_requests holds the change requests themselves (and
their review); event_logs is the request's timeline of what was asked for
and what was changed.

Like transitions.transition's history row, the log insert is a separate
PostgREST call from the event write it describes, not one transaction.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.events.event_service import (
    REGISTRATION_WINDOW_FIELDS,
    SHARED_FIELDS,
    _from_database_event,
    _parse_registration_datetime,
    _session_sort_key,
)
from app.extensions import supabase

# IS-9: "Changes to date, time, expected attendance, venue requirements, or
# equipment requirements are recorded as significant; changes to other
# fields are recorded as ordinary." Venue requirements = the room layout
# (accessibility needs are listed as their own field in the story).
SIGNIFICANT_FIELDS = frozenset(
    {
        "preferred_start_date",
        "preferred_end_date",
        "preferred_start_time",
        "preferred_end_time",
        "expected_attendance",
        "room_layout",
        "equipment",
    }
)


def significance(fields) -> str | None:
    """"significant" if any of `fields` is in SIGNIFICANT_FIELDS, else
    "ordinary"; None when nothing changed."""
    fields = set(fields)
    if not fields:
        return None
    return "significant" if fields & SIGNIFICANT_FIELDS else "ordinary"


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


def record_event_change(
    before_row, after_row, changed_by: str | None, acknowledged_impacts: list[dict] | None = None
) -> dict | None:
    """Logs what changed between two versions of a session row, and
    whether that was significant. Writes nothing (and returns None) when no
    detail actually changed. `acknowledged_impacts` are the arrangements
    the coordinator was shown, and accepted, before saving."""
    changes = diff(_details(before_row), _details(after_row))
    if not changes:
        return None
    after = after_row if isinstance(after_row, dict) else vars(after_row)
    entry = {
        "shared_event_id": group_id(after),
        "event_id": after["id"],
        "changes": changes,
        "significance": significance(changes),
        "changed_by": changed_by,
    }
    if acknowledged_impacts:
        entry["acknowledged_impacts"] = acknowledged_impacts
    result = supabase.table("event_logs").insert(entry).execute()
    return (result.data or [entry])[0]


def record_requested_change(event, requested_changes: dict, previous_values: dict, requested_by: str) -> dict:
    """Logs that the organiser ASKED for a change (a change request was
    submitted): the same {field: {from, to}} shape as an applied change, so
    the timeline reads "requested X -> Y", then (if approved) "changed"."""
    entry = {
        "shared_event_id": group_id(event),
        "event_id": event.id,
        "changes": {
            field: {"from": previous_values.get(field), "to": value} for field, value in requested_changes.items()
        },
        "significance": significance(requested_changes),
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


def _session_numbers(event: SimpleNamespace) -> dict[str, int]:
    """session id -> its number in the request (1, 2, ...), in the same
    order the request's sessions are listed (event_service._session_sort_key).
    A request's sessions share shared_event_id AND organiser, the same scope
    event_update.apply_shared_details uses."""
    shared_event_id = getattr(event, "shared_event_id", None)
    if not shared_event_id:
        return {event.id: 1}
    rows = (
        supabase.table("events")
        .select("id, preferred_start_date, preferred_start_time, created_at")
        .eq("shared_event_id", shared_event_id)
        .eq("organizer_id", event.organizer_id)
        .execute()
        .data
        or []
    )
    return {row["id"]: number for number, row in enumerate(sorted(rows, key=_session_sort_key), start=1)}


def _session_label(entry: dict, kind: str, numbers: dict[str, int]) -> dict | None:
    """Which session an entry is about, as {"id", "number", "label"}:

      "All sessions"  a change that took effect on the shared details only
                      (name, description, purpose), which the coordinator's
                      edit or approval writes to every session;
      "Session N"     otherwise, the session it was made on;
      "Session not recorded"
                      an entry with no (or no longer a) session on a
                      multi-session request: written before sessions were
                      recorded (20261019400000_event_logs_session.sql), or
                      its session was since removed. Said outright rather
                      than left blank, so it doesn't read as a missing label;
      None            a single-session request (nothing to tell apart).
    """
    if len(numbers) < 2:
        return None
    fields = set(entry.get("changes") or {})
    if kind == "changed" and fields and fields <= set(SHARED_FIELDS):
        return {"id": None, "number": None, "label": "All sessions"}
    number = numbers.get(entry.get("event_id"))
    if number is None:
        return {"id": None, "number": None, "label": "Session not recorded"}
    return {"id": entry["event_id"], "number": number, "label": f"Session {number}"}


def list_event_logs(event: SimpleNamespace) -> list[dict]:
    """Every log entry for this event request, newest first, with the name
    of whoever made it (`profiles`, through changed_by), its `kind`
    ("requested" or "changed", see entry_kind), its `significance`
    (worked out from the fields for entries written before it was stored)
    and the `session` it was about (see _session_label).

    The caller has already been authorised to view `event` (EVENT_VIEW).
    Entries are read for the whole request, which has one organiser and one
    coordinator, so that covers every session's entries."""
    result = (
        supabase.table("event_logs")
        .select("*, profiles(name)")
        .eq("shared_event_id", group_id(event))
        .order("changed_at", desc=True)
        .execute()
    )
    entries = result.data or []
    numbers = _session_numbers(event) if entries else {}
    listed = []
    for entry in entries:
        kind = entry_kind(entry, event)
        listed.append(
            {
                **entry,
                "kind": kind,
                "significance": entry.get("significance") or significance(entry.get("changes") or {}),
                "session": _session_label(entry, kind, numbers),
            }
        )
    return listed
