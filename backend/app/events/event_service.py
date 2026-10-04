"""Business logic for event request creation, editing, and submission.

An event request is made of one or more SESSIONS. Each session is its own
row in the events table (so each one is reviewed, assigned a coordinator
and moves through the status lifecycle independently), and every session
of the same request carries the same `shared_event_id`, generated here on
the server when the request is first created. The name, description and
purpose are shared by every session; everything else (dates/times,
attendance, layout, accessibility, equipment, registration and its
window, special requests) is per session.

Request bodies for the create/draft endpoints are group-shaped:
    {"name", "description", "purpose", "sessions": [{...session fields}]}
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from types import SimpleNamespace

from app.authz.actions import EVENT_VIEW
from app.authz.policy import can
from app.events.coordinator_service import NoCoordinatorAvailableError, assign_initial_coordinator
from app.events.transitions import TransitionConflictError, record_creation, transition
from app.extensions import supabase
from app.shared.errors import ValidationError

EVENT_STATUSES = {
    "draft",
    "submitted",
    "under_review",
    "approved",
    "planning",
    "confirmed",
    "completed",
    "cancelled",
    "rejected",
}
ROOM_LAYOUTS = {"theatre", "classroom", "boardroom", "seminar", "banquet", "networking"}
EQUIPMENT = {"microphone", "projector", "screen", "wifi"}
ACCESSIBILITY_NEEDS = {
    "wheelchair_access",
    "lift_access",
    "removable_seats",
    "extra_legroom_seats",
}
SHARED_FIELDS = ("name", "description", "purpose")
SESSION_FIELDS = {
    "preferred_start_date",
    "preferred_end_date",
    "preferred_start_time",
    "preferred_end_time",
    "expected_attendance",
    "accessibility_needs",
    "room_layout",
    "equipment",
    "registration_needs",
    "registration_start_datetime",
    "registration_end_datetime",
    "special_requests",
}
EVENT_FIELDS = set(SHARED_FIELDS) | SESSION_FIELDS
GROUP_FIELDS = {*SHARED_FIELDS, "sessions"}
REGISTRATION_WINDOW_FIELDS = ("registration_start_datetime", "registration_end_datetime")
# Venues are in Singapore, so session dates/times (date + time columns with
# no timezone) are Singapore wall-clock time. Singapore has been a fixed
# UTC+8 with no daylight saving since 1982, so a fixed offset is exact --
# and unlike zoneinfo it needs no tzdata package on Windows.
SINGAPORE_TZ = timezone(timedelta(hours=8), "SGT")
REQUIRED_FIELDS = {
    "name",
    "description",
    "purpose",
    "preferred_start_date",
    "preferred_end_date",
    "expected_attendance",
    "room_layout",
    "registration_needs",
}
DRAFT_NAME = "Untitled event request"


def _validate_item_list(value, field: str, allowed_items: set[str], *, quantity_required: bool) -> list[dict]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValidationError(f"{field} must be a list of objects.")

    validated = []
    for item in value:
        name = item.get("item")
        if name not in allowed_items:
            raise ValidationError(f"Unsupported {field} item: {name}.")

        entry = {"item": name}
        if quantity_required or "quantity" in item:
            quantity = item.get("quantity")
            if not isinstance(quantity, int) or quantity <= 0:
                raise ValidationError(f"{field} quantity must be a positive integer.")
            entry["quantity"] = quantity

        if field == "accessibility_needs" and "notes" in item:
            if not isinstance(item["notes"], str) or not item["notes"].strip():
                raise ValidationError("Accessibility notes must be a non-empty string.")
            entry["notes"] = item["notes"].strip()

        validated.append(entry)
    return validated


def _parse_registration_datetime(value, field: str) -> datetime:
    """registration_*_datetime are timestamptz columns, so the value must
    carry its own UTC offset -- a naive value would be silently read by
    Postgres as UTC, shifting it by Singapore's 8 hours.

    Returned in Singapore time (e.g. the browser's "2026-11-01T01:00:00Z"
    becomes "2026-11-01T09:00:00+08:00"). It's the same instant either way
    -- timestamptz stores an absolute moment in UTC -- but sending it with
    +08:00 keeps what's written readable as Singapore time, and gives the
    wall-clock value the session-start comparison below needs."""
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be an ISO datetime with a timezone offset.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"{field} must be an ISO datetime with a timezone offset.") from exc
    if parsed.tzinfo is None:
        raise ValidationError(f"{field} must be an ISO datetime with a timezone offset.")
    return parsed.astimezone(SINGAPORE_TZ)


def _validate_registration_window(validated: dict, *, for_submission: bool) -> None:
    """Registration period for a session: when registration_needs is true
    the organiser must say when registration opens and closes. Mutates
    `validated` in place (normalised ISO strings / None).

    The session's own start is a date + time WITHOUT a timezone (Singapore
    wall-clock time), while the registration window is timestamptz. To
    compare the two, the registration close is converted to Singapore time
    (by _parse_registration_datetime) and compared as wall-clock values --
    independent of whatever timezone the server itself runs in.
    """
    if validated.get("registration_needs") is False:
        # A session that doesn't need registration has no window; drop
        # anything stale left over from when the checkbox was ticked.
        for field in REGISTRATION_WINDOW_FIELDS:
            validated[field] = None
        return

    if for_submission and validated.get("registration_needs") is True:
        missing = [field for field in REGISTRATION_WINDOW_FIELDS if not validated.get(field)]
        if missing:
            raise ValidationError(
                f"{' and '.join(missing)} {'is' if len(missing) == 1 else 'are'} "
                "required when registration is needed."
            )

    parsed = {}
    for field in REGISTRATION_WINDOW_FIELDS:
        if validated.get(field) == "":
            validated[field] = None
        if field in validated and validated[field] is not None:
            parsed[field] = _parse_registration_datetime(validated[field], field)
            validated[field] = parsed[field].isoformat()

    opens = parsed.get("registration_start_datetime")
    closes = parsed.get("registration_end_datetime")
    if opens and closes and opens >= closes:
        raise ValidationError("registration_end_datetime must be after registration_start_datetime.")

    if closes and validated.get("preferred_start_date"):
        session_start = datetime.combine(
            date.fromisoformat(validated["preferred_start_date"]),
            time.fromisoformat(validated["preferred_start_time"])
            if validated.get("preferred_start_time")
            else time.min,
        )
        if closes.replace(tzinfo=None) > session_start:
            raise ValidationError(
                "registration_end_datetime must be on or before the session's preferred start date and time."
            )


def validate_event_payload(payload: dict, *, for_submission: bool) -> dict:
    if not isinstance(payload, dict):
        raise ValidationError("The event request body must be a JSON object.")
    unknown_fields = set(payload) - EVENT_FIELDS
    if unknown_fields:
        raise ValidationError(f"Unknown event fields: {', '.join(sorted(unknown_fields))}.")

    if not payload.get("name") or payload.get("name") == DRAFT_NAME:
        raise ValidationError("name is required.")
    if for_submission:
        missing = sorted(
            field for field in REQUIRED_FIELDS
            if field not in payload or payload[field] in (None, "", [])
        )
        if missing:
            raise ValidationError(f"Missing required fields: {', '.join(missing)}.")

    validated = dict(payload)
    for field in ("name", "description", "purpose"):
        if field in validated and (not isinstance(validated[field], str) or not validated[field].strip()):
            raise ValidationError(f"{field} must be a non-empty string.")
    if "special_requests" in validated and not isinstance(validated["special_requests"], str):
        raise ValidationError("special_requests must be a string.")

    if "registration_needs" in validated and not isinstance(validated["registration_needs"], bool):
        raise ValidationError("registration_needs must be true or false.")

    if "preferred_start_date" in validated:
        try:
            start_date = date.fromisoformat(validated["preferred_start_date"])
        except (TypeError, ValueError) as exc:
            raise ValidationError("preferred_start_date must be an ISO date (YYYY-MM-DD).") from exc
        if start_date <= date.today():
            raise ValidationError("preferred_start_date must be after today.")

    if validated.get("preferred_end_date") == "":
        validated["preferred_end_date"] = None
    if "preferred_end_date" in validated and validated["preferred_end_date"] is not None:
        try:
            end_date = date.fromisoformat(validated["preferred_end_date"])
        except (TypeError, ValueError) as exc:
            raise ValidationError("preferred_end_date must be an ISO date (YYYY-MM-DD).") from exc
        # Only cross-checked against the start date when both are in THIS
        # payload -- same convention as the time-range check below: a
        # partial edit touching only one of a related pair isn't
        # re-validated against whatever the other one already is in the DB.
        if "preferred_start_date" in validated:
            if end_date < start_date:
                raise ValidationError("preferred_end_date must be on or after preferred_start_date.")

    # No venue-hours window any more -- events are available 24 hours.
    for field in ("preferred_start_time", "preferred_end_time"):
        if validated.get(field) == "":
            validated[field] = None
        if field in validated and validated[field] is not None:
            try:
                validated[field] = time.fromisoformat(validated[field]).isoformat()
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"{field} must be an ISO time (HH:MM[:SS]).") from exc

    # The real invariant is "start date+time is before end date+time" as
    # ONE combined comparison, not two separate rules (date ordering, then
    # time ordering) kept in sync -- that's what correctly allows an end
    # TIME earlier than the start TIME as long as the end DATE is later
    # (e.g. 22:00 on day one to 06:00 on day two is a normal overnight
    # event), while still catching a same-day mistake. Only runs when all
    # four fields are in THIS payload, same partial-edit convention as the
    # date-only and (formerly) time-only checks above: a partial edit
    # touching just one of the four isn't re-validated against whatever
    # the others already are in the DB.
    if (
        validated.get("preferred_start_date")
        and validated.get("preferred_end_date")
        and validated.get("preferred_start_time")
        and validated.get("preferred_end_time")
    ):
        start_dt = datetime.combine(
            date.fromisoformat(validated["preferred_start_date"]),
            time.fromisoformat(validated["preferred_start_time"]),
        )
        end_dt = datetime.combine(
            date.fromisoformat(validated["preferred_end_date"]),
            time.fromisoformat(validated["preferred_end_time"]),
        )
        if start_dt >= end_dt:
            raise ValidationError("preferred_end_time must be after preferred_start_time.")
    elif validated.get("preferred_start_time") and validated.get("preferred_end_time"):
        # No end date given (or no start date to pair it with) -- the
        # ordinary same-day case, unchanged from before.
        if validated["preferred_start_time"] >= validated["preferred_end_time"]:
            raise ValidationError("preferred_end_time must be after preferred_start_time.")

    _validate_registration_window(validated, for_submission=for_submission)

    if "expected_attendance" in validated:
        if not isinstance(validated["expected_attendance"], int) or validated["expected_attendance"] <= 0:
            raise ValidationError("expected_attendance must be a positive integer.")
    if "room_layout" in validated and validated["room_layout"] not in ROOM_LAYOUTS:
        raise ValidationError(f"room_layout must be one of: {', '.join(sorted(ROOM_LAYOUTS))}.")
    if "equipment" in validated:
        validated["equipment"] = _validate_item_list(
            validated["equipment"], "equipment", EQUIPMENT, quantity_required=True
        )
    if "accessibility_needs" in validated:
        validated["accessibility_needs"] = _validate_item_list(
            validated["accessibility_needs"],
            "accessibility_needs",
            ACCESSIBILITY_NEEDS,
            quantity_required=False,
        )
    return validated


def _to_database_payload(payload: dict, existing: dict | None = None) -> dict:
    """Translate request fields to columns in the existing events table."""
    database_payload = dict(existing or {})
    database_payload.update(payload)
    database_payload["equipment_needed"] = {
        "equipment": database_payload.pop("equipment", []),
    }
    return database_payload


def _has_draft_data(values) -> bool:
    return any(value not in (None, "", [], False) for value in values)


def _normalize_draft_row(payload: dict, existing: dict | None = None) -> dict:
    """Blank-to-NULL normalisation for one draft row -- no completeness
    checks, since a draft may be saved half-filled."""
    database_payload = dict(existing or {})
    database_payload.update(payload)
    database_payload["name"] = database_payload.get("name") or DRAFT_NAME
    nullable_fields = (
        "preferred_start_date",
        "preferred_end_date",
        "preferred_start_time",
        "preferred_end_time",
        "room_layout",
        *REGISTRATION_WINDOW_FIELDS,
    )
    for field in nullable_fields:
        if database_payload.get(field) == "":
            database_payload[field] = None
    if database_payload.get("expected_attendance") == "":
        database_payload["expected_attendance"] = None
    if database_payload.get("registration_needs") is False:
        for field in REGISTRATION_WINDOW_FIELDS:
            database_payload[field] = None
    for field in REGISTRATION_WINDOW_FIELDS:
        if database_payload.get(field) is not None:
            database_payload[field] = _parse_registration_datetime(database_payload[field], field).isoformat()
    database_payload["equipment_needed"] = {
        "equipment": database_payload.pop("equipment", []),
    }
    return database_payload


def _draft_payload(payload: dict, existing: dict | None = None) -> dict:
    if not isinstance(payload, dict):
        raise ValidationError("The event request body must be a JSON object.")
    unknown_fields = set(payload) - EVENT_FIELDS
    if unknown_fields:
        raise ValidationError(f"Unknown event fields: {', '.join(sorted(unknown_fields))}.")
    if not _has_draft_data(payload.values()):
        raise ValidationError("At least one event field is required to save a draft.")
    return _normalize_draft_row(payload, existing)


def _from_database_event(event: SimpleNamespace) -> dict:
    equipment_needed = event.equipment_needed or {}
    if not isinstance(equipment_needed, dict):
        equipment_needed = {}
    return {
        "name": event.name,
        "description": event.description,
        "purpose": event.purpose,
        "preferred_start_date": event.preferred_start_date,
        "preferred_end_date": event.preferred_end_date,
        "preferred_start_time": event.preferred_start_time,
        "preferred_end_time": event.preferred_end_time,
        "expected_attendance": event.expected_attendance,
        "accessibility_needs": event.accessibility_needs or [],
        "room_layout": event.room_layout,
        "equipment": equipment_needed.get("equipment") or [],
        "registration_needs": event.registration_needs,
        # getattr: rows created before the registration window existed (and
        # test doubles) may not carry these attributes at all.
        "registration_start_datetime": getattr(event, "registration_start_datetime", None),
        "registration_end_datetime": getattr(event, "registration_end_datetime", None),
        "special_requests": event.special_requests,
    }


def _first_row(result) -> dict:
    if not result.data:
        raise ValidationError("The event database operation did not return an event.")
    return result.data[0] if isinstance(result.data, list) else result.data


# -- Sessions (one event request = one or more rows sharing shared_event_id) --


def _session_sort_key(row: dict):
    """Chronological; sessions with no date yet (half-filled drafts) last."""
    return (
        row.get("preferred_start_date") or "9999-12-31",
        row.get("preferred_start_time") or "",
        row.get("created_at") or "",
    )


def _group_response(rows: list[dict]) -> dict:
    rows = sorted(rows, key=_session_sort_key)
    first = rows[0] if rows else {}
    return {
        "shared_event_id": first.get("shared_event_id"),
        "name": first.get("name"),
        "description": first.get("description"),
        "purpose": first.get("purpose"),
        "sessions": rows,
    }


def _split_group_payload(payload) -> tuple[dict, list[dict]]:
    """Shape check for a group body; returns (shared fields, sessions)."""
    if not isinstance(payload, dict):
        raise ValidationError("The event request body must be a JSON object.")
    unknown_fields = set(payload) - GROUP_FIELDS
    if unknown_fields:
        raise ValidationError(f"Unknown event fields: {', '.join(sorted(unknown_fields))}.")
    sessions = payload.get("sessions")
    if not isinstance(sessions, list) or not sessions or any(not isinstance(s, dict) for s in sessions):
        raise ValidationError("sessions must be a non-empty list of session objects.")
    for index, session in enumerate(sessions, start=1):
        unknown_fields = set(session) - SESSION_FIELDS - {"id"}
        if unknown_fields:
            raise ValidationError(
                f"Session {index}: unknown session fields: {', '.join(sorted(unknown_fields))}."
            )
    shared = {field: payload[field] for field in SHARED_FIELDS if field in payload}
    return shared, sessions


def _session_fields(session: dict) -> dict:
    return {field: value for field, value in session.items() if field != "id"}


def _validate_session(index: int, total: int, payload: dict, *, for_submission: bool) -> dict:
    """validate_event_payload for one session, with the error message
    saying WHICH session is wrong when there's more than one."""
    try:
        return validate_event_payload(payload, for_submission=for_submission)
    except ValidationError as exc:
        if total == 1:
            raise
        raise ValidationError(f"Session {index}: {exc.message}") from exc


