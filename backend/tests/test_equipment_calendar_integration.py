"""Live Supabase test for the equipment calendar's data (IS-47).

test_equipment_calendar_service.py hands the service units with the event
name already attached. This proves the part those can't: that
equipment_service.get_equipment's nested select (reservation -> request
item -> request -> event) really returns the event's name from Postgres,
and that the calendar built on it filters by range.

Every row is created with unique names/tags and removed afterwards;
deleting the event cascades to its requests, items and reservations.
"""

from __future__ import annotations

import uuid

import pytest

from app.equipment.calendar_service import get_equipment_calendar
from app.equipment.equipment_service import get_equipment
from app.extensions import supabase

pytestmark = pytest.mark.integration

_PASSWORD = "Password123!-throwaway-test-account"


@pytest.fixture
def organizer():
    email = f"equip-cal-{uuid.uuid4()}@example.com"
    user_id = supabase.auth.admin.create_user({"email": email, "password": _PASSWORD, "email_confirm": True}).user.id
    supabase.table("profiles").insert({"id": user_id, "name": "Equipment Calendar Test", "email": email}).execute()
    yield user_id
    supabase.table("events").delete().eq("organizer_id", user_id).execute()
    supabase.table("profiles").delete().eq("id", user_id).execute()
    supabase.auth.admin.delete_user(user_id)


@pytest.fixture
def unit():
    tag = uuid.uuid4().hex[:8]
    type_ = supabase.table("equipment_types").insert({"name": f"cal-type-{tag}"}).execute().data[0]
    row = (
        supabase.table("equipment_units")
        .insert({"equipment_type_id": type_["id"], "asset_tag": f"CAL-{tag}"})
        .execute()
        .data[0]
    )
    yield row
    # Tears down before `organizer`: remove the request lines on this type
    # (their reservations cascade) so nothing references the unit or type.
    supabase.table("equipment_request_items").delete().eq("equipment_type_id", type_["id"]).execute()
    supabase.table("equipment_units").delete().eq("id", row["id"]).execute()
    supabase.table("equipment_types").delete().eq("id", type_["id"]).execute()


def _reserve(organizer_id, unit_row, event_name, start, end):
    event = (
        supabase.table("events")
        .insert({"organizer_id": organizer_id, "name": event_name, "status": "planning"})
        .execute()
        .data[0]
    )
    request = (
        supabase.table("equipment_requests")
        .insert(
            {
                "event_id": event["id"],
                "requested_by": organizer_id,
                "status": "confirmed",
                "needed_start": start,
                "needed_end": end,
            }
        )
        .execute()
        .data[0]
    )
    item = (
        supabase.table("equipment_request_items")
        .insert({"request_id": request["id"], "equipment_type_id": unit_row["equipment_type_id"], "quantity": 1})
        .execute()
        .data[0]
    )
    supabase.table("equipment_reservations").insert(
        {"equipment_id": unit_row["id"], "request_item_id": item["id"], "reserved_start": start, "reserved_end": end}
    ).execute()
    return event


def test_calendar_entries_name_the_event_through_the_real_join(organizer, unit):
    inside = _reserve(organizer, unit, "Calendar Gala", "2031-03-10T10:00:00+00:00", "2031-03-12T04:00:00+00:00")
    _reserve(organizer, unit, "Calendar April Event", "2031-04-10T10:00:00+00:00", "2031-04-10T12:00:00+00:00")

    result = get_equipment_calendar(get_equipment(unit["id"]), "2031-03-01", "2031-03-31")

    assert result["equipment"]["asset_tag"] == unit["asset_tag"]
    assert [(entry["event_id"], entry["event_name"]) for entry in result["entries"]] == [
        (inside["id"], "Calendar Gala")
    ]
    entry = result["entries"][0]
    assert entry["state"] == "reserved"
    # PostgREST returns timestamptz normalised to UTC; the period is intact.
    assert entry["start"].startswith("2031-03-10T10:00:00")
    assert entry["end"].startswith("2031-03-12T04:00:00")
