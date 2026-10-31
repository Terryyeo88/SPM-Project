"""The caller's own contact details and communication preferences (IS-68).

Four nullable columns on public.profiles
(20261030000000_profile_contact_preferences.sql):

  phone         text     the Edit Profile wireframe's Phone Number
  organisation  text     Organisation (optional)
  notify_email  boolean  Communication Preferences: Email notifications
  notify_sms    boolean  Communication Preferences: SMS notifications

NULL is "not given yet": every profile that existed before IS-68 has NULL
in all four, and blank text is stored as NULL, never ''. For the two
preferences NULL is distinct from false ("chose not to").

OWN PROFILE ONLY -- the guard of this ticket. Every read and write here
takes the caller's id from their token (app/me/routes.py passes
current_user().id) and scopes the query with .eq("id", user_id). The
update payload refuses "id" and "email" outright (400, not ignored), so a
request cannot name another profile or change the login email.

Nothing reads the two preferences yet: notifications are in-app only
(IS-69), and each registration keeps its own notify_email / notify_sms.
Justin's register form prefills from them (lib/registrations.js
prefillFromProfile) -- see docs/design-decisions.md and
docs/open-questions.md (IS-68).
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.extensions import supabase
from app.registrations.registration_service import PHONE_PATTERN
from app.shared.errors import NotFoundError, ValidationError

TABLE = "profiles"

CONTACT_FIELDS = ("phone", "organisation", "notify_email", "notify_sms")

# Never writable here: "id" would name another profile, "email" is the
# login identity (Supabase Auth's, mirrored on profiles) and isn't part of
# this ticket. Refused with their own code so a caller sees why.
FORBIDDEN_FIELDS = ("id", "email")

ORGANISATION_MAX_LENGTH = 200


def get_contact(user_id: str) -> dict:
    """The four fields for the caller's own profile, NULLs included."""
    result = (
        supabase.table(TABLE)
        .select(", ".join(CONTACT_FIELDS))
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    # maybe_single().execute() returns None itself when no row matches.
    if result is None or not result.data:
        raise NotFoundError("Profile not found.")
    return _contact(result.data)


def validate_profile_update(payload) -> dict:
    """A partial update: only the keys present are changed. Text fields
    take a string or null (blank -> null); the preferences take
    true / false / null. "id" and "email" are refused, as is anything else
    that isn't one of the four fields."""
    if not isinstance(payload, dict):
        raise ValidationError("The profile update must be a JSON object.")

    forbidden = [field for field in FORBIDDEN_FIELDS if field in payload]
    if forbidden:
        raise ValidationError(
            f"{' and '.join(forbidden)} cannot be changed here.", code="profile_field_not_editable"
        )
    unknown = set(payload) - set(CONTACT_FIELDS)
    if unknown:
        raise ValidationError(f"Unknown profile fields: {', '.join(sorted(unknown))}.")
    if not payload:
        raise ValidationError("Nothing to update.")

    changes: dict = {}
    if "phone" in payload:
        phone = _optional_text(payload["phone"], "phone")
        if phone is not None and not PHONE_PATTERN.match(phone):
            raise ValidationError("Enter a valid phone number, e.g. 9123 4567 or +65 9123 4567.")
        changes["phone"] = phone
    if "organisation" in payload:
        organisation = _optional_text(payload["organisation"], "organisation")
        if organisation is not None and len(organisation) > ORGANISATION_MAX_LENGTH:
            raise ValidationError(f"Organisation can be at most {ORGANISATION_MAX_LENGTH} characters.")
        changes["organisation"] = organisation
    for field in ("notify_email", "notify_sms"):
        if field in payload:
            value = payload[field]
            if value is not None and not isinstance(value, bool):
                raise ValidationError(f"{field} must be true, false or null.")
            changes[field] = value
    return changes


def update_own_profile(user_id: str, payload) -> dict:
    """Validate, then write to the caller's own row only. Returns the four
    fields as saved."""
    changes = validate_profile_update(payload)
    result = (
        supabase.table(TABLE)
        .update({**changes, "updated_at": datetime.now(UTC).isoformat()})
        .eq("id", user_id)
        .execute()
    )
    rows = result.data or []
    if not rows:
        raise NotFoundError("Profile not found.")
    return _contact(rows[0])


def _optional_text(value, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError(f"{field} must be text or null.")
    return value.strip() or None


def _contact(row: dict) -> dict:
    return {field: row.get(field) for field in CONTACT_FIELDS}
