"""
Unit tests for app.equipment.equipment_service.accept_request -- Accept an
equipment request and reserve stock (Nawaz, Sprint 3, IS-19).

The real availability arithmetic runs (nothing in _compute_availability is
stubbed); only the database is faked. The fake supports the writes accept
makes (insert, conditional update, delete) and can be told to refuse the
reservation insert the way the exclusion constraint would.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from postgrest.exceptions import APIError

import app.equipment.equipment_service as service
from app.shared.errors import ValidationError

PROJECTOR = {"id": "type-prj", "name": "projector"}
MIC = {"id": "type-mic", "name": "microphone"}

START = "2026-12-01T09:00:00+08:00"
END = "2026-12-01T13:00:00+08:00"


class _Table:
    def __init__(self, db, name):
        self._db = db
        self._name = name
        self._rows = db.tables[name]
        self._filters = []
        self._op = "select"
        self._payload = None
        self._single = False

    def select(self, *_a, **_k):
        return self

    def eq(self, column, value):
        self._filters.append((column, value, "eq"))
        return self

    def in_(self, column, values):
        self._filters.append((column, tuple(values), "in"))
        return self

    def order(self, *_a, **_k):
        return self

    def maybe_single(self):
        self._single = True
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload):
        self._op = "update"
        self._payload = payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    def _matching(self):
        def ok(row):
            return all((row.get(c) in v) if kind == "in" else (row.get(c) == v) for c, v, kind in self._filters)

        return [row for row in self._rows if ok(row)]

    def execute(self):
        db = self._db
        if self._op == "insert":
            if self._name == "equipment_reservations" and db.insert_error:
                raise db.insert_error
            rows = self._payload if isinstance(self._payload, list) else [self._payload]
            stored = []
            for row in rows:
                row = {"id": f"res-{len(db.tables[self._name]) + 1}", **row}
                self._rows.append(row)
                stored.append(dict(row))
            db.writes.append(("insert", self._name, stored))
            return SimpleNamespace(data=stored)
        if self._op == "update":
            if db.before_update:
                db.before_update()
            matched = self._matching()
            for row in matched:
                row.update(self._payload)
            db.writes.append(("update", self._name, list(self._filters), dict(self._payload)))
            return SimpleNamespace(data=[dict(row) for row in matched])
        if self._op == "delete":
            matched = self._matching()
            for row in matched:
                self._rows.remove(row)
            db.writes.append(("delete", self._name, list(self._filters)))
            return SimpleNamespace(data=[dict(row) for row in matched])
        rows = [dict(row) for row in self._matching()]
        if self._single:
            return SimpleNamespace(data=rows[0] if rows else None)
        return SimpleNamespace(data=rows)


class _DB:
    def __init__(self, units, requests, reservations=()):
        self.tables = {
            "equipment_units": units,
            "equipment_requests": requests,
            "equipment_reservations": list(reservations),
        }
        self.insert_error = None
        self.before_update = None
        self.writes = []

    def table(self, name):
        return _Table(self, name)

    def kinds(self, kind):
        return [write for write in self.writes if write[0] == kind]


def _unit(unit_id, tag, type_, status="available"):
    return {
        "id": unit_id,
        "asset_tag": tag,
        "status": status,
        "equipment_type_id": type_["id"],
        "equipment_types": {"name": type_["name"]},
    }


def _request(items, status="pending", request_id="req-1"):
    return {
        "id": request_id,
        "event_id": "event-1",
        "requested_by": "coord-1",
        "status": status,
        "needed_start": START,
        "needed_end": END,
        "created_at": "2026-11-01T00:00:00+00:00",
        "events": {"name": "Tech Symposium", "status": "planning"},
        "equipment_request_items": [
            {
                "id": f"item-{i}",
                "equipment_type_id": type_["id"],
                "quantity": quantity,
                "technical_requirements": None,
                "equipment_types": {"name": type_["name"]},
            }
            for i, (type_, quantity) in enumerate(items, start=1)
        ],
    }


def _other_reservation(unit_id, start="2026-12-01T10:00:00+08:00", end="2026-12-01T14:00:00+08:00"):
    return {
        "id": f"held-{unit_id}",
        "equipment_id": unit_id,
        "reserved_start": start,
        "reserved_end": end,
        "equipment_request_items": {
            "request_id": "other-req",
            "equipment_requests": {"event_id": "event-9", "events": {"name": "Gala"}},
        },
    }


def _install(monkeypatch, units, requests, reservations=()):
    db = _DB(units, requests, reservations)
    monkeypatch.setattr(service, "supabase", db)
    return db


PROJECTORS = [_unit("p1", "PRJ-001", PROJECTOR), _unit("p2", "PRJ-002", PROJECTOR), _unit("p3", "PRJ-003", PROJECTOR)]
MICS = [_unit("m1", "MIC-001", MIC), _unit("m2", "MIC-002", MIC)]


# -- happy path --------------------------------------------------------------


def test_accept_reserves_one_row_per_unit_and_confirms_the_request(monkeypatch):
    db = _install(monkeypatch, PROJECTORS + MICS, [_request([(PROJECTOR, 2), (MIC, 1)])])

    result = service.accept_request("req-1")

    reservations = db.tables["equipment_reservations"]
    assert [(r["equipment_id"], r["request_item_id"]) for r in reservations] == [
        ("p1", "item-1"),
        ("p2", "item-1"),
        ("m1", "item-2"),
    ]
    assert db.tables["equipment_requests"][0]["status"] == "confirmed"
    assert result["status"] == "confirmed"


def test_each_reservation_copies_the_requests_period(monkeypatch):
    """Justin's convention 3: reservations copy needed_start / needed_end."""
    db = _install(monkeypatch, PROJECTORS, [_request([(PROJECTOR, 1)])])
    service.accept_request("req-1")
    reservation = db.tables["equipment_reservations"][0]
    assert (reservation["reserved_start"], reservation["reserved_end"]) == (START, END)


