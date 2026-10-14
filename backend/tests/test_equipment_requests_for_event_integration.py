"""Live Supabase test for the Equipment Booking section's query
(View Reserved Equipment, Justin, Sprint 3):
app.equipment.equipment_service.list_requests_for_event.

The unit tests in test_equipment_service.py hand the service rows with the
embeds already attached, so they prove the grouping and sorting but not
that PostgREST accepts the nested select (request -> items -> reservations
-> units) against the real foreign keys. This file proves that part:

  - only this event's requests come back, newest first
  - a confirmed request's units come back grouped by type (A-Z), each with
    its asset tag, the quantity being the units actually held
  - a pending request has its items and total but nothing allocated

Every row is created with unique names/tags and removed afterwards;
deleting the event cascades to its requests, items and reservations.
"""

from __future__ import annotations

import uuid

import pytest

from app.equipment.equipment_service import list_requests_for_event
from app.extensions import supabase

pytestmark = pytest.mark.integration

_PASSWORD = "Password123!-throwaway-test-account"
_START = "2031-03-10T10:00:00+08:00"
_END = "2031-03-10T14:00:00+08:00"


@pytest.fixture
def organizer():
    email = f"equip-org-{uuid.uuid4()}@example.com"
    user_id = supabase.auth.admin.create_user({"email": email, "password": _PASSWORD, "email_confirm": True}).user.id
    supabase.table("profiles").insert({"id": user_id, "name": "Equipment Test Organiser", "email": email}).execute()
    yield user_id
    supabase.table("events").delete().eq("organizer_id", user_id).execute()
    supabase.table("profiles").delete().eq("id", user_id).execute()
    supabase.auth.admin.delete_user(user_id)


@pytest.fixture
def inventory():
    """Two throwaway types (named so "mic" sorts before "prj") with units."""
    tag = uuid.uuid4().hex[:8]
    types = {
        key: supabase.table("equipment_types").insert({"name": f"it-{key}-{tag}"}).execute().data[0]
        for key in ("mic", "prj")
    }
    units = {}
    for key, count in (("mic", 2), ("prj", 1)):
        for n in range(1, count + 1):
            asset_tag = f"IT-{key.upper()}-{tag}-{n}"
            units[asset_tag] = (
                supabase.table("equipment_units")
                .insert({"equipment_type_id": types[key]["id"], "asset_tag": asset_tag})
                .execute()
                .data[0]
            )
    yield {"tag": tag, "types": types, "units": units}
    # This fixture tears down BEFORE organizer (reverse setup order), so the
    # events and their requests still exist. Delete the request lines that
    # use these types first (their reservations cascade with them), so
    # nothing references the units or types any more.
    type_ids = [type_["id"] for type_ in types.values()]
    supabase.table("equipment_request_items").delete().in_("equipment_type_id", type_ids).execute()
    for unit in units.values():
        supabase.table("equipment_units").delete().eq("id", unit["id"]).execute()
    for type_ in types.values():
        supabase.table("equipment_types").delete().eq("id", type_["id"]).execute()


def _event(organizer_id, name="Equipment test"):
    return (
        supabase.table("events")
        .insert({"organizer_id": organizer_id, "name": name, "status": "planning"})
        .execute()
        .data[0]
    )


def _request(event_id, requested_by, status, created_at, lines):
    """lines: [(type_row, quantity, [unit rows to reserve])]."""
    request = (
        supabase.table("equipment_requests")
        .insert(
            {
                "event_id": event_id,
                "requested_by": requested_by,
                "status": status,
                "needed_start": _START,
                "needed_end": _END,
                "created_at": created_at,
            }
        )
        .execute()
        .data[0]
    )
    for type_, quantity, reserve in lines:
        item = (
            supabase.table("equipment_request_items")
            .insert({"request_id": request["id"], "equipment_type_id": type_["id"], "quantity": quantity})
            .execute()
            .data[0]
        )
        for unit in reserve:
            reservation = {
                "equipment_id": unit["id"],
                "request_item_id": item["id"],
                "reserved_start": _START,
                "reserved_end": _END,
            }
            supabase.table("equipment_reservations").insert(reservation).execute()
    return request


def test_confirmed_request_lists_reserved_units_by_type_from_the_real_database(organizer, inventory):
    types, units, tag = inventory["types"], inventory["units"], inventory["tag"]
    event = _event(organizer)
    other_event = _event(organizer, name="Another event")
    pending = _request(
        event["id"], organizer, "pending", "2031-01-02T00:00:00Z", [(types["prj"], 2, [])]
    )
    confirmed = _request(
        event["id"],
        organizer,
        "confirmed",
        "2031-01-01T00:00:00Z",
        [
            # Reserved in reverse tag order, to show the sort is the service's.
            (types["mic"], 2, [units[f"IT-MIC-{tag}-2"], units[f"IT-MIC-{tag}-1"]]),
            (types["prj"], 1, [units[f"IT-PRJ-{tag}-1"]]),
        ],
    )
    _request(other_event["id"], organizer, "pending", "2031-01-03T00:00:00Z", [(types["mic"], 1, [])])

    requests = list_requests_for_event(event["id"])

    assert [r["id"] for r in requests] == [pending["id"], confirmed["id"]]

    assert requests[0]["total_quantity"] == 2
    assert requests[0]["allocated"] == []

    got = requests[1]
    assert got["total_quantity"] == 3
    assert sorted((i["type"], i["quantity"]) for i in got["items"]) == [
        (types["mic"]["name"], 2),
        (types["prj"]["name"], 1),
    ]
    assert [(g["type"], g["quantity"]) for g in got["allocated"]] == [
        (types["mic"]["name"], 2),
        (types["prj"]["name"], 1),
    ]
    assert [u["asset_tag"] for u in got["allocated"][0]["units"]] == [f"IT-MIC-{tag}-1", f"IT-MIC-{tag}-2"]
    assert got["allocated"][0]["units"][0]["id"] == units[f"IT-MIC-{tag}-1"]["id"]
    assert [u["asset_tag"] for u in got["allocated"][1]["units"]] == [f"IT-PRJ-{tag}-1"]


def test_event_with_no_equipment_requests_returns_an_empty_list(organizer):
    event = _event(organizer)

    assert list_requests_for_event(event["id"]) == []