def validate_event_group(payload, *, for_submission: bool) -> list[dict]:
    """Validates every session (merged with the shared fields) BEFORE
    anything is written, so one bad session can't leave a half-created
    request behind. Returns the validated rows, in request order."""
    shared, sessions = _split_group_payload(payload)
    # Shared fields first, so a missing name is reported once rather than
    # as "Session 1: name is required."
    validate_event_payload(
        shared,
        for_submission=False,
    )
    if for_submission:
        missing = sorted(field for field in SHARED_FIELDS if shared.get(field) in (None, ""))
        if missing:
            raise ValidationError(f"Missing required fields: {', '.join(missing)}.")
    return [
        _validate_session(
            index, len(sessions), {**shared, **_session_fields(session)}, for_submission=for_submission
        )
        for index, session in enumerate(sessions, start=1)
    ]


def _load_sessions_with_status(event: SimpleNamespace, status: str) -> list[dict]:
    """Every session of the same request as `event` (owned by the same
    organiser) currently in `status`, oldest-first by date. A request
    created before sessions existed has no shared_event_id and is a group
    of one."""
    shared_event_id = getattr(event, "shared_event_id", None)
    if not shared_event_id:
        return [dict(vars(event))]
    result = (
        supabase.table("events")
        .select("*")
        .eq("shared_event_id", shared_event_id)
        .eq("organizer_id", event.organizer_id)
        .eq("status", status)
        .execute()
    )
    return sorted(result.data or [], key=_session_sort_key)


