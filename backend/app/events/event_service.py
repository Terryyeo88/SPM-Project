"""Business logic for event request creation, editing, and submission."""

from __future__ import annotations

from datetime import date, datetime, time
from types import SimpleNamespace

from app.events.coordinator_service import NoCoordinatorAvailableError, assign_initial_coordinator
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
EVENT_FIELDS = {
    "name",
    "description",
    "purpose",
    "preferred_start_date",
    "preferred_end_date",
    "preferred_start_time",
    "preferred_end_time",
    "expected_attendance",
    "accessibility_needs",
    "room_layout",
    "equipment",
    "registration_needs",
    "special_requests",
}
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


def _draft_payload(payload: dict, existing: dict | None = None) -> dict:
    if not isinstance(payload, dict):
        raise ValidationError("The event request body must be a JSON object.")
    unknown_fields = set(payload) - EVENT_FIELDS
    if unknown_fields:
        raise ValidationError(f"Unknown event fields: {', '.join(sorted(unknown_fields))}.")
    if not any(value not in (None, "", [], False) for value in payload.values()):
        raise ValidationError("At least one event field is required to save a draft.")

    database_payload = dict(existing or {})
    database_payload.update(payload)
    database_payload["name"] = database_payload.get("name") or DRAFT_NAME
    nullable_fields = (
        "preferred_start_date",
        "preferred_end_date",
        "preferred_start_time",
        "preferred_end_time",
        "room_layout",
    )
    for field in nullable_fields:
        if database_payload.get(field) == "":
            database_payload[field] = None
    if database_payload.get("expected_attendance") == "":
        database_payload["expected_attendance"] = None
    database_payload["equipment_needed"] = {
        "equipment": database_payload.pop("equipment", []),
    }
    return database_payload


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
        "special_requests": event.special_requests,
    }


def _first_row(result) -> dict:
    if not result.data:
        raise ValidationError("The event database operation did not return an event.")
    return result.data[0] if isinstance(result.data, list) else result.data


def create_event_request(organizer_id: str, payload: dict):
    payload = validate_event_payload(payload, for_submission=False)
    database_payload = _to_database_payload(payload)
    database_payload["organizer_id"] = organizer_id
    database_payload["status"] = "draft"
    result = supabase.table("events").insert(database_payload).select("*").execute()
    return _first_row(result)


def create_draft_request(organizer_id: str, payload: dict):
    database_payload = _draft_payload(payload)
    database_payload["organizer_id"] = organizer_id
    database_payload["status"] = "draft"
    result = supabase.table("events").insert(database_payload).select("*").execute()
    return _first_row(result)


def edit_event_request(event_id: str, event: SimpleNamespace, payload: dict):
    payload = validate_event_payload(payload, for_submission=False)
    if not payload:
        raise ValidationError("At least one event field is required.")
    database_payload = _to_database_payload(payload, _from_database_event(event))
    result = supabase.table("events").update(database_payload).eq("id", event_id).select("*").execute()
    return _first_row(result)


def save_draft_request(event_id: str, event: SimpleNamespace, payload: dict):
    database_payload = _draft_payload(payload, _from_database_event(event))
    result = supabase.table("events").update(database_payload).eq("id", event_id).select("*").execute()
    return _first_row(result)


def delete_draft_request(event_id: str, event: SimpleNamespace) -> None:
    """Permanently remove a draft event request.

    Callers must gate this through app.authz's event.delete action first
    (rule_event_delete restricts it to the owning organizer while status
    is still "draft") -- this function itself performs no status check,
    the same trust boundary edit_event_request/submit_event_request rely
    on for their own authz-gated preconditions.
    """
    supabase.table("events").delete().eq("id", event_id).execute()


def submit_event_request(event_id: str, event: SimpleNamespace):
    validate_event_payload(_from_database_event(event), for_submission=True)
    result = (
        supabase.table("events")
        .update({"status": "submitted"})
        .eq("id", event_id)
        .select("*")
        .execute()
    )
    submitted_event = _first_row(result)

    # Per Customer Briefing Step 3 / Event Status Management: submission
    # should trigger coordinator auto-assignment, moving the event to
    # "under_review". If nobody's available, it stays "submitted" and
    # unassigned -- an intentionally open case per coordinator_service's
    # own docstring, not an error here.
    try:
        assign_initial_coordinator(event_id)
    except NoCoordinatorAvailableError:
        return submitted_event

    result = supabase.table("events").select("*").eq("id", event_id).single().execute()
    return result.data


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