def test_returns_the_allocated_units_by_type(monkeypatch):
    _install(monkeypatch, PROJECTORS + MICS, [_request([(PROJECTOR, 2), (MIC, 1)])])
    result = service.accept_request("req-1")
    assert result["allocated"] == [
        {
            "equipment_type_id": "type-prj",
            "type": "projector",
            "quantity": 2,
            "units": [{"id": "p1", "asset_tag": "PRJ-001"}, {"id": "p2", "asset_tag": "PRJ-002"}],
        },
        {
            "equipment_type_id": "type-mic",
            "type": "microphone",
            "quantity": 1,
            "units": [{"id": "m1", "asset_tag": "MIC-001"}],
        },
    ]


def test_reserves_the_reservations_before_flipping_the_status(monkeypatch):
    """Justin's convention 2: confirmed only once the rows are written."""
    db = _install(monkeypatch, PROJECTORS, [_request([(PROJECTOR, 1)])])
    service.accept_request("req-1")
    order = [(kind, table) for kind, table, *_ in db.writes]
    assert order == [("insert", "equipment_reservations"), ("update", "equipment_requests")]


def test_the_status_change_is_conditioned_on_the_request_still_being_pending(monkeypatch):
    db = _install(monkeypatch, PROJECTORS, [_request([(PROJECTOR, 1)])])
    service.accept_request("req-1")
    _, _, filters, payload = db.kinds("update")[0]
    assert ("status", "pending", "eq") in filters
    assert payload == {"status": "confirmed"}


# -- which units it picks ----------------------------------------------------


def test_skips_units_held_for_an_overlapping_event_and_units_out_of_service(monkeypatch):
    units = [
        _unit("p1", "PRJ-001", PROJECTOR),
        _unit("p2", "PRJ-002", PROJECTOR, status="maintenance"),
        _unit("p3", "PRJ-003", PROJECTOR),
        _unit("p4", "PRJ-004", PROJECTOR),
    ]
    db = _install(monkeypatch, units, [_request([(PROJECTOR, 2)])], [_other_reservation("p1")])
    service.accept_request("req-1")
    taken = [r["equipment_id"] for r in db.tables["equipment_reservations"] if r["id"].startswith("res-")]
    assert taken == ["p3", "p4"]