def _load_draft_sessions(event: SimpleNamespace) -> list[dict]:
    """Every still-draft session of the same request as `event`."""
    return _load_sessions_with_status(event, "draft")


def _insert_sessions(organizer_id: str, rows: list[dict], shared_event_id: str) -> list[dict]:
    for row in rows:
        row.pop("id", None)
        row["organizer_id"] = organizer_id
        row["status"] = "draft"
        row["shared_event_id"] = shared_event_id
    # One insert statement for all rows -- PostgREST runs it as a single
    # statement, so either every session is created or none is.
    result = supabase.table("events").insert(rows).select("*").execute()
    created = result.data or []
    for row in created:
        record_creation(row["id"], organizer_id)  # history row: NULL -> draft
    return created


def _submit_sessions(
    event_ids: list[str], from_status: str = "draft", submitted_by: str | None = None
) -> list[dict]:
    """Moves these sessions from `from_status` ("draft", or "rejected" for
    a resubmission) to "submitted", then on to review -- every status
    change through transition(), so each one is guarded and logged.

    The FIRST id is the session the caller acted on: if it lost a race
    (already moved by a double submit or another tab), the
    TransitionConflictError propagates before any sibling is touched.
    A sibling that already left `from_status` is skipped rather than
    failing the whole submit -- the same tolerance the old conditional
    update had. `submitted_by` is recorded as changed_by (the organiser)."""
    submitted_ids = []
    for index, event_id in enumerate(event_ids):
        try:
            transition(event_id, "submitted", submitted_by, expected_from=from_status)
        except TransitionConflictError:
            if index == 0:
                raise
            continue
        submitted_ids.append(event_id)

    sessions = supabase.table("events").select("*").in_("id", submitted_ids).execute().data or []
    submitted = [session for session in sessions if session["status"] == "submitted"]

    # A resubmitted session still has the coordinator who rejected it: it
    # goes straight back to their review queue, keeping the request's one
    # coordinator. Only sessions with nobody assigned go through
    # assignment below. Attributed to the organiser, whose submit caused it
    # (docs/design-decisions.md, changed_by).
    for session in submitted:
        if session.get("coordinator_id"):
            transition(session["id"], "under_review", submitted_by, expected_from="submitted")

    # Per Customer Briefing Step 3 / Event Status Management: submission
    # should trigger coordinator auto-assignment, moving the event to
    # "under_review". If nobody's available, it stays "submitted" and
    # unassigned -- an intentionally open case per coordinator_service's
    # own docstring, not an error here. Called ONCE, after every session
    # is submitted: the request gets one coordinator for all its sessions
    # (assign_initial_coordinator covers the request's other submitted
    # sessions too, and reuses the request's coordinator if it has one).
    unassigned = [session for session in submitted if not session.get("coordinator_id")]
    if unassigned:
        try:
            assign_initial_coordinator(unassigned[0]["id"], actor=submitted_by)
        except NoCoordinatorAvailableError:
            pass

    result = supabase.table("events").select("*").in_("id", submitted_ids).execute()
    return result.data or []


