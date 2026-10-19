"""What a change to a session would disturb, before it is committed.

Used for an IS-21 change request (before the coordinator approves it) and
for the coordinator's own IS-9 update (app.events.event_update): before a
change is committed, the coordinator is shown which arrangements already
made for the session it touches, so a significant change is never made
blind. Each impact is one dict:

    {"area": "venue" | "registration" | "equipment" | "technical_support",
     "severity": "conflict" | "check",
     "title": str, "issues": [str, ...], ...area-specific keys}

  conflict -- checked against real records (venue_bookings + venues,
              registrations, equipment_requests): the change contradicts
              something that exists.
  check    -- nothing can be checked: there are no technical-support
              assignment records at all, and a session that needs equipment
              may have none requested through the system yet. Raised
              whenever the change touches what those arrangements depend
              on, once the event is past approval (when arrangements start
              being made), so the coordinator confirms by hand.

Nothing here writes. In particular a timing change does NOT move a venue
booking or an equipment request: booking_start/end and needed_start/end are
deliberately snapshotted (see 20261005100000_venue_bookings.sql and
20261008000000_equipment.sql), so the coordinator is told instead. Each
booking is assessed on its own, and none is ever removed.

check_acknowledged is the gate: the commit must name every affected area.

touched_arrangements answers the wider IS-9 question -- "which
already-made arrangements does this change touch (venue, equipment,
registration)?" -- whether or not anything conflicts: every active venue
booking, equipment request and the session's registrations that depend on
a field the change alters, so the coordinator sees them all before a
significant change is committed.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from app.events.event_service import SINGAPORE_TZ, _from_database_event
from app.extensions import supabase
from app.shared.errors import AppError, ValidationError
from app.venues.booking_service import _event_window, _parse_timestamptz

TIMING_FIELDS = frozenset({"preferred_start_date", "preferred_end_date", "preferred_start_time", "preferred_end_time"})
REGISTRATION_WINDOW_FIELDS = frozenset({"registration_start_datetime", "registration_end_datetime"})
# Statuses in which arrangements (venue, equipment, support) may already be
# in place: from approval on. Venue bookings can only exist from here anyway
# (rule_venue_booking_create).
# safety_review (Week 7 change #6) sits between planning and confirmed, with
# the arrangements already in place.
ARRANGED_STATUSES = frozenset({"approved", "planning", "safety_review", "confirmed"})
_ACTIVE_BOOKING_STATUSES = ("pending", "confirmed")

# The session details each kind of arrangement depends on: a change to one
# of these "touches" that arrangement (touched_arrangements).
VENUE_DEPENDENT_FIELDS = TIMING_FIELDS | {"expected_attendance", "room_layout", "accessibility_needs"}
EQUIPMENT_DEPENDENT_FIELDS = TIMING_FIELDS | {"equipment"}
REGISTRATION_DEPENDENT_FIELDS = (
    TIMING_FIELDS | REGISTRATION_WINDOW_FIELDS | {"expected_attendance", "registration_needs"}
)
_ACTIVE_EQUIPMENT_REQUEST_STATUSES = ("pending", "confirmed")


class ChangeImpactNotAcknowledgedError(AppError):
    """Committing would disturb arrangements already made for the session
    that the coordinator hasn't acknowledged -- including one that appeared
    after they loaded the page."""

    status_code = 409
    code = "change_impact_unacknowledged"

_ITEM_LABELS = {
    "microphone": "microphones",
    "projector": "projectors",
    "screen": "screens",
    "wifi": "WiFi",
    "wheelchair_access": "wheelchair access",
    "lift_access": "lift access",
    "removable_seats": "removable seats",
    "extra_legroom_seats": "seats with extra legroom",
}


def _when(value: datetime) -> str:
    return value.astimezone(SINGAPORE_TZ).strftime("%d %b %Y %H:%M")


def _items(entries) -> list[str]:
    return [entry.get("item") for entry in entries or [] if isinstance(entry, dict)]


def _labels(items) -> str:
    return ", ".join(_ITEM_LABELS.get(item, item) for item in items)


def _venue_impacts(event: SimpleNamespace, after: dict, changed: set[str]) -> list[dict]:
    result = (
        supabase.table("venue_bookings")
        .select("*, venues(name, capacity, supported_layouts, accessibility_features)")
        .eq("event_id", event.id)
        .in_("status", _ACTIVE_BOOKING_STATUSES)
        .execute()
    )
    impacts = []
    for booking in result.data or []:
        venue = booking.get("venues") or {}
        issues = []

        if changed & TIMING_FIELDS and after.get("preferred_start_date"):
            start, end = _event_window(SimpleNamespace(**after))
            needed_start = start - timedelta(minutes=booking.get("setup_minutes") or 0)
            needed_end = end + timedelta(minutes=booking.get("turnaround_minutes") or 0)
            booked_start = _parse_timestamptz(booking["booking_start"])
            booked_end = _parse_timestamptz(booking["booking_end"])
            if needed_start < booked_start or needed_end > booked_end:
                issues.append(
                    f"The booking holds the venue {_when(booked_start)} to {_when(booked_end)}; the new timing "
                    f"needs {_when(needed_start)} to {_when(needed_end)} (including setup and turnaround). "
                    "The booking will not move automatically."
                )

        capacity = venue.get("capacity")
        if "expected_attendance" in changed and capacity and (after.get("expected_attendance") or 0) > capacity:
            issues.append(
                f"{after['expected_attendance']} expected attendees exceeds the venue's capacity of {capacity}."
            )

        layouts = venue.get("supported_layouts")
        if "room_layout" in changed and layouts is not None and after.get("room_layout") not in layouts:
            issues.append(f"The venue doesn't support a {after.get('room_layout')} layout.")

        if "accessibility_needs" in changed and venue.get("accessibility_features") is not None:
            missing = [i for i in _items(after.get("accessibility_needs")) if i not in venue["accessibility_features"]]
            if missing:
                issues.append(f"The venue doesn't provide: {_labels(missing)}.")

        if issues:
            impacts.append(
                {
                    "area": "venue",
                    "severity": "conflict",
                    "title": f"Venue booking: {venue.get('name') or 'venue'} ({booking['status']})",
                    "booking_id": booking["id"],
                    "issues": issues,
                }
            )
    return impacts


def _registration_impacts(after: dict, before: dict, changed: set[str], event_id: str) -> list[dict]:
    rows = supabase.table("registrations").select("status").eq("event_id", event_id).execute().data or []
    if not rows:
        return []
    confirmed = sum(1 for row in rows if row.get("status") == "confirmed")
    waitlisted = len(rows) - confirmed
    who = f"{confirmed} confirmed" + (f" and {waitlisted} waitlisted" if waitlisted else "") + " attendee(s)"

    issues = []
    if changed & TIMING_FIELDS:
        issues.append(f"{who} registered for the current date and time.")
    if "expected_attendance" in changed and (after.get("expected_attendance") or 0) < confirmed:
        issues.append(
            f"{confirmed} confirmed registrations exceed the new expected attendance of "
            f"{after['expected_attendance']}; they stay confirmed."
        )
    if "registration_needs" in changed and after.get("registration_needs") is False:
        issues.append(f"Registration would be turned off, but {who} are already registered.")
    elif changed & REGISTRATION_WINDOW_FIELDS and before.get("registration_needs"):
        issues.append(f"The registration period changes while {who} are registered.")
    if not issues:
        return []
    return [
        {
            "area": "registration",
            "severity": "conflict",
            "title": "Attendee registrations",
            "confirmed": confirmed,
            "waitlisted": waitlisted,
            "issues": issues,
        }
    ]


def _requests_phrase(status: str, count: int) -> tuple[str, tuple[str, str], str]:
    """("The pending equipment request", ("covers", "was"), "It") for one
    request; the plural forms for several."""
    if count == 1:
        return f"The {status} equipment request", ("covers", "was"), "It"
    return f"The {count} {status} equipment requests", ("cover", "were"), "They"


def _equipment_impacts(event: SimpleNamespace, after: dict, before: dict, changed: set[str]) -> list[dict]:
    """Checked against the session's equipment requests when it has any;
    otherwise a manual check, as long as the session needs equipment."""
    if not changed & (TIMING_FIELDS | {"equipment"}):
        return []
    requests = (
        supabase.table("equipment_requests")
        .select("id, status, needed_start, needed_end")
        .eq("event_id", event.id)
        .in_("status", _ACTIVE_EQUIPMENT_REQUEST_STATUSES)
        .execute()
        .data
        or []
    )
    if not requests:
        if not (_items(after.get("equipment")) or _items(before.get("equipment"))):
            return []
        what = "the new equipment list" if "equipment" in changed else "the new date/time"
        return [
            {
                "area": "equipment",
                "severity": "check",
                "title": "Equipment",
                "issues": [
                    "No equipment request has been made through the system for this session yet. Confirm that "
                    f"{_labels(_items(after.get('equipment'))) or 'no equipment'} can be provided for {what}."
                ],
            }
        ]

    # Requests with the same status (and, for timing, the same window) would
    # each produce the same sentence, so they're grouped: one issue per
    # group, saying how many requests it covers.
    issues = []
    if changed & TIMING_FIELDS and after.get("preferred_start_date"):
        start, end = _event_window(SimpleNamespace(**after))
        windows: dict[tuple, int] = {}
        for equipment_request in requests:
            needed_start = _parse_timestamptz(equipment_request["needed_start"])
            needed_end = _parse_timestamptz(equipment_request["needed_end"])
            if start < needed_start or end > needed_end:
                key = (equipment_request["status"], needed_start, needed_end)
                windows[key] = windows.get(key, 0) + 1
        for (status, needed_start, needed_end), count in windows.items():
            subject, verb, pronoun = _requests_phrase(status, count)
            issues.append(
                f"{subject} {verb[0]} {_when(needed_start)} to {_when(needed_end)}; the new timing is "
                f"{_when(start)} to {_when(end)}. {pronoun} will not move automatically."
            )
    if "equipment" in changed:
        statuses: dict[str, int] = {}
        for equipment_request in requests:
            statuses[equipment_request["status"]] = statuses.get(equipment_request["status"], 0) + 1
        for status, count in statuses.items():
            subject, verb, _ = _requests_phrase(status, count)
            issues.append(
                f"{subject} {verb[1]} made for the previous equipment list; the new list is "
                f"{_labels(_items(after.get('equipment'))) or 'no equipment'}."
            )
    if not issues:
        return []
    return [{"area": "equipment", "severity": "conflict", "title": "Equipment requests", "issues": issues}]


def _technical_support_impacts(after: dict, before: dict, changed: set[str]) -> list[dict]:
    equipment = _items(after.get("equipment")) or _items(before.get("equipment"))
    if not (equipment and changed & (TIMING_FIELDS | {"equipment", "room_layout"})):
        return []
    return [
        {
            "area": "technical_support",
            "severity": "check",
            "title": "Technical support",
            "issues": [
                "Technical support assignments aren't recorded in the system yet. Let the Technical Support "
                "Staff know about the change to " + _labels_of_changes(changed) + "."
            ],
        }
    ]


def _labels_of_changes(changed: set[str]) -> str:
    parts = []
    if changed & TIMING_FIELDS:
        parts.append("the timing")
    if "equipment" in changed:
        parts.append("the equipment")
    if "room_layout" in changed:
        parts.append("the room layout")
    return " and ".join(parts)


def assess_change_impact(event: SimpleNamespace, requested_changes: dict) -> list[dict]:
    """Every arrangement for this session that `requested_changes` (field ->
    new value) would disturb. Empty when nothing already arranged is
    affected (e.g. a name change, or any change before the event is
    approved)."""
    if event.status not in ARRANGED_STATUSES:
        return []
    changed = set(requested_changes)
    before = _from_database_event(event)
    after = {**before, **requested_changes}
    return [
        *_venue_impacts(event, after, changed),
        *_registration_impacts(after, before, changed, event.id),
        *_equipment_impacts(event, after, before, changed),
        *_technical_support_impacts(after, before, changed),
    ]


def check_acknowledged(impacts: list[dict], acknowledged) -> None:
    """Every impacted area must be acknowledged by name -- a plain "yes"
    would also wave through an impact that appeared after the coordinator
    loaded the page (a new registration, a booking just confirmed)."""
    if acknowledged is not None and (
        not isinstance(acknowledged, list) or not all(isinstance(area, str) for area in acknowledged)
    ):
        raise ValidationError("acknowledge_impacts must be a list of impact areas.")
    unacknowledged = sorted({impact["area"] for impact in impacts} - set(acknowledged or []))
    if unacknowledged:
        raise ChangeImpactNotAcknowledgedError(
            "This change affects arrangements already made for the event ("
            + ", ".join(area.replace("_", " ") for area in unacknowledged)
            + "). Review them and acknowledge before saving."
        )


def touched_arrangements(event: SimpleNamespace, requested_changes: dict) -> list[dict]:
    """Every arrangement already made for this session that
    `requested_changes` touches, conflict or not -- one dict each:

        {"area": "venue" | "equipment" | "registration",
         "id": str | None,      # the booking / equipment request; None for registrations
         "title": str,
         "status": str | None,  # the booking's / request's own status
         "fields": [...]}       # the changed fields it depends on

    Empty before arrangements can exist (ARRANGED_STATUSES) or when the
    change alters nothing an arrangement depends on (e.g. a name change).
    Read-only, like assess_change_impact; whether a touched arrangement
    actually conflicts is assess_change_impact's answer."""
    if event.status not in ARRANGED_STATUSES:
        return []
    changed = set(requested_changes)
    touched = []

    venue_fields = sorted(changed & VENUE_DEPENDENT_FIELDS)
    if venue_fields:
        bookings = (
            supabase.table("venue_bookings")
            .select("id, status, venues(name)")
            .eq("event_id", event.id)
            .in_("status", _ACTIVE_BOOKING_STATUSES)
            .execute()
            .data
            or []
        )
        touched += [
            {
                "area": "venue",
                "id": booking["id"],
                "title": f"Venue booking: {(booking.get('venues') or {}).get('name') or 'venue'}",
                "status": booking["status"],
                "fields": venue_fields,
            }
            for booking in bookings
        ]

    equipment_fields = sorted(changed & EQUIPMENT_DEPENDENT_FIELDS)
    if equipment_fields:
        requests = (
            supabase.table("equipment_requests")
            .select("id, status")
            .eq("event_id", event.id)
            .in_("status", _ACTIVE_EQUIPMENT_REQUEST_STATUSES)
            .execute()
            .data
            or []
        )
        touched += [
            {
                "area": "equipment",
                "id": equipment_request["id"],
                "title": "Equipment request",
                "status": equipment_request["status"],
                "fields": equipment_fields,
            }
            for equipment_request in requests
        ]

    registration_fields = sorted(changed & REGISTRATION_DEPENDENT_FIELDS)
    if registration_fields:
        rows = supabase.table("registrations").select("status").eq("event_id", event.id).execute().data or []
        if rows:
            confirmed = sum(1 for row in rows if row.get("status") == "confirmed")
            waitlisted = len(rows) - confirmed
            touched.append(
                {
                    "area": "registration",
                    "id": None,
                    "title": f"Attendee registrations ({confirmed} confirmed"
                    + (f", {waitlisted} waitlisted" if waitlisted else "")
                    + ")",
                    "status": None,
                    "fields": registration_fields,
                }
            )
    return touched
