"""
Attendee Registration (Justin).

  As an Attendee, I want to register for an event, so that I can secure a
  place to attend the event.

  - The Attendee can register only for an event that is confirmed and
    enabled for registration.
  - The Attendee can register only during the permitted registration period.
  - The Attendee can provide the required registration information.
  - Given that registration capacity is available, when Attendee registers,
    the Attendee's registration is recorded as confirmed.
  - Given that registration capacity has been reached and a waiting list is
    available, when Attendee registers, the Attendee's registration is
    recorded as waitlisted.

Decisions (docs/design-decisions.md, "Attendee Registration"):
  - Attendees register for a SESSION (one events row): registration_needs
    and the registration window are already per session.
  - Capacity is the session's expected_attendance (NULL = no limit).
  - Every session has a waiting list, first come first served.
  - Registration information follows the Edit Profile wireframe: email and
    phone (required), which notifications they want (email and/or SMS, at
    least one), whether to include their organisation, and optional notes.
    Name and organisation are the profile's and can't be changed here --
    the attendee only chooses whether their organisation is included. The
    page prefills everything it can from the profile; what's stored is what
    they submit for THIS registration.
  - Withdrawing (the wireframe's Withdraw Registration / Leave Waiting
    List) frees the place for the first waitlisted attendee, who is moved up
    in the same database call (public.withdraw_registration).

The confirmed-or-waitlisted decision and the insert happen in ONE database
call, public.register_attendee, which locks the session row first -- so two
attendees racing for the last place can't both be confirmed. Everything
here is validation before that call and wording after it.

Attendees only ever see a session's PUBLIC fields (_PUBLIC_FIELDS) -- the
briefing: "an Attendee should not be able to view internal planning
information".
"""

from __future__ import annotations

import re
from datetime import date, datetime

from app.events.event_service import SINGAPORE_TZ
from app.extensions import supabase
from app.shared.errors import NotFoundError, ValidationError

_PUBLIC_FIELDS = (
    "id, shared_event_id, name, description, "
    "preferred_start_date, preferred_end_date, preferred_start_time, preferred_end_time, "
    "expected_attendance, registration_start_datetime, registration_end_datetime"
)

PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9 \-]{5,18}[0-9]$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NOTES_MAX_LENGTH = 500


# -- validation --------------------------------------------------------------


_FIELDS = {"email", "phone", "notify_email", "notify_sms", "include_organisation", "notes"}


def validate_registration_details(payload) -> dict:
    """{"email", "phone": required; "notify_email", "notify_sms": booleans,
    at least one true; "include_organisation": boolean, default false;
    "notes": optional} -> cleaned values."""
    if not isinstance(payload, dict):
        raise ValidationError("The registration body must be a JSON object.")
    unknown = set(payload) - _FIELDS
    if unknown:
        raise ValidationError(f"Unknown registration fields: {', '.join(sorted(unknown))}.")

    email = payload.get("email")
    if not isinstance(email, str) or not email.strip():
        raise ValidationError("An email address is required to register.")
    email = email.strip().lower()
    if len(email) > 254 or not EMAIL_PATTERN.match(email):
        raise ValidationError("Enter a valid email address.")

    phone = payload.get("phone")
    if not isinstance(phone, str) or not phone.strip():
        raise ValidationError("A phone number is required to register.")
    phone = phone.strip()
    if not PHONE_PATTERN.match(phone):
        raise ValidationError("Enter a valid phone number, e.g. 9123 4567 or +65 9123 4567.")

    notify_email = payload.get("notify_email", False)
    notify_sms = payload.get("notify_sms", False)
    include_organisation = payload.get("include_organisation", False)
    for name, value in (
        ("notify_email", notify_email),
        ("notify_sms", notify_sms),
        ("include_organisation", include_organisation),
    ):
        if not isinstance(value, bool):
            raise ValidationError(f"{name} must be true or false.")
    if not (notify_email or notify_sms):
        raise ValidationError("Choose at least one way to be notified: email or SMS.")

    notes = payload.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise ValidationError("notes must be text.")
    notes = (notes or "").strip()
    if len(notes) > NOTES_MAX_LENGTH:
        raise ValidationError(f"Notes can be at most {NOTES_MAX_LENGTH} characters.")
    return {
        "email": email,
        "phone": phone,
        "notify_email": notify_email,
        "notify_sms": notify_sms,
        "include_organisation": include_organisation,
        "notes": notes or None,
    }