def create_event_request(organizer_id: str, payload: dict) -> dict:
    """Create AND submit a new multi-session request in one step: every
    session must pass submission validation before any row is written."""
    rows = [_to_database_payload(row) for row in validate_event_group(payload, for_submission=True)]
    # Submitting without ever saving a draft: the request's shared_event_id
    # is generated here, server-side, and stamped on every session row.
    shared_event_id = str(uuid.uuid4())
    inserted = _insert_sessions(organizer_id, rows, shared_event_id)
    if not inserted:
        raise ValidationError("The event database operation did not return an event.")
    return _group_response(_submit_sessions([row["id"] for row in inserted], submitted_by=organizer_id))


def create_draft_request(organizer_id: str, payload: dict) -> dict:
    shared, sessions = _split_group_payload(payload)
    if not _has_draft_data([*shared.values(), *(v for s in sessions for v in _session_fields(s).values())]):
        raise ValidationError("At least one event field is required to save a draft.")
    rows = [_normalize_draft_row({**shared, **_session_fields(session)}) for session in sessions]
    # First save of a new draft: shared_event_id is generated here, server-side.
    shared_event_id = str(uuid.uuid4())
    inserted = _insert_sessions(organizer_id, rows, shared_event_id)
    if not inserted:
        raise ValidationError("The event database operation did not return an event.")
    return _group_response(inserted)


