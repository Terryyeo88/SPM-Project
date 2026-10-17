"""
Unit tests for app.equipment.calendar_service -- View Equipment
Availability Calendar (IS-47).

No database and no fake client: the service takes the unit exactly as
equipment_service.get_equipment returns it (occupancy already joined to
the event's name), so each test hands it one. That join itself is proven
against real Postgres in test_equipment_calendar_integration.py.

The BOUNDARY tests at the bottom are deliberate. PR #32 found the IS-11
venue calendar suite reached 100% line and branch coverage of the shared
overlap predicate yet caught neither boundary mutant, because no entry sat
on a range edge. These put entries exactly on both edges.
"""

from __future__ import annotations

import pytest

from app.equipment.calendar_service import get_equipment_calendar
from app.shared.errors import ValidationError


def _reservation(start: str, end: str, event_name: str = "Annual Tech Symposium", event_id: str = "event-1") -> dict:
    return {
        "reservation_id": f"res-{start}",
        "reserved_start": start,
        "reserved_end": end,
        "request_id": "req-1",
        "event_id": event_id,
        "event_name": event_name,
    }


def _unit(*reservations, status: str = "available") -> dict:
    return {
        "id": "unit-1",
        "asset_tag": "PRJ-001",
        "status": status,
        "notes": "HDMI and USB-C",
        "equipment_type_id": "type-1",
        "type": "projector",
        "occupancy": list(reservations),
    }


DECEMBER = ("2026-12-01", "2026-12-31")


# -- range filtering and entry shape ----------------------------------------


def test_reservation_within_range_is_an_entry_naming_its_event():
    unit = _unit(_reservation("2026-12-10T09:00:00+00:00", "2026-12-10T13:00:00+00:00"))

    result = get_equipment_calendar(unit, *DECEMBER)

    assert result["entries"] == [
        {
            "type": "reservation",
            "state": "reserved",
            "start": "2026-12-10T09:00:00+00:00",
            "end": "2026-12-10T13:00:00+00:00",
            "event_id": "event-1",
            "event_name": "Annual Tech Symposium",
        }
    ]


def test_entry_exposes_only_the_calendar_fields():
    """Not the reservation or request id -- only what the calendar shows."""
    unit = _unit(_reservation("2026-12-10T09:00:00+00:00", "2026-12-10T13:00:00+00:00"))

    entry = get_equipment_calendar(unit, *DECEMBER)["entries"][0]

    assert set(entry) == {"type", "state", "start", "end", "event_id", "event_name"}


def test_reservations_outside_the_range_are_excluded():
    unit = _unit(
        _reservation("2026-11-10T09:00:00+00:00", "2026-11-10T13:00:00+00:00", event_name="November"),
        _reservation("2026-12-10T09:00:00+00:00", "2026-12-10T13:00:00+00:00", event_name="December"),
        _reservation("2027-01-10T09:00:00+00:00", "2027-01-10T13:00:00+00:00", event_name="January"),
    )

    result = get_equipment_calendar(unit, *DECEMBER)

    assert [entry["event_name"] for entry in result["entries"]] == ["December"]


def test_multi_day_reservation_is_one_entry_with_its_whole_period():
    """The page marks every day it covers (AC5); the API returns it once,
    start to end."""
    unit = _unit(_reservation("2026-12-09T10:00:00+00:00", "2026-12-11T04:00:00+00:00"))

    entries = get_equipment_calendar(unit, *DECEMBER)["entries"]

    assert len(entries) == 1
    assert (entries[0]["start"], entries[0]["end"]) == ("2026-12-09T10:00:00+00:00", "2026-12-11T04:00:00+00:00")


def test_multi_day_reservation_starting_before_the_range_is_included():
    unit = _unit(_reservation("2026-11-29T10:00:00+00:00", "2026-12-02T04:00:00+00:00"))

    assert len(get_equipment_calendar(unit, *DECEMBER)["entries"]) == 1


def test_entries_are_ordered_by_start():
    unit = _unit(
        _reservation("2026-12-20T09:00:00+00:00", "2026-12-20T10:00:00+00:00", event_name="Later"),
        _reservation("2026-12-05T09:00:00+00:00", "2026-12-05T10:00:00+00:00", event_name="Earlier"),
    )

    names = [entry["event_name"] for entry in get_equipment_calendar(unit, *DECEMBER)["entries"]]

    assert names == ["Earlier", "Later"]


def test_unit_with_no_reservations_has_no_entries():
    assert get_equipment_calendar(_unit(), *DECEMBER)["entries"] == []


def test_response_carries_the_unit_profile_and_the_range():
    result = get_equipment_calendar(_unit(status="maintenance"), *DECEMBER)

    assert result["equipment"] == {
        "id": "unit-1",
        "asset_tag": "PRJ-001",
        "type": "projector",
        "notes": "HDMI and USB-C",
        "status": "maintenance",
    }
    assert result["range"] == {"start": "2026-12-01", "end": "2026-12-31"}


# -- 400s -----------------------------------------------------------------


def test_rejects_end_before_start():
    with pytest.raises(ValidationError, match="end must not be before start"):
        get_equipment_calendar(_unit(), "2026-12-31", "2026-12-01")


@pytest.mark.parametrize("start, end", [("not-a-date", "2026-12-31"), ("2026-12-01", "31/12/2026")])
def test_rejects_malformed_date(start, end):
    with pytest.raises(ValidationError, match="is not a valid date"):
        get_equipment_calendar(_unit(), start, end)


# -- boundaries -----------------------------------------------------------
# The range is whole days: 2026-12-10 .. 2026-12-12 runs from 12-10 00:00 to
# the last instant of 12-12, i.e. it ends where 12-13 00:00 begins.

RANGE = ("2026-12-10", "2026-12-12")


def test_reservation_ending_exactly_at_the_range_start_is_excluded():
    unit = _unit(_reservation("2026-12-09T20:00:00+00:00", "2026-12-10T00:00:00+00:00"))

    assert get_equipment_calendar(unit, *RANGE)["entries"] == []


def test_reservation_starting_exactly_at_the_range_end_is_excluded():
    """Starts at 12-13 00:00, the instant after the range's last one."""
    unit = _unit(_reservation("2026-12-13T00:00:00+00:00", "2026-12-13T04:00:00+00:00"))

    assert get_equipment_calendar(unit, *RANGE)["entries"] == []


def test_reservation_starting_at_the_ranges_last_instant_is_excluded():
    """The range's end is time.max on its last day (23:59:59.999999), and
    the comparison against it is strict -- this is the edge the predicate
    really tests, one microsecond before the midnight above. A `<=` there
    would let this in."""
    unit = _unit(_reservation("2026-12-12T23:59:59.999999+00:00", "2026-12-13T04:00:00+00:00"))

    assert get_equipment_calendar(unit, *RANGE)["entries"] == []


def test_reservation_covering_the_range_exactly_is_included():
    unit = _unit(_reservation("2026-12-10T00:00:00+00:00", "2026-12-13T00:00:00+00:00"))

    assert len(get_equipment_calendar(unit, *RANGE)["entries"]) == 1


def test_reservations_just_inside_each_edge_are_included():
    unit = _unit(
        _reservation("2026-12-09T20:00:00+00:00", "2026-12-10T00:00:01+00:00", event_name="Into the start"),
        _reservation("2026-12-12T23:59:59+00:00", "2026-12-13T04:00:00+00:00", event_name="From the end"),
    )

    names = [entry["event_name"] for entry in get_equipment_calendar(unit, *RANGE)["entries"]]

    assert names == ["Into the start", "From the end"]