# -- registering -------------------------------------------------------------


def _format_sgt(value) -> str:
    if not value:
        return ""
    moment = datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(SINGAPORE_TZ)
    hour = int(moment.strftime("%I"))
    return f"{moment.day} {moment.strftime('%b %Y')}, {hour}:{moment.strftime('%M %p')}"


def register(event, attendee_id: str, payload) -> dict:
    """Register `attendee_id` for the session `event` (already authorised by
    rule_event_register: confirmed and enabled for registration). Returns the
    registration row, whose status is "confirmed" or "waitlisted"."""
    details = validate_registration_details(payload)
    # The organisation is the profile's, never typed in here: the attendee
    # only chooses whether to include it. Profiles have no organisation
    # column yet, so today this is always None.
    details["organisation"] = _db_profile_organisation(attendee_id) if details["include_organisation"] else None
    result = _db_register(event.id, attendee_id, details) or {}
    outcome = result.get("outcome")

    if outcome == "registered":
        return result["registration"]
    if outcome == "already_registered":
        raise ValidationError("You're already registered for this session.")
    if outcome == "not_started":
        raise ValidationError(
            f"Registration for this session opens on {_format_sgt(event.registration_start_datetime)}."
        )
    if outcome == "closed":
        raise ValidationError(
            f"Registration for this session closed on {_format_sgt(event.registration_end_datetime)}."
        )
    if outcome == "not_open":
        # Authorised as open a moment ago, so it changed in between (e.g. cancelled).
        raise ValidationError("Registration is no longer open for this session.")
    raise NotFoundError("Event not found.")


def withdraw(event_id: str, attendee_id: str) -> dict:
    """Withdraw the attendee's registration (or take them off the waiting
    list). Returns {"withdrawn": True, "promoted": bool} -- promoted is
    whether the freed place went to the next attendee on the waiting list."""
    result = _db_withdraw(event_id, attendee_id) or {}
    outcome = result.get("outcome")
    if outcome == "withdrawn":
        return {"withdrawn": True, "promoted": result.get("promoted_registration_id") is not None}
    if outcome == "started":
        raise ValidationError("This session has already started, so the registration can't be withdrawn.")
    raise NotFoundError("You aren't registered for this session.")


# -- browsing, one session, and "my registrations" ----------------------------


def _counts(event_ids: list[str]) -> dict[str, dict[str, int]]:
    counts = {event_id: {"confirmed": 0, "waitlisted": 0} for event_id in event_ids}
    if not event_ids:
        return counts
    rows = _db_registration_statuses(event_ids)
    for row in rows:
        counts[row["event_id"]][row["status"]] += 1
    return counts


def _with_places(session: dict, counts: dict[str, int]) -> dict:
    capacity = session.get("expected_attendance")
    return {
        **session,
        "capacity": capacity,
        "confirmed_count": counts["confirmed"],
        "waitlist_count": counts["waitlisted"],
        "places_left": None if capacity is None else max(capacity - counts["confirmed"], 0),
    }


def list_open_sessions(today: date | None = None) -> list[dict]:
    """Every upcoming session attendees may know about: confirmed, with
    registration enabled, not yet started. Includes sessions whose window
    hasn't opened yet or has closed, so the page can say so -- the window
    itself is enforced when registering. Public fields only, plus places
    left, soonest first."""
    today = today or datetime.now(SINGAPORE_TZ).date()
    sessions = _db_public_sessions(today.isoformat())
    counts = _counts([session["id"] for session in sessions])
    return [_with_places(session, counts[session["id"]]) for session in sessions]