def edit_event_request(event_id: str, event: SimpleNamespace, payload: dict):
    # validate_event_payload requires `name`, so a validated payload is
    # never empty -- no separate "at least one field" check is needed.
    payload = validate_event_payload(payload, for_submission=False)
    database_payload = _to_database_payload(payload, _from_database_event(event))
    result = supabase.table("events").update(database_payload).eq("id", event_id).select("*").execute()
    return _first_row(result)


def save_draft_request(event_id: str, event: SimpleNamespace, payload: dict) -> dict:
    """Save edits to an editable request (authz has already checked the
    caller owns it and it's "draft" or "rejected").

    - draft: the whole request is edited together. Sessions in the body
      with an `id` update that session, sessions without one are added,
      and draft sessions missing from the body are removed.
    - rejected: only this one session is edited -- its siblings have
      their own review outcome and aren't touched. Adding or removing
      sessions isn't allowed.
    """
    shared, sessions = _split_group_payload(payload)
    if not _has_draft_data([*shared.values(), *(v for s in sessions for v in _session_fields(s).values())]):
        raise ValidationError("At least one event field is required to save a draft.")

    if event.status != "draft":
        if len(sessions) != 1 or sessions[0].get("id", event_id) != event_id:
            raise ValidationError("A rejected event request can only be edited one session at a time.")
        row = _normalize_draft_row(
            {**shared, **_session_fields(sessions[0])}, _from_database_event(event)
        )
        result = supabase.table("events").update(row).eq("id", event_id).select("*").execute()
        return _group_response([_first_row(result)])

    existing = {row["id"]: row for row in _load_draft_sessions(event)}
    # A legacy single-row draft gets its group id the first time it's saved.
    shared_event_id = getattr(event, "shared_event_id", None) or str(uuid.uuid4())

    updates, inserts = [], []
    for index, session in enumerate(sessions, start=1):
        session_id = session.get("id")
        if session_id is not None and session_id not in existing:
            raise ValidationError(f"Session {index} does not belong to this draft event request.")
        current = _from_database_event(SimpleNamespace(**existing[session_id])) if session_id else None
        row = _normalize_draft_row({**shared, **_session_fields(session)}, current)
        row["shared_event_id"] = shared_event_id
        if session_id:
            updates.append((session_id, row))
        else:
            inserts.append(row)
    removed = set(existing) - {session_id for session_id, _ in updates}

    # Not one transaction (supabase-py has none to offer), so order matters:
    # write the new state first and remove dropped sessions last, so a
    # failure part-way leaves extra sessions behind rather than lost ones.
    for session_id, row in updates:
        supabase.table("events").update(row).eq("id", session_id).eq("status", "draft").execute()
    if inserts:
        _insert_sessions(event.organizer_id, inserts, shared_event_id)
    if removed:
        supabase.table("events").delete().in_("id", sorted(removed)).eq("status", "draft").execute()

    result = (
        supabase.table("events")
        .select("*")
        .eq("shared_event_id", shared_event_id)
        .eq("organizer_id", event.organizer_id)
        .eq("status", "draft")
        .execute()
    )
    return _group_response(result.data or [])


