"""What an IS-21 change request would disturb, if approved.

Before the assigned coordinator commits a change, they're shown which
arrangements already made for the session it touches, so a significant
change is never approved blind. Each impact is one dict:

    {"area": "venue" | "registration" | "equipment" | "technical_support",
     "severity": "conflict" | "check",
     "title": str, "issues": [str, ...], ...area-specific keys}

  conflict -- checked against real records (venue_bookings + venues,
              registrations): the change contradicts something that exists.
  check    -- the area has no records in the system yet (no equipment
              allocation or technical-support assignment tables exist), so
              nothing can be checked. Raised whenever the change touches what
              those arrangements depend on, once the event is past approval
              (when arrangements start being made), so the coordinator
              confirms with the people involved by hand.

Nothing here writes. In particular an approved timing change does NOT move
a venue booking: booking_start/end are deliberately snapshotted (see
20261005100000_venue_bookings.sql), so the coordinator is told instead.
"""

#

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from app.events.event_service import SINGAPORE_TZ, _from_database_event
from app.extensions import supabase
from app.venues.booking_service import _event_window, _parse_timestamptz

TIMING_FIELDS = frozenset({"preferred_start_date", "preferred_end_date", "preferred_start_time", "preferred_end_time"})
REGISTRATION_WINDOW_FIELDS = frozenset({"registration_start_datetime", "registration_end_datetime"})
# Statuses in which arrangements (venue, equipment, support) may already be
# in place: from approval on. Venue bookings can only exist from here anyway
# (rule_venue_booking_create).
ARRANGED_STATUSES = frozenset({"approved", "planning", "confirmed"})
_ACTIVE_BOOKING_STATUSES = ("pending", "confirmed")

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


def _untracked_impacts(after: dict, before: dict, changed: set[str]) -> list[dict]:
    impacts = []
    equipment = _items(after.get("equipment")) or _items(before.get("equipment"))
    if equipment and changed & (TIMING_FIELDS | {"equipment"}):
        what = "the new equipment list" if "equipment" in changed else "the new date/time"
        impacts.append(
            {
                "area": "equipment",
                "severity": "check",
                "title": "Equipment",
                "issues": [
                    f"Equipment allocations aren't recorded in the system yet. Confirm that "
                    f"{_labels(_items(after.get('equipment'))) or 'no equipment'} can be provided for {what}."
                ],
            }
        )
    if equipment and changed & (TIMING_FIELDS | {"equipment", "room_layout"}):
        impacts.append(
            {
                "area": "technical_support",
                "severity": "check",
                "title": "Technical support",
                "issues": [
                    "Technical support assignments aren't recorded in the system yet. Let the Technical Support "
                    "Staff know about the change to " + _labels_of_changes(changed) + "."
                ],
            }
        )
    return impacts


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
    """Every arrangement for this session that `requested_changes` would
    disturb. Empty when nothing already arranged is affected (e.g. a name
    change, or any change before the event is approved)."""
    if event.status not in ARRANGED_STATUSES:
        return []
    changed = set(requested_changes)
    before = _from_database_event(event)
    after = {**before, **requested_changes}
    return [
        *_venue_impacts(event, after, changed),
        *_registration_impacts(after, before, changed, event.id),
        *_untracked_impacts(after, before, changed),
    ]
