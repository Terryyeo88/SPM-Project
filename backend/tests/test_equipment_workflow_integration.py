"""Live Supabase tests for the equipment request workflow (Nawaz, Sprint 3-4:
IS-17 record a request, IS-19 accept and reserve, IS-41 reject with a
reason, IS-43 change a quantity, IS-66 withdraw a booking).

The unit tests for these hand the services a fake database, so they prove
the logic but not that the real database agrees. This file proves the parts
only a real database can:

  - IS-17  the session's window is stored as the right instants, and a
           request whose lines cannot be saved leaves nothing behind
  - IS-19  accepting writes one reservation per unit and confirms the
           request; the exclusion constraint refuses a double booking and
           accepts back-to-back periods ([) is half-open)
  - IS-41  the rejection reason is stored, and the CHECK keeps reason and
           status in step; a rejection cannot overwrite an accepted request
  - IS-43  a change request is applied (units added or released, quantity
           updated); only one pending change per item (partial unique
           index); a change the stock cannot cover changes nothing
  - IS-66  `cancelled` is a real status value, and cancelling frees the
           units for another request; a waiting change is rejected with it

Needs migrations 20261019100000 (rejection), 20261019200000 (change
requests) and 20261102000000 (cancelled) applied -- `npx supabase db reset`
applies them all on a local stack.

Every row is created with unique names/tags and removed afterwards; deleting
the events cascades to their requests, items, reservations and change
requests. Run with `pytest -m integration` against a LOCAL Supabase only
(see tests/conftest.py: other targets are refused).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from postgrest.exceptions import APIError

from app.equipment.change_service import (
    accept_change,
    create_change_request,
    list_changes_for_request,
    reject_change,
)
from app.equipment.equipment_service import (
    accept_request,
    cancel_request,
    check_availability,
    create_request,
    get_request,
    reject_request,
)
from app.extensions import supabase
from app.shared.errors import ValidationError

pytestmark = pytest.mark.integration

_PASSWORD = "Password123!-throwaway-test-account"
_SGT = timezone(timedelta(hours=8))
# The session (and so every request) runs 10:00-14:00 on this date, Singapore time.
_DATE = "2031-03-10"
_START = f"{_DATE}T10:00:00+08:00"
_END = f"{_DATE}T14:00:00+08:00"


def _instant(value: str) -> datetime:
    """PostgREST returns timestamptz normalised to UTC; compare as instants."""
    return datetime.fromisoformat(value)


# -- fixtures -----------------------------------------------------------------


def _make_user(label: str) -> str:
    email = f"equip-{label}-{uuid.uuid4()}@example.com"
    user_id = supabase.auth.admin.create_user({"email": email, "password": _PASSWORD, "email_confirm": True}).user.id
    supabase.table("profiles").insert({"id": user_id, "name": f"Equipment Test {label}", "email": email}).execute()
    return user_id


@pytest.fixture
def world():
    """An organiser, a coordinator and a technical-support user, plus
    throwaway stock: 3 projectors and 2 microphones, in types of their own so
    no other data can affect the availability arithmetic.

    Teardown order matters: events first (their requests, items,
    reservations and change requests cascade), then the lines that use the
    types, then units and types, then the people the rows pointed at."""
    tag = uuid.uuid4().hex[:8]
    organizer, coordinator, tech = _make_user("org"), _make_user("coord"), _make_user("tech")
    types = {
        key: supabase.table("equipment_types").insert({"name": f"it-{key}-{tag}"}).execute().data[0]
        for key in ("prj", "mic")
    }
    units: dict[str, dict] = {}
    for key, count in (("prj", 3), ("mic", 2)):
        for n in range(1, count + 1):
            asset_tag = f"IT-{key.upper()}-{tag}-{n}"
            units[asset_tag] = (
                supabase.table("equipment_units")
                .insert({"equipment_type_id": types[key]["id"], "asset_tag": asset_tag})
                .execute()
                .data[0]
            )
    yield SimpleNamespace(
        tag=tag, organizer=organizer, coordinator=coordinator, tech=tech, types=types, units=units
    )

    supabase.table("events").delete().eq("organizer_id", organizer).execute()
    type_ids = [type_["id"] for type_ in types.values()]
    supabase.table("equipment_request_items").delete().in_("equipment_type_id", type_ids).execute()
    for unit in units.values():
        supabase.table("equipment_units").delete().eq("id", unit["id"]).execute()
    for type_ in types.values():
        supabase.table("equipment_types").delete().eq("id", type_["id"]).execute()
    for user_id in (organizer, coordinator, tech):
        supabase.table("profiles").delete().eq("id", user_id).execute()
        supabase.auth.admin.delete_user(user_id)


def _prj(world, n: int) -> dict:
    return world.units[f"IT-PRJ-{world.tag}-{n}"]


def _event(world, name="Equipment workflow test") -> SimpleNamespace:
    """A planning session on _DATE, 10:00-14:00 -- as the namespace the
    services take (they read preferred_* for the session's window)."""
    row = (
        supabase.table("events")
        .insert(
            {
                "organizer_id": world.organizer,
                "name": name,
                "status": "planning",
                "preferred_start_date": _DATE,
                "preferred_start_time": "10:00",
                "preferred_end_time": "14:00",
            }
        )
        .execute()
        .data[0]
    )
    return SimpleNamespace(**row)


def _lines(world, **quantities):
    """create_request lines: _lines(world, prj=2, mic=1)."""
    return [{"equipment_type_id": world.types[key]["id"], "quantity": qty} for key, qty in quantities.items()]


def _db_request(world, event, status, lines):
    """A request written straight to the tables (no service), for holding
    stock or setting up a starting state. lines: [(type key, quantity,
    [unit rows to reserve])]. Returns (request row, [item rows])."""
    request = (
        supabase.table("equipment_requests")
        .insert(
            {
                "event_id": event.id,
                "requested_by": world.coordinator,
                "status": status,
                "needed_start": _START,
                "needed_end": _END,
            }
        )
        .execute()
        .data[0]
    )
    items = []
    for key, quantity, reserve in lines:
        item = (
            supabase.table("equipment_request_items")
            .insert({"request_id": request["id"], "equipment_type_id": world.types[key]["id"], "quantity": quantity})
            .execute()
            .data[0]
        )
        items.append(item)
        for unit in reserve:
            _reserve(item["id"], unit["id"])
    return request, items


def _reserve(item_id, unit_id, start=_START, end=_END):
    return (
        supabase.table("equipment_reservations")
        .insert({"equipment_id": unit_id, "request_item_id": item_id, "reserved_start": start, "reserved_end": end})
        .execute()
        .data[0]
    )


def _reserved_tags(world, item_id) -> list[str]:
    rows = (
        supabase.table("equipment_reservations")
        .select("equipment_units(asset_tag)")
        .eq("request_item_id", item_id)
        .execute()
        .data
    )
    return sorted(row["equipment_units"]["asset_tag"] for row in rows)


def _confirmed(world, event, **quantities):
    """A request made and accepted through the real services."""
    request = create_request(event, _lines(world, **quantities), world.coordinator)
    accept_request(request["id"])
    return get_request(request["id"])


# -- IS-17: record a request ----------------------------------------------------


def test_a_request_stores_its_lines_and_the_sessions_window_as_the_right_instants(world):
    event = _event(world)

    request = create_request(event, _lines(world, prj=2, mic=1), world.coordinator)

    assert request["status"] == "pending"
    assert request["event_status"] == "planning"
    assert _instant(request["needed_start"]) == datetime(2031, 3, 10, 10, 0, tzinfo=_SGT)
    assert _instant(request["needed_end"]) == datetime(2031, 3, 10, 14, 0, tzinfo=_SGT)
    assert sorted((item["type"], item["quantity"]) for item in request["items"]) == [
        (world.types["mic"]["name"], 1),
        (world.types["prj"]["name"], 2),
    ]


def test_a_request_naming_an_unknown_type_leaves_no_request_behind(world):
    event = _event(world)
    lines = [{"equipment_type_id": str(uuid.uuid4()), "quantity": 1}]

    with pytest.raises(ValidationError):
        create_request(event, lines, world.coordinator)

    left = supabase.table("equipment_requests").select("id").eq("event_id", event.id).execute().data
    assert left == []


def test_the_database_refuses_a_zero_quantity_line(world):
    event = _event(world)
    request, _ = _db_request(world, event, "pending", [])

    with pytest.raises(APIError) as error:
        supabase.table("equipment_request_items").insert(
            {"request_id": request["id"], "equipment_type_id": world.types["prj"]["id"], "quantity": 0}
        ).execute()

    assert error.value.code == "23514"  # check_violation


# -- IS-19: accept and reserve ----------------------------------------------------


def test_accepting_reserves_the_lowest_asset_tags_and_confirms_the_request(world):
    event = _event(world)
    request = create_request(event, _lines(world, prj=2), world.coordinator)

    accepted = accept_request(request["id"])

    assert accepted["status"] == "confirmed"
    item_id = accepted["items"][0]["id"]
    assert _reserved_tags(world, item_id) == [f"IT-PRJ-{world.tag}-1", f"IT-PRJ-{world.tag}-2"]
    reservations = supabase.table("equipment_reservations").select("*").eq("request_item_id", item_id).execute().data
    assert all(_instant(row["reserved_start"]) == _instant(request["needed_start"]) for row in reservations)
    assert all(_instant(row["reserved_end"]) == _instant(request["needed_end"]) for row in reservations)


def test_accepting_when_another_event_holds_the_stock_is_refused_and_reserves_nothing(world):
    other = _event(world, "Holds the projectors")
    _db_request(world, other, "confirmed", [("prj", 3, [_prj(world, 1), _prj(world, 2), _prj(world, 3)])])
    event = _event(world)
    request = create_request(event, _lines(world, prj=1), world.coordinator)

    with pytest.raises(ValidationError, match="not enough equipment"):
        accept_request(request["id"])

    assert get_request(request["id"])["status"] == "pending"
    item_id = get_request(request["id"])["items"][0]["id"]
    assert _reserved_tags(world, item_id) == []


def test_the_exclusion_constraint_refuses_one_unit_reserved_for_two_overlapping_periods(world):
    first, second = _event(world, "First"), _event(world, "Second")
    _, (first_item,) = _db_request(world, first, "confirmed", [("prj", 1, [_prj(world, 1)])])
    _, (second_item,) = _db_request(world, second, "pending", [("prj", 1, [])])

    with pytest.raises(APIError) as error:
        _reserve(
            second_item["id"], _prj(world, 1)["id"], start=f"{_DATE}T12:00:00+08:00", end=f"{_DATE}T16:00:00+08:00"
        )

    assert error.value.code == "23P01"  # exclusion_violation
    assert _reserved_tags(world, first_item["id"]) == [f"IT-PRJ-{world.tag}-1"]


def test_a_unit_returned_when_the_next_period_starts_can_be_reserved_again(world):
    first, second = _event(world, "First"), _event(world, "Second")
    _db_request(world, first, "confirmed", [("prj", 1, [_prj(world, 1)])])
    _, (second_item,) = _db_request(world, second, "pending", [("prj", 1, [])])

    # [10:00, 14:00) then [14:00, 18:00): half-open, so no overlap.
    _reserve(second_item["id"], _prj(world, 1)["id"], start=f"{_DATE}T14:00:00+08:00", end=f"{_DATE}T18:00:00+08:00")

    assert _reserved_tags(world, second_item["id"]) == [f"IT-PRJ-{world.tag}-1"]


# -- IS-41: reject with a reason ----------------------------------------------------


def test_rejecting_stores_the_reason_and_who_decided(world):
    event = _event(world)
    request = create_request(event, _lines(world, prj=1), world.coordinator)

    rejected = reject_request(request["id"], "  Needed elsewhere that day.  ", world.tech)

    assert rejected["status"] == "rejected"
    assert rejected["rejection_reason"] == "Needed elsewhere that day."
    assert rejected["decided_by"] == world.tech
    assert rejected["decided_at"]


def test_the_database_keeps_a_rejection_reason_and_the_status_in_step(world):
    event = _event(world)
    request, _ = _db_request(world, event, "pending", [])

    with pytest.raises(APIError) as without_reason:
        supabase.table("equipment_requests").update({"status": "rejected"}).eq("id", request["id"]).execute()
    with pytest.raises(APIError) as blank_reason:
        supabase.table("equipment_requests").update({"status": "rejected", "rejection_reason": "   "}).eq(
            "id", request["id"]
        ).execute()
    with pytest.raises(APIError) as reason_on_pending:
        supabase.table("equipment_requests").update({"rejection_reason": "why"}).eq("id", request["id"]).execute()

    assert without_reason.value.code == blank_reason.value.code == reason_on_pending.value.code == "23514"
    assert get_request(request["id"])["status"] == "pending"


def test_a_request_accepted_first_cannot_then_be_rejected(world):
    event = _event(world)
    request = create_request(event, _lines(world, prj=1), world.coordinator)
    accept_request(request["id"])

    with pytest.raises(ValidationError, match="no longer pending"):
        reject_request(request["id"], "Too late", world.tech)

    after = get_request(request["id"])
    assert after["status"] == "confirmed"
    assert after["rejection_reason"] is None


# -- IS-43: change a quantity --------------------------------------------------------


def test_an_accepted_increase_reserves_the_extra_unit_and_updates_the_quantity(world):
    event = _event(world)
    request = _confirmed(world, event, prj=1)
    item = request["items"][0]

    change = create_change_request(request["id"], item["id"], 2, world.coordinator)
    waiting = list_changes_for_request(request["id"])[0]
    assert waiting["check"]["accommodated"] is True

    accept_change(change["id"], world.tech)

    after = get_request(request["id"])
    assert after["items"][0]["quantity"] == 2
    assert _reserved_tags(world, item["id"]) == [f"IT-PRJ-{world.tag}-1", f"IT-PRJ-{world.tag}-2"]
    assert list_changes_for_request(request["id"])[0]["status"] == "accepted"


def test_an_accepted_decrease_releases_the_highest_tags(world):
    event = _event(world)
    request = _confirmed(world, event, prj=3)
    item = request["items"][0]

    change = create_change_request(request["id"], item["id"], 1, world.coordinator)
    accept_change(change["id"], world.tech)

    assert get_request(request["id"])["items"][0]["quantity"] == 1
    assert _reserved_tags(world, item["id"]) == [f"IT-PRJ-{world.tag}-1"]


def test_an_increase_the_stock_cannot_cover_is_refused_and_changes_nothing(world):
    other = _event(world, "Holds two projectors")
    _db_request(world, other, "confirmed", [("prj", 2, [_prj(world, 2), _prj(world, 3)])])
    event = _event(world)
    request = _confirmed(world, event, prj=1)
    item = request["items"][0]
    change = create_change_request(request["id"], item["id"], 3, world.coordinator)

    check = list_changes_for_request(request["id"])[0]["check"]
    assert check["accommodated"] is False and check["shortfall"] == 2
    with pytest.raises(ValidationError, match="not enough equipment"):
        accept_change(change["id"], world.tech)

    assert get_request(request["id"])["items"][0]["quantity"] == 1
    assert _reserved_tags(world, item["id"]) == [f"IT-PRJ-{world.tag}-1"]
    assert list_changes_for_request(request["id"])[0]["status"] == "pending"


def test_a_rejected_change_stores_its_reason_and_leaves_the_reservation_alone(world):
    event = _event(world)
    request = _confirmed(world, event, prj=1)
    item = request["items"][0]
    change = create_change_request(request["id"], item["id"], 2, world.coordinator)

    rejected = reject_change(change["id"], "Only one projector can be spared.", world.tech)

    assert rejected["status"] == "rejected"
    assert rejected["rejection_reason"] == "Only one projector can be spared."
    assert get_request(request["id"])["items"][0]["quantity"] == 1
    assert _reserved_tags(world, item["id"]) == [f"IT-PRJ-{world.tag}-1"]


def test_the_database_allows_only_one_pending_change_per_item(world):
    event = _event(world)
    _, (item,) = _db_request(world, event, "confirmed", [("prj", 1, [_prj(world, 1)])])
    row = {"request_item_id": item["id"], "requested_by": world.coordinator, "old_quantity": 1, "new_quantity": 2}
    supabase.table("equipment_change_requests").insert(row).execute()

    with pytest.raises(APIError) as error:
        supabase.table("equipment_change_requests").insert({**row, "new_quantity": 3}).execute()

    assert error.value.code == "23505"  # unique_violation (the partial index)


def test_the_database_refuses_a_change_to_the_same_quantity(world):
    event = _event(world)
    _, (item,) = _db_request(world, event, "confirmed", [("prj", 1, [_prj(world, 1)])])

    with pytest.raises(APIError) as error:
        supabase.table("equipment_change_requests").insert(
            {"request_item_id": item["id"], "requested_by": world.coordinator, "old_quantity": 1, "new_quantity": 1}
        ).execute()

    assert error.value.code == "23514"


# -- IS-66: withdraw a booking ---------------------------------------------------------


def test_cancelling_a_confirmed_request_frees_its_units_for_another_request(world):
    first, second = _event(world, "Withdraws"), _event(world, "Wants the projectors")
    held = _confirmed(world, first, prj=3)
    wanting = create_request(second, _lines(world, prj=3), world.coordinator)
    assert check_availability(wanting["id"])["all_sufficient"] is False

    cancelled = cancel_request(held["id"], world.coordinator)

    assert cancelled["status"] == "cancelled"  # 'cancelled' exists in the real enum
    assert _reserved_tags(world, held["items"][0]["id"]) == []
    assert check_availability(wanting["id"])["all_sufficient"] is True
    assert accept_request(wanting["id"])["status"] == "confirmed"


def test_cancelling_a_pending_request_marks_it_cancelled(world):
    event = _event(world)
    request = create_request(event, _lines(world, prj=1), world.coordinator)

    assert cancel_request(request["id"], world.coordinator)["status"] == "cancelled"


def test_cancelling_rejects_a_change_still_waiting_on_the_request(world):
    event = _event(world)
    request = _confirmed(world, event, prj=1)
    change = create_change_request(request["id"], request["items"][0]["id"], 2, world.coordinator)

    cancel_request(request["id"], world.coordinator)

    row = supabase.table("equipment_change_requests").select("*").eq("id", change["id"]).execute().data[0]
    assert row["status"] == "rejected"
    assert row["rejection_reason"] == "The equipment request was cancelled."


def test_a_request_that_is_already_cancelled_cannot_be_cancelled_again(world):
    event = _event(world)
    request = create_request(event, _lines(world, prj=1), world.coordinator)
    cancel_request(request["id"], world.coordinator)

    with pytest.raises(ValidationError, match="no longer be cancelled"):
        cancel_request(request["id"], world.coordinator)