def delete_draft_request(event_id: str, event: SimpleNamespace) -> None:
    """Permanently remove a draft event request -- every one of its
    sessions, since they're only separate rows, not separate requests.

    Callers must gate this through app.authz's event.delete action first
    (rule_event_delete restricts it to the owning organizer while status
    is still "draft") -- this function only re-checks status on the
    SIBLING rows, which authz never saw, the same trust boundary
    edit_event_request/submit_event_request rely on for their own
    authz-gated preconditions.
    """
    shared_event_id = getattr(event, "shared_event_id", None)
    if not shared_event_id:
        supabase.table("events").delete().eq("id", event_id).execute()
        return
    (
        supabase.table("events")
        .delete()
        .eq("shared_event_id", shared_event_id)
        .eq("organizer_id", event.organizer_id)
        .eq("status", "draft")
        .execute()
    )


def submit_event_request(event_id: str, event: SimpleNamespace):
    """Submit this request (authz has checked the caller owns it and it's
    "draft" or "rejected").

    - draft: every draft session of the request is submitted together.
    - rejected: a resubmission. Every rejected session of the request goes
      back together -- the organiser fixes them on one page -- and sessions
      with any other outcome (approved, in planning, ...) are untouched.

    All the sessions are validated before any of them changes status.
    Returns the row for `event_id` itself (the session the caller submitted
    from).
    """
    sessions = _load_sessions_with_status(event, event.status)
    for index, session in enumerate(sessions, start=1):
        _validate_session(
            index,
            len(sessions),
            _from_database_event(SimpleNamespace(**session)),
            for_submission=True,
        )
    # The session the caller submitted from goes first, so a lost race on
    # it refuses the submit before any sibling moves (see _submit_sessions).
    ordered_ids = [event_id] + [session["id"] for session in sessions if session["id"] != event_id]
    submitted = _submit_sessions(ordered_ids, from_status=event.status, submitted_by=event.organizer_id)
    return next(row for row in submitted if row["id"] == event_id)


