"""The caller's own contact details and communication preferences (IS-68).

Columns on public.profiles (20261030000000_profile_contact_preferences.sql,
tightened by 20261031000000_profile_contact_rules.sql):

  phone         text     nullable; +65 followed by 8 digits, stored as
                         "+6591234567" (no spaces)
  organisation  text     nullable; READ-ONLY here (see below)
  notify_email  boolean  not null, default true
  notify_sms    boolean  not null, default false

Acceptance criteria (IS-68, agreed with Justin 31 Oct):
  - only phone and the two preferences are editable; name, email and
    organisation are shown read-only
  - phone is optional; when given it is +65 followed by 8 digits
  - email is selected by default and at least one preference stays on
  - SMS can only be on when a phone number is saved
  - an update that fails validation leaves the stored profile unchanged
  - a user can only update their own profile

Organisation is read-only because the customer says organisations and
organisers are set up outside the system ("some integration process
outside the scope of this release", Week 4 clarification), so a user
doesn't type their own in. It is still returned by GET /me, and
registration_service._db_profile_organisation still copies it into a
registration when the attendee ticks "include organisation".

OWN PROFILE ONLY. Every read and write here takes the caller's id from
their token (app/me/routes.py passes current_user().id) and scopes the
query with .eq("id", user_id). The update payload refuses "id", "email"
and "organisation" outright (400, not ignored).

The rules are checked against the profile AS IT WILL BE after the update
(the saved row merged with the change), so a partial update can't break
them: e.g. {"phone": null} is refused while SMS is on. The database checks
the same rules (profiles_notify_at_least_one, profiles_sms_needs_phone,
profiles_phone_sg) in case anything writes around this service.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from app.extensions import supabase
from app.shared.errors import NotFoundError, ValidationError

TABLE = "profiles"

# What GET /me returns alongside id, email, name and roles.
CONTACT_FIELDS = ("phone", "organisation", "notify_email", "notify_sms")

# What PATCH /me/profile may change.
EDITABLE_FIELDS = ("phone", "notify_email", "notify_sms")

# Refused with their own code so a caller sees why: "id" would name another
# profile, "email" is the login identity (Supabase Auth's, mirrored on
# profiles), "organisation" comes from outside the system.
FORBIDDEN_FIELDS = ("id", "email", "organisation")

# Stored form: +65 then 8 digits, nothing else. Input may contain spaces or
# hyphens ("+65 9123 4567"); they are removed before checking. Same rule as
# the database's profiles_phone_sg check.
SG_PHONE_PATTERN = re.compile(r"^\+65[0-9]{8}$")
PHONE_FORMAT_MESSAGE = "Enter a Singapore number: +65 followed by 8 digits, e.g. +65 9123 4567."
AT_LEAST_ONE_MESSAGE = "Choose at least one way to be contacted: email or SMS."
SMS_NEEDS_PHONE_MESSAGE = "Add a phone number to turn on SMS notifications."


def get_contact(user_id: str) -> dict:
    """The four fields for the caller's own profile."""
    row = _db_own_row(user_id, CONTACT_FIELDS)
    return _contact(row)


def normalise_phone(value: str) -> str:
    """"+65 9123-4567" -> "+6591234567". Doesn't check the result."""
    return re.sub(r"[\s-]", "", value)


def validate_profile_update(payload) -> dict:
    """Checks the shape of a partial update on its own: only the keys
    present are changed. phone takes a string or null (blank -> null);
    the preferences take true / false. Returns the cleaned changes. The
    rules that depend on the whole profile are check_profile_rules'."""
    if not isinstance(payload, dict):
        raise ValidationError("The profile update must be a JSON object.")

    forbidden = [field for field in FORBIDDEN_FIELDS if field in payload]
    if forbidden:
        raise ValidationError(
            f"{' and '.join(forbidden)} cannot be changed here.", code="profile_field_not_editable"
        )
    unknown = set(payload) - set(EDITABLE_FIELDS)
    if unknown:
        raise ValidationError(f"Unknown profile fields: {', '.join(sorted(unknown))}.")
    if not payload:
        raise ValidationError("Nothing to update.")

    changes: dict = {}
    if "phone" in payload:
        changes["phone"] = _clean_phone(payload["phone"])
    for field in ("notify_email", "notify_sms"):
        if field in payload:
            value = payload[field]
            if not isinstance(value, bool):
                raise ValidationError(f"{field} must be true or false.")
            changes[field] = value
    return changes


def check_profile_rules(profile: dict) -> None:
    """The rules on the profile as a whole (after the update)."""
    if not (profile.get("notify_email") or profile.get("notify_sms")):
        raise ValidationError(AT_LEAST_ONE_MESSAGE)
    if profile.get("notify_sms") and not profile.get("phone"):
        raise ValidationError(SMS_NEEDS_PHONE_MESSAGE)


def update_own_profile(user_id: str, payload) -> dict:
    """Validate, then write to the caller's own row only. Returns the four
    fields as saved. Nothing is written if any check fails."""
    changes = validate_profile_update(payload)
    current = _db_own_row(user_id, EDITABLE_FIELDS)
    check_profile_rules({**current, **changes})

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


def _clean_phone(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValidationError("phone must be text or null.")
    if not value.strip():
        return None
    phone = normalise_phone(value.strip())
    if not SG_PHONE_PATTERN.match(phone):
        raise ValidationError(PHONE_FORMAT_MESSAGE)
    return phone


def _db_own_row(user_id: str, fields) -> dict:
    result = (
        supabase.table(TABLE)
        .select(", ".join(fields))
        .eq("id", user_id)
        .maybe_single()
        .execute()
    )
    # maybe_single().execute() returns None itself when no row matches.
    if result is None or not result.data:
        raise NotFoundError("Profile not found.")
    return result.data


def _contact(row: dict) -> dict:
    return {field: row.get(field) for field in CONTACT_FIELDS}
