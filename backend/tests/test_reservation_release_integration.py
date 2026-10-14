"""Live Supabase test for Release Equipment on Cancel (Justin, Sprint 3):
cancelling an event (transition() + release_event_equipment, what the
cancel route does) frees its reserved units, so

  - another event's availability check for the same date and time goes
    back up (IS-18's check_availability counts reservation rows), and
  - the unit can be reserved again (the exclusion constraint no longer
    blocks it), while
  - other events' reservations are untouched.

Every row is created with unique names/tags and removed afterwards.
"""

from __future__ import annotations

import uuid

import pytest

from app.equipment.equipment_service import check_availability
from app.equipment.reservation_release import release_event_equipment
from app.events.transitions import transition
from app.extensions import supabase

pytestmark = pytest.mark.integration

_PASSWORD = "Password123!-throwaway-test-account"
_START = "2031-04-10T10:00:00+08:00"
_END = "2031-04-10T14:00:00+08:00"


@pytest.fixture
def organizer():
    email = f"release-org-{uuid.uuid4()}@example.com"
    user_id = supabase.auth.admin.create_user({"email": email, "password": _PASSWORD, "email_confirm": True}).user.id
    supabase.table("profiles").insert({"id": user_id, "name": "Release Test Organiser", "email": email}).execute()
    yield user_id
    supabase.table("event_status_log").delete().eq("changed_by", user_id).execute()
    supabase.table("events").delete().eq("organizer_id", user_id).execute()
    supabase.table("profiles").delete().eq("id", user_id).execute()
    supabase.auth.admin.delete_user(user_id)


@pytest.fixture
def projectors():
    """One throwaway type with two units."""
    tag = uuid.uuid4().hex[:8]
    type_ = supabase.table("equipment_types").insert({"name": f"it-release-prj-{tag}"}).execute().data[0]
    units = [
        supabase.table("equipment_units")
        .insert({"equipment_type_id": type_["id"], "asset_tag": f"IT-REL-{tag}-{n}"})
        .execute()
        .data[0]
        for n in (1, 2)
    ]
    yield type_, units
    # Tears down before organizer: clear the request lines using this type
    # first (their reservations cascade), then the units and the type.
    supabase.table("equipment_request_items").delete().eq("equipment_type_id", type_["id"]).execute()
    for unit in units:
        supabase.table("equipment_units").delete().eq("id", unit["id"]).execute()
    supabase.table("equipment_types").delete().eq("id", type_["id"]).execute()


def _event(organizer_id, name):
    return (
        supabase.table("events")
        .insert({"organizer_id": organizer_id, "name": name, "status": "planning"})
        .execute()
        .data[0]
    )


def _request(event_id, requested_by, status, type_, quantity, reserve=()):
    request = (
        supabase.table("equipment_requests")
        .insert(
            {
                "event_id": event_id,
                "requested_by": requested_by,
                "status": status,
                "needed_start": _START,
                "needed_end": _END,
            }
        )
        .execute()
        .data[0]
    )
    item = (
        supabase.table("equipment_request_items")
        .insert({"request_id": request["id"], "equipment_type_id": type_["id"], "quantity": quantity})
        .execute()
        .data[0]
    )
    for unit in reserve:
        _reserve(unit, item)
    return request, item


def _reserve(unit, item):
    reservation = {
        "equipment_id": unit["id"],
        "request_item_id": item["id"],
        "reserved_start": _START,
        "reserved_end": _END,
    }
    return supabase.table("equipment_reservations").insert(reservation).execute().data[0]


def _available(request_id):
    return check_availability(request_id)["items"][0]["available"]


def test_cancelling_an_event_gives_its_units_back_for_that_date_and_time(organizer, projectors):
    type_, (unit_1, unit_2) = projectors
    cancelled = _event(organizer, "Release test: to be cancelled")
    other = _event(organizer, "Release test: keeps its booking")
    waiting = _event(organizer, "Release test: wants a projector")

    _request(cancelled["id"], organizer, "confirmed", type_, 1, reserve=[unit_1])
    _, other_item = _request(other["id"], organizer, "confirmed", type_, 1, reserve=[unit_2])
    pending, pending_item = _request(waiting["id"], organizer, "pending", type_, 1)

    assert _available(pending["id"]) == 0  # both projectors held at that time

    transition(cancelled["id"], "cancelled", organizer, reason="Venue unavailable", expected_from="planning")
    assert release_event_equipment(cancelled["id"]) == 1

    # Available quantity recalculated for that date and time.
    assert _available(pending["id"]) == 1
    # The unit can actually be reserved again (exclusion constraint no longer blocks it).
    _reserve(unit_1, pending_item)
    # The other event's reservation is untouched.
    held = supabase.table("equipment_reservations").select("id").eq("request_item_id", other_item["id"]).execute()
    assert len(held.data) == 1


def test_releasing_an_event_with_no_equipment_is_harmless(organizer):
    event = _event(organizer, "Release test: no equipment")

    assert release_event_equipment(event["id"]) == 0