def _attach_rejections(rows: list[dict]) -> list[dict]:
    """Adds `rejection` to each rejected session: the coordinator's most
    recent rejection of it, {"reason", "rejected_at", "rejected_by"}, read
    from event_status_log (where reject_event_request records it). Only the
    latest one, since a session rejected, fixed and resubmitted can be
    rejected again -- the organiser needs the reason that applies now.
    Other sessions are returned unchanged."""
    rejected_ids = [row["id"] for row in rows if row.get("status") == "rejected"]
    if not rejected_ids:
        return rows
    result = (
        supabase.table("event_status_log")
        .select("event_id, reason, changed_at, profiles(name)")
        .in_("event_id", rejected_ids)
        .eq("to_status", "rejected")
        .execute()
    )
    latest = {}
    for entry in sorted(result.data or [], key=lambda entry: entry.get("changed_at") or ""):
        latest[entry["event_id"]] = entry  # later entries overwrite earlier ones
    for row in rows:
        entry = latest.get(row["id"])
        if row.get("status") == "rejected" and entry:
            row["rejection"] = {
                "reason": entry.get("reason"),
                "rejected_at": entry.get("changed_at"),
                "rejected_by": (entry.get("profiles") or {}).get("name"),
            }
    return rows


def list_event_sessions(event: SimpleNamespace, user) -> dict:
    """Every session of the same request as `event` that `user` may see,
    with the coordinator's rejection reason on any rejected session.
    Sibling rows are filtered through the same event.view rule the route
    used for `event` itself -- e.g. a coordinator assigned to one session
    doesn't see siblings assigned to someone else."""
    shared_event_id = getattr(event, "shared_event_id", None)
    if not shared_event_id:
        return _group_response(_attach_rejections([dict(vars(event))]))
    result = supabase.table("events").select("*").eq("shared_event_id", shared_event_id).execute()
    visible = [row for row in result.data or [] if can(user, EVENT_VIEW, SimpleNamespace(**row))]
    return _group_response(_attach_rejections(visible))


