"""
Unit tests for app.equipment.equipment_service -- Check Equipment
Availability (Nawaz, Sprint 2, IS-18).

A small fake scoped to the four tables this service reads, same
"write a fake scoped to what THIS service needs" precedent as
test_calendar_service.py. Rows that PostgREST would return with an
embedded join are stored with the embed already attached; this tests the
availability arithmetic, not PostgREST's embed mechanics.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.equipment.equipment_service as service
from app.shared.errors import NotFoundError, ValidationError


class _FakeTable:
    def __init__(self, rows):
        self._rows = rows
        self._eq = []
        self._in = []
        self._single = False
        self._order = None

    def select(self, *_a, **_k):
        return self

    def eq(self, column, value):
        self._eq.append((column, value))
        return self

    def in_(self, column, values):
        self._in.append((column, tuple(values)))
        return self

    def order(self, column, desc=False):
        self._order = (column, desc)
        return self

    def maybe_single(self):
        self._single = True
        return self

    def execute(self):
        rows = [
            dict(row)
            for row in self._rows
            if all(row.get(c) == v for c, v in self._eq) and all(row.get(c) in vs for c, vs in self._in)
        ]
        if self._order:
            column, desc = self._order
            rows.sort(key=lambda row: row[column], reverse=desc)
        if self._single:
            return SimpleNamespace(data=rows[0] if rows else None)
        return SimpleNamespace(data=rows)


class _FakeSupabase:
    def __init__(self, **tables):
        self._tables = {
            name: tables.get(name, [])
            for name in ("equipment_units", "equipment_reservations", "equipment_requests")
        }

    def table(self, name):
        return _FakeTable(self._tables[name])


PROJECTOR = {"id": "type-prj", "name": "projector"}
MIC = {"id": "type-mic", "name": "microphone"}
SCREEN = {"id": "type-scr", "name": "screen"}


def _unit(unit_id, tag, type_, status="available"):
    return {
        "id": unit_id,
        "asset_tag": tag,
        "status": status,
        "notes": None,
        "equipment_type_id": type_["id"],
        "equipment_types": {"name": type_["name"]},
    }


def _request(request_id="req-1", items=(), start="2026-12-01T09:00:00+08:00", end="2026-12-01T13:00:00+08:00",
             status="pending"):
    return {
        "id": request_id,
        "event_id": "event-1",
        "requested_by": "coord-1",
        "status": status,
        "needed_start": start,
        "needed_end": end,
        "created_at": "2026-11-01T00:00:00+00:00",
        "events": {"name": "Tech Symposium"},
        "equipment_request_items": [
            {
                "id": f"item-{i}",
                "equipment_type_id": type_["id"],
                "quantity": quantity,
                "technical_requirements": note,
                "equipment_types": {"name": type_["name"]},
            }
            for i, (type_, quantity, note) in enumerate(items)
        ],
    }


def _reservation(unit_id, start, end, request_id="other-req", event_name="Other Event", event_id="event-9"):
    return {
        "id": f"res-{unit_id}-{start}",
        "equipment_id": unit_id,
        "reserved_start": start,
        "reserved_end": end,
        "equipment_request_items": {
            "request_id": request_id,
            "equipment_requests": {"event_id": event_id, "events": {"name": event_name}},
        },
    }


@pytest.fixture
def install(monkeypatch):
    def _install(**tables):
        monkeypatch.setattr(service, "supabase", _FakeSupabase(**tables))

    return _install


# -- availability: the core arithmetic ---------------------------------------


def test_all_units_free_is_sufficient(install):
    install(
        equipment_units=[_unit("u1", "PRJ-001", PROJECTOR), _unit("u2", "PRJ-002", PROJECTOR)],
        equipment_requests=[_request(items=[(PROJECTOR, 2, None)])],
    )
    result = service.check_availability("req-1")
    item = result["items"][0]
    assert item["requested"] == 2
    assert item["available"] == 2
    assert item["sufficient"] is True
    assert item["shortfall"] == 0
    assert item["available_units"] == ["PRJ-001", "PRJ-002"]
    assert result["all_sufficient"] is True


def test_overlapping_reservation_by_another_request_is_subtracted(install):
    install(
        equipment_units=[_unit("u1", "PRJ-001", PROJECTOR), _unit("u2", "PRJ-002", PROJECTOR)],
        equipment_requests=[_request(items=[(PROJECTOR, 2, None)])],
        equipment_reservations=[
            _reservation("u1", "2026-12-01T10:00:00+08:00", "2026-12-01T14:00:00+08:00", event_name="Gala")
        ],
    )
    item = service.check_availability("req-1")["items"][0]
    assert item["available"] == 1
    assert item["reserved_by_others"] == 1
    assert item["sufficient"] is False
    assert item["shortfall"] == 1
    assert item["available_units"] == ["PRJ-002"]
    assert item["conflicts"][0]["asset_tag"] == "PRJ-001"
    assert item["conflicts"][0]["event_name"] == "Gala"


def test_flags_only_the_short_item_not_the_whole_request(install):
    install(
        equipment_units=[
            _unit("u1", "PRJ-001", PROJECTOR),
            _unit("m1", "MIC-001", MIC),
            _unit("m2", "MIC-002", MIC),
        ],
        equipment_requests=[_request(items=[(PROJECTOR, 2, None), (MIC, 2, None)])],
    )
    result = service.check_availability("req-1")
    by_type = {item["type"]: item for item in result["items"]}
    assert by_type["projector"]["sufficient"] is False
    assert by_type["projector"]["shortfall"] == 1
    assert by_type["microphone"]["sufficient"] is True
    assert result["all_sufficient"] is False


def test_reservation_for_a_different_period_is_not_subtracted(install):
    install(
        equipment_units=[_unit("u1", "PRJ-001", PROJECTOR)],
        equipment_requests=[_request(items=[(PROJECTOR, 1, None)])],
        equipment_reservations=[
            _reservation("u1", "2026-12-02T09:00:00+08:00", "2026-12-02T13:00:00+08:00"),
        ],
    )
    item = service.check_availability("req-1")["items"][0]
    assert item["available"] == 1
    assert item["conflicts"] == []


def test_back_to_back_reservation_does_not_conflict(install):
    # Half-open [start, end): a unit returned at 09:00 is free from 09:00.
    install(
        equipment_units=[_unit("u1", "PRJ-001", PROJECTOR)],
        equipment_requests=[_request(items=[(PROJECTOR, 1, None)])],
        equipment_reservations=[
            _reservation("u1", "2026-12-01T05:00:00+08:00", "2026-12-01T09:00:00+08:00"),
            _reservation("u1", "2026-12-01T13:00:00+08:00", "2026-12-01T17:00:00+08:00"),
        ],
    )
    assert service.check_availability("req-1")["items"][0]["available"] == 1


def test_reservation_overlapping_by_one_minute_conflicts(install):
    install(
        equipment_units=[_unit("u1", "PRJ-001", PROJECTOR)],
        equipment_requests=[_request(items=[(PROJECTOR, 1, None)])],
        equipment_reservations=[
            _reservation("u1", "2026-12-01T12:59:00+08:00", "2026-12-01T17:00:00+08:00"),
        ],
    )
    assert service.check_availability("req-1")["items"][0]["available"] == 0


def test_timezones_are_compared_as_instants_not_wall_clock(install):
    # 09:00-13:00 SGT is 01:00-05:00 UTC. A reservation written in UTC as
    # 04:00-06:00 overlaps; one at 05:00-07:00 only touches the end.
    install(
        equipment_units=[_unit("u1", "PRJ-001", PROJECTOR), _unit("u2", "PRJ-002", PROJECTOR)],
        equipment_requests=[_request(items=[(PROJECTOR, 2, None)])],
        equipment_reservations=[
            _reservation("u1", "2026-12-01T04:00:00+00:00", "2026-12-01T06:00:00+00:00"),
            _reservation("u2", "2026-12-01T05:00:00+00:00", "2026-12-01T07:00:00+00:00"),
        ],
    )
    item = service.check_availability("req-1")["items"][0]
    assert item["available_units"] == ["PRJ-002"]


def test_units_out_of_service_are_not_counted_available(install):
    install(
        equipment_units=[
            _unit("u1", "PRJ-001", PROJECTOR),
            _unit("u2", "PRJ-002", PROJECTOR, status="maintenance"),
            _unit("u3", "PRJ-003", PROJECTOR, status="retired"),
        ],
        equipment_requests=[_request(items=[(PROJECTOR, 2, None)])],
    )
    item = service.check_availability("req-1")["items"][0]
    assert item["total_units"] == 3
    assert item["out_of_service"] == 2
    assert item["available"] == 1
    assert item["sufficient"] is False


def test_requests_own_reservations_are_excluded(install):
    # Checking an already-confirmed request must not count its own held
    # units against itself.
    install(
        equipment_units=[_unit("u1", "PRJ-001", PROJECTOR)],
        equipment_requests=[_request(items=[(PROJECTOR, 1, None)], status="confirmed")],
        equipment_reservations=[
            _reservation("u1", "2026-12-01T09:00:00+08:00", "2026-12-01T13:00:00+08:00", request_id="req-1"),
        ],
    )
    item = service.check_availability("req-1")["items"][0]
    assert item["available"] == 1
    assert item["sufficient"] is True


def test_type_with_no_units_is_flagged_not_an_error(install):
    install(equipment_units=[], equipment_requests=[_request(items=[(SCREEN, 1, None)])])
    item = service.check_availability("req-1")["items"][0]
    assert item["total_units"] == 0
    assert item["available"] == 0
    assert item["sufficient"] is False
    assert item["shortfall"] == 1


def test_units_of_other_types_do_not_leak_into_the_count(install):
    install(
        equipment_units=[_unit("m1", "MIC-001", MIC), _unit("u1", "PRJ-001", PROJECTOR)],
        equipment_requests=[_request(items=[(PROJECTOR, 1, None)])],
    )
    item = service.check_availability("req-1")["items"][0]
    assert item["total_units"] == 1
    assert item["available_units"] == ["PRJ-001"]


def test_response_carries_request_period_and_event(install):
    install(equipment_units=[], equipment_requests=[_request(items=[])])
    result = service.check_availability("req-1")
    assert result["request"]["needed_start"] == "2026-12-01T09:00:00+08:00"
    assert result["request"]["event_name"] == "Tech Symposium"
    assert result["items"] == []
    assert result["all_sufficient"] is True


def test_missing_request_raises_not_found(install):
    install()
    with pytest.raises(NotFoundError):
        service.check_availability("nope")


# -- get_request --------------------------------------------------------------


def test_get_request_flattens_items_and_event_name(install):
    install(equipment_requests=[_request(items=[(PROJECTOR, 2, "HDMI input needed")])])
    request = service.get_request("req-1")
    assert request["event_name"] == "Tech Symposium"
    assert request["items"][0]["type"] == "projector"
    assert request["items"][0]["quantity"] == 2
    assert request["items"][0]["technical_requirements"] == "HDMI input needed"
    assert "equipment_request_items" not in request


# -- list_requests ------------------------------------------------------------


def _user(*roles, user_id="u-1"):
    return SimpleNamespace(id=user_id, roles=frozenset(roles))


def test_technical_staff_lists_every_request(install):
    other = _request("req-2", items=[(MIC, 1, None)])
    other["requested_by"] = "coord-2"
    install(equipment_requests=[_request(items=[(PROJECTOR, 1, None)]), other])
    assert len(service.list_requests(_user("technical_support_staff"))) == 2


def test_coordinator_lists_only_their_own_requests(install):
    other = _request("req-2", items=[(MIC, 1, None)])
    other["requested_by"] = "coord-2"
    install(equipment_requests=[_request(items=[(PROJECTOR, 1, None)]), other])
    result = service.list_requests(_user("event_coordinator", user_id="coord-1"))
    assert [row["id"] for row in result] == ["req-1"]


def test_list_requests_summarises_items(install):
    install(equipment_requests=[_request(items=[(PROJECTOR, 2, None), (MIC, 3, None)])])
    row = service.list_requests(_user("technical_support_staff"))[0]
    assert row["items"] == [{"type": "projector", "quantity": 2}, {"type": "microphone", "quantity": 3}]


def test_list_requests_filters_by_status(install):
    confirmed = _request("req-2", items=[], status="confirmed")
    install(equipment_requests=[_request(items=[]), confirmed])
    result = service.list_requests(_user("technical_support_staff"), "confirmed")
    assert [row["id"] for row in result] == ["req-2"]


def test_list_requests_rejects_unknown_status(install):
    install()
    with pytest.raises(ValidationError):
        service.list_requests(_user("technical_support_staff"), "bogus")


def test_list_requests_fails_closed_for_unrelated_role(install):
    install(equipment_requests=[_request(items=[])])
    assert service.list_requests(_user("attendee")) == []


# -- equipment records -------------------------------------------------------


def test_list_equipment_flattens_type_and_filters(install):
    install(equipment_units=[_unit("u1", "PRJ-001", PROJECTOR), _unit("m1", "MIC-001", MIC)])
    assert [u["asset_tag"] for u in service.list_equipment()] == ["MIC-001", "PRJ-001"]
    assert [u["asset_tag"] for u in service.list_equipment(type_name="projector")] == ["PRJ-001"]


def test_list_equipment_filters_by_status_and_rejects_unknown(install):
    install(
        equipment_units=[_unit("u1", "PRJ-001", PROJECTOR), _unit("u2", "PRJ-002", PROJECTOR, status="maintenance")]
    )
    assert [u["asset_tag"] for u in service.list_equipment(status="maintenance")] == ["PRJ-002"]
    with pytest.raises(ValidationError):
        service.list_equipment(status="bogus")


def test_get_equipment_returns_occupancy_with_event_and_period(install):
    install(
        equipment_units=[_unit("u1", "PRJ-001", PROJECTOR)],
        equipment_reservations=[
            _reservation("u1", "2026-12-05T09:00:00+08:00", "2026-12-05T13:00:00+08:00", event_name="Gala",
                         event_id="event-7", request_id="req-7"),
            _reservation("u1", "2026-12-01T09:00:00+08:00", "2026-12-01T13:00:00+08:00", event_name="Workshop"),
        ],
    )
    record = service.get_equipment("u1")
    assert record["asset_tag"] == "PRJ-001"
    assert record["type"] == "projector"
    assert [o["event_name"] for o in record["occupancy"]] == ["Workshop", "Gala"]
    gala = record["occupancy"][1]
    assert gala["event_id"] == "event-7"
    assert gala["request_id"] == "req-7"
    assert gala["reserved_start"] == "2026-12-05T09:00:00+08:00"
    assert gala["reserved_end"] == "2026-12-05T13:00:00+08:00"


def test_get_equipment_with_no_reservations_has_empty_occupancy(install):
    install(equipment_units=[_unit("u1", "PRJ-001", PROJECTOR)])
    assert service.get_equipment("u1")["occupancy"] == []


def test_get_equipment_only_exposes_event_id_and_name(install):
    install(
        equipment_units=[_unit("u1", "PRJ-001", PROJECTOR)],
        equipment_reservations=[_reservation("u1", "2026-12-01T09:00:00+08:00", "2026-12-01T13:00:00+08:00")],
    )
    occupancy = service.get_equipment("u1")["occupancy"][0]
    assert set(occupancy) == {
        "reservation_id", "reserved_start", "reserved_end", "request_id", "event_id", "event_name",
    }


def test_get_equipment_missing_raises_not_found(install):
    install()
    with pytest.raises(NotFoundError):
        service.get_equipment("nope")