def test_a_unit_returned_when_the_request_starts_is_free(monkeypatch):
    """Half-open [start, end): held until 09:00, needed from 09:00."""
    held = _other_reservation("p1", "2026-12-01T05:00:00+08:00", START)
    db = _install(monkeypatch, [_unit("p1", "PRJ-001", PROJECTOR)], [_request([(PROJECTOR, 1)])], [held])
    service.accept_request("req-1")
    assert db.tables["equipment_requests"][0]["status"] == "confirmed"


# -- not enough stock: nothing is reserved -----------------------------------


def test_refuses_when_there_is_not_enough_and_says_what_is_short(monkeypatch):
    db = _install(monkeypatch, PROJECTORS[:1], [_request([(PROJECTOR, 2)])])
    with pytest.raises(ValidationError, match=r"projector: 2 requested, 1 available"):
        service.accept_request("req-1")
    assert db.writes == []
    assert db.tables["equipment_requests"][0]["status"] == "pending"


def test_one_short_line_means_nothing_is_reserved_for_any_line(monkeypatch):
    """A request is accepted whole or not at all."""
    db = _install(monkeypatch, PROJECTORS + MICS[:1], [_request([(PROJECTOR, 1), (MIC, 2)])])
    with pytest.raises(ValidationError, match="microphone"):
        service.accept_request("req-1")
    assert db.writes == []
    assert db.tables["equipment_reservations"] == []


def test_a_unit_that_is_not_available_does_not_count_as_stock(monkeypatch):
    units = [_unit("p1", "PRJ-001", PROJECTOR, status="retired")]
    db = _install(monkeypatch, units, [_request([(PROJECTOR, 1)])])
    with pytest.raises(ValidationError, match="1 requested, 0 available"):
        service.accept_request("req-1")
    assert db.writes == []


# -- races -------------------------------------------------------------------


@pytest.mark.parametrize("code", ["23P01", "40P01"])
def test_the_exclusion_constraint_refusing_a_unit_is_a_clear_error(monkeypatch, code):
    db = _install(monkeypatch, PROJECTORS, [_request([(PROJECTOR, 1)])])
    db.insert_error = APIError({"code": code, "message": "conflicting key value violates exclusion constraint"})
    with pytest.raises(ValidationError, match="just reserved for another event"):
        service.accept_request("req-1")
    assert db.tables["equipment_requests"][0]["status"] == "pending"
    assert db.kinds("update") == []


def test_any_other_database_error_is_not_swallowed(monkeypatch):
    db = _install(monkeypatch, PROJECTORS, [_request([(PROJECTOR, 1)])])
    db.insert_error = APIError({"code": "XX000", "message": "boom"})
    with pytest.raises(APIError):
        service.accept_request("req-1")


def test_a_second_accept_racing_the_first_releases_what_it_reserved(monkeypatch):
    """Two Technical Support users accept at once: the loser's status
    update matches no pending row, so the units it just reserved go back."""
    db = _install(monkeypatch, PROJECTORS, [_request([(PROJECTOR, 2)])])

    def other_accept_lands_first():
        db.tables["equipment_requests"][0]["status"] = "confirmed"

    db.before_update = other_accept_lands_first
    with pytest.raises(ValidationError, match="no longer pending"):
        service.accept_request("req-1")
    assert db.tables["equipment_reservations"] == []


def test_a_failure_flipping_the_status_also_releases_the_units(monkeypatch):
    db = _install(monkeypatch, PROJECTORS, [_request([(PROJECTOR, 1)])])

    def explode():
        raise RuntimeError("connection lost")

    db.before_update = explode
    with pytest.raises(RuntimeError):
        service.accept_request("req-1")
    assert db.tables["equipment_reservations"] == []


# -- get_request carries what the rule needs ---------------------------------


def test_get_request_exposes_the_events_status(monkeypatch):
    _install(monkeypatch, PROJECTORS, [_request([(PROJECTOR, 1)])])
    request = service.get_request("req-1")
    assert request["event_name"] == "Tech Symposium"
    assert request["event_status"] == "planning"