def _decide(event_id: str, event: SimpleNamespace, to_status: str, decided_by: str, reason: str | None):
    """Moves an under_review event to `to_status`.

    The authz rule (rule_event_approve / rule_event_reject) has already
    checked the caller is the assigned coordinator and the event is
    under_review. The write goes through app.events.transitions.transition(),
    conditional on status still being under_review, so two decisions racing
    each other (e.g. a double click, or approve and reject from two tabs)
    can't both land -- the second matches no row and gets a 409
    TransitionConflictError instead of silently winning. transition() also
    writes the event_status_log row (same columns as before) and enforces
    the rejection reason.
    """
    return transition(event_id, to_status, decided_by, reason=reason, expected_from="under_review")


def approve_event_request(event_id: str, event: SimpleNamespace, approved_by: str):
    """Event Review and Approval: coordinator approves -> "approved"
    (Week 4: "Approval = sufficient info for planning")."""
    return _decide(event_id, event, "approved", approved_by, None)


def reject_event_request(event_id: str, event: SimpleNamespace, rejected_by: str, reason):
    """Event Review and Approval: coordinator rejects -> "rejected".
    A reason is required (Week 4: "Free text reason is reasonable";
    rejected requests keep a record of the decision) so the organiser
    knows what to fix before resubmitting. Enforced (and trimmed) by
    transition() from transitions.REASON_REQUIRED, with the same message
    as before.

    Rejection applies to the whole request, not just the session the
    coordinator happened to open (Aaralyn, IS-46 follow-up): every
    under_review sibling sharing its shared_event_id goes with it, so the
    organiser fixes and resubmits them together (submit_event_request
    already resubmits every rejected session of a request at once).

    The session authz checked is decided first, so a lost race on it
    (409 TransitionConflictError) refuses the whole rejection before any
    sibling is touched. Siblings are then moved only if they are still
    under_review AND assigned to this coordinator -- authz never saw those
    rows, so the coordinator check is re-done here (one coordinator per
    request makes it a no-op in practice). Each sibling goes through
    transition() too, so each is guarded and logged with the same reason;
    one that already left under_review is skipped, not overwritten."""
    rejected = _decide(event_id, event, "rejected", rejected_by, reason)
    for session in _load_sessions_with_status(event, "under_review"):
        if session["id"] == event_id or session.get("coordinator_id") != rejected_by:
            continue
        try:
            transition(session["id"], "rejected", rejected_by, reason=reason, expected_from="under_review")
        except TransitionConflictError:
            continue
    return rejected


def list_event_requests(user, status: str | None = None) -> list[dict]:
    """Every event request the caller is entitled to see, scoped per
    role -- see rule_event_list's *** warning *** in app.authz.rules'
    module docstring: passing that role-only check does NOT mean "every
    event", it means "attempt a list at all". The actual per-row scoping
    is this function's job, not authz's:
      - event_organizer sees events where organizer_id == user.id
        (View Event Requests story: "all the event requests that have
        been created or drafted by him or her")
      - event_coordinator sees events where coordinator_id == user.id
        (the equivalent coordinator-side grant referenced by that same
        rule)
    A user holding both roles sees the UNION of both, not just one --
    multi-role union is the same structural stance app.authz.rules takes
    everywhere else (see that module's docstring on why it's `in
    user.roles`, never `user.role ==`, throughout).

    `status` is the optional filter from "Can filter based of status of
    events" -- applied after the ownership scoping above, never in place
    of it.

    NOT implemented here: replying to Event Coordinator feedback on a
    request "under review" (the rest of that same acceptance criterion).
    That depends on a clarification/feedback record that doesn't exist
    yet -- it belongs to Event Review and Approval (Aaralyn), which
    sprint planning explicitly deferred past Sprint 1 ("leave this to a
    later date"). Wiring a reply flow against a table that doesn't exist
    would be guessing at a shape someone else's story still needs to
    define.
    """
    conditions = []
    if "event_organizer" in user.roles:
        conditions.append(f"organizer_id.eq.{user.id}")
    if "event_coordinator" in user.roles:
        conditions.append(f"coordinator_id.eq.{user.id}")
    if not conditions:
        # rule_event_list already blocks a caller holding neither role
        # from reaching this function at all -- this is defence in depth,
        # not the real gate, so that a future bug in that rule fails
        # closed (empty list) rather than open (every event).
        return []

    if status is not None and status not in EVENT_STATUSES:
        raise ValidationError(f"status must be one of: {', '.join(sorted(EVENT_STATUSES))}.")

    query = supabase.table("events").select("*").or_(",".join(conditions))
    if status is not None:
        query = query.eq("status", status)
    result = query.order("created_at", desc=True).execute()
    return result.data or []