def get_session(event_id: str, attendee_id: str) -> dict:
    """One session's public fields and places left, plus the caller's own
    registration for it (or None), for the attendee's event page. Authorised
    already (rule_event_view_public): confirmed with registration enabled."""
    sessions = _db_sessions_by_id([event_id])
    if not sessions:
        raise NotFoundError("Event not found.")
    session = _with_places(sessions[0], _counts([event_id])[event_id])
    mine = next((r for r in list_my_registrations(attendee_id) if r["event_id"] == event_id), None)
    if mine:
        mine = {key: value for key, value in mine.items() if key != "session"}
    return {**session, "my_registration": mine}


def list_my_registrations(attendee_id: str) -> list[dict]:
    """The attendee's own registrations, each with its session's public
    fields and, if waitlisted, their place in the queue (1 = next in line)."""
    registrations = _db_my_registrations(attendee_id)
    if not registrations:
        return []
    event_ids = sorted({row["event_id"] for row in registrations})
    sessions = {session["id"]: session for session in _db_sessions_by_id(event_ids)}

    waiting = {}
    for row in _db_waitlists(event_ids):
        waiting.setdefault(row["event_id"], []).append(row)
    for queue in waiting.values():
        queue.sort(key=lambda row: (row["registered_at"], row["id"]))

    result = []
    for row in registrations:
        position = None
        if row["status"] == "waitlisted":
            queue = [entry["id"] for entry in waiting.get(row["event_id"], [])]
            position = queue.index(row["id"]) + 1 if row["id"] in queue else None
        result.append({**row, "session": sessions.get(row["event_id"]), "waitlist_position": position})
    result.sort(key=lambda item: ((item["session"] or {}).get("preferred_start_date") or "9999-12-31"))
    return result


# -- database access (isolated so unit tests don't fake the query builder) --


def _db_register(event_id: str, attendee_id: str, details: dict) -> dict:
    result = supabase.rpc(
        "register_attendee",
        {
            "p_event_id": event_id,
            "p_attendee_id": attendee_id,
            "p_email": details["email"],
            "p_phone": details["phone"],
            "p_organisation": details["organisation"],
            "p_notify_email": details["notify_email"],
            "p_notify_sms": details["notify_sms"],
            "p_notes": details["notes"],
        },
    ).execute()
    return result.data


def _db_withdraw(event_id: str, attendee_id: str) -> dict:
    result = supabase.rpc(
        "withdraw_registration", {"p_event_id": event_id, "p_attendee_id": attendee_id}
    ).execute()
    return result.data


def _db_profile_organisation(attendee_id: str) -> str | None:
    """The profile's organisation, once profiles have one. select("*") so
    this keeps working before and after that column exists."""
    result = supabase.table("profiles").select("*").eq("id", attendee_id).execute()
    rows = result.data or []
    return (rows[0].get("organisation") or None) if rows else None


def _db_public_sessions(from_date: str) -> list[dict]:
    result = (
        supabase.table("events")
        .select(_PUBLIC_FIELDS)
        .eq("status", "confirmed")
        .eq("registration_needs", True)
        .gte("preferred_start_date", from_date)
        .order("preferred_start_date")
        .execute()
    )
    return result.data or []


def _db_sessions_by_id(event_ids: list[str]) -> list[dict]:
    result = supabase.table("events").select(_PUBLIC_FIELDS + ", status").in_("id", event_ids).execute()
    return result.data or []


def _db_registration_statuses(event_ids: list[str]) -> list[dict]:
    result = supabase.table("registrations").select("event_id, status").in_("event_id", event_ids).execute()
    return result.data or []


def _db_my_registrations(attendee_id: str) -> list[dict]:
    result = (
        supabase.table("registrations")
        .select(
            "id, event_id, status, email, phone, organisation, notify_email, notify_sms, notes, registered_at"
        )
        .eq("attendee_id", attendee_id)
        .execute()
    )
    return result.data or []


def _db_waitlists(event_ids: list[str]) -> list[dict]:
    result = (
        supabase.table("registrations")
        .select("id, event_id, registered_at")
        .in_("event_id", event_ids)
        .eq("status", "waitlisted")
        .execute()
    )
    return result.data or []
