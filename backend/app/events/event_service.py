"""Business logic for event request creation, editing, and submission."""

from __future__ import annotations

from datetime import date, time
from types import SimpleNamespace

from app.extensions import supabase
from app.shared.errors import ValidationError

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
    "preferred_date",
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
    "preferred_date",
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

    if "preferred_date" in validated:
        try:
            preferred_date = date.fromisoformat(validated["preferred_date"])
        except (TypeError, ValueError) as exc:
            raise ValidationError("preferred_date must be an ISO date (YYYY-MM-DD).") from exc
        if preferred_date <= date.today():
            raise ValidationError("preferred_date must be after today.")

    for field in ("preferred_start_time", "preferred_end_time"):
        if validated.get(field) == "":
            validated[field] = None
        if field in validated and validated[field] is not None:
            try:
                validated[field] = time.fromisoformat(validated[field]).isoformat()
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"{field} must be an ISO time (HH:MM[:SS]).") from exc
    if validated.get("preferred_start_time") and validated.get("preferred_end_time"):
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
    for field in ("preferred_date", "preferred_start_time", "preferred_end_time", "room_layout"):
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
        "preferred_date": event.preferred_date,
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


def submit_event_request(event_id: str, event: SimpleNamespace):
    validate_event_payload(_from_database_event(event), for_submission=True)
    result = (
        supabase.table("events")
        .update({"status": "submitted"})
        .eq("id", event_id)
        .select("*")
        .execute()
    )
    return _first_row(result)
