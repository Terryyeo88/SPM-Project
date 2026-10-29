"""
Unit tests for app.equipment.equipment_service.create_request and
list_equipment_types -- Record Equipment Request for Event (Nawaz,
Sprint 3, IS-17).

A recording fake scoped to the three tables the write touches: it keeps
what was inserted/deleted so the tests can assert on the exact rows and on
the clean-up when the second insert fails. get_request is stubbed (its own
tests live in test_equipment_service.py).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.equipment.equipment_service as service
from app.shared.errors import ValidationError

PROJECTOR = {"id": "type-prj", "name": "projector"}
MIC = {"id": "type-mic", "name": "microphone"}


class _Table:
    def __init__(self, db, name):
        self._db = db
        self._name = name
        self._op = None
        self._payload = None
        self._filters = []

    def select(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def in_(self, column, values):
        self._filters.append((column, tuple(values), "in"))
        return self

    def eq(self, column, value):
        self._filters.append((column, value, "eq"))
        return self

    def insert(self, payload):
        self._op = "insert"
        self._payload = payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    def execute(self):
        db = self._db
        if self._op == "insert":
            if self._name == "equipment_request_items" and db.fail_items:
                raise RuntimeError("items insert failed")
            rows = self._payload if isinstance(self._payload, list) else [self._payload]
            stored = []
            for row in rows:
                row = {"id": f"{self._name}-{len(db.inserted[self._name]) + 1}", **row}
                db.inserted[self._name].append(row)
                stored.append(row)
            return SimpleNamespace(data=stored)
        if self._op == "delete":
            db.deleted[self._name].append(list(self._filters))
            return SimpleNamespace(data=[])
        rows = list(db.types)
        for column, value, kind in self._filters:
            rows = [r for r in rows if (r[column] in value if kind == "in" else r[column] == value)]
        return SimpleNamespace(data=rows)


class _DB:
    def __init__(self, types=(PROJECTOR, MIC), fail_items=False):
        self.types = list(types)
        self.fail_items = fail_items
        self.inserted = {"equipment_requests": [], "equipment_request_items": []}
        self.deleted = {"equipment_requests": [], "equipment_request_items": []}

    def table(self, name):
        return _Table(self, name)


@pytest.fixture
def db(monkeypatch):
    fake = _DB()
    monkeypatch.setattr(service, "supabase", fake)
    monkeypatch.setattr(service, "get_request", lambda request_id: {"id": request_id, "status": "pending"})
    return fake


EVENT = SimpleNamespace(
    id="event-1",
    preferred_start_date="2026-11-10",
    preferred_end_date=None,
    preferred_start_time="10:00",
    preferred_end_time="14:00",
)


def _line(type_id="type-prj", quantity=2, requirements=None):
    return {"equipment_type_id": type_id, "quantity": quantity, "technical_requirements": requirements}


# -- happy path --------------------------------------------------------------


def test_creates_a_pending_request_for_the_event_with_its_lines(db):
    result = service.create_request(EVENT, [_line("type-prj", 2, "HDMI input"), _line("type-mic", 1)], "coord-1")

    request_row = db.inserted["equipment_requests"][0]
    assert request_row["event_id"] == "event-1"
    assert request_row["requested_by"] == "coord-1"
    assert request_row["status"] == "pending"
    assert result == {"id": request_row["id"], "status": "pending"}

    items = db.inserted["equipment_request_items"]
    assert [(i["equipment_type_id"], i["quantity"], i["request_id"]) for i in items] == [
        ("type-prj", 2, request_row["id"]),
        ("type-mic", 1, request_row["id"]),
    ]
    assert items[0]["technical_requirements"] == "HDMI input"
    assert items[1]["technical_requirements"] is None


def test_needed_period_is_the_sessions_own_window_in_singapore_time(db):
    service.create_request(EVENT, [_line()], "coord-1")
    row = db.inserted["equipment_requests"][0]
    assert row["needed_start"] == "2026-11-10T10:00:00+08:00"
    assert row["needed_end"] == "2026-11-10T14:00:00+08:00"


def test_session_with_no_times_needs_equipment_all_day(db):
    event = SimpleNamespace(
        id="event-2",
        preferred_start_date="2026-11-10",
        preferred_end_date=None,
        preferred_start_time=None,
        preferred_end_time=None,
    )
    service.create_request(event, [_line()], "coord-1")
    row = db.inserted["equipment_requests"][0]
    assert row["needed_start"].startswith("2026-11-10T00:00:00")
    assert row["needed_end"].startswith("2026-11-10T23:59:59")


def test_blank_requirements_are_stored_as_null_and_text_is_trimmed(db):
    service.create_request(EVENT, [_line("type-prj", 1, "   "), _line("type-mic", 1, "  boundary mic  ")], "coord-1")
    items = db.inserted["equipment_request_items"]
    assert items[0]["technical_requirements"] is None
    assert items[1]["technical_requirements"] == "boundary mic"


# -- validation: nothing is written for a bad request ------------------------


@pytest.mark.parametrize("items", [None, [], "projector", {"equipment_type_id": "type-prj"}])
def test_needs_at_least_one_item(db, items):
    with pytest.raises(ValidationError, match="at least one"):
        service.create_request(EVENT, items, "coord-1")
    assert db.inserted["equipment_requests"] == []


@pytest.mark.parametrize("quantity", [None, 0, -1, 2.5, "3", True])
def test_quantity_must_be_a_whole_number_of_at_least_one(db, quantity):
    """AC: prevents submitting if quantity is missing or zero."""
    with pytest.raises(ValidationError, match="quantity"):
        service.create_request(EVENT, [_line(quantity=quantity)], "coord-1")
    assert db.inserted["equipment_requests"] == []


def test_missing_quantity_key_is_rejected(db):
    with pytest.raises(ValidationError, match="quantity"):
        service.create_request(EVENT, [{"equipment_type_id": "type-prj"}], "coord-1")


@pytest.mark.parametrize("type_id", [None, "", "   ", 5])
def test_each_line_needs_a_type(db, type_id):
    with pytest.raises(ValidationError, match="equipment type"):
        service.create_request(EVENT, [_line(type_id=type_id)], "coord-1")


def test_a_type_can_only_appear_once(db):
    with pytest.raises(ValidationError, match="only appear once"):
        service.create_request(EVENT, [_line("type-prj", 1), _line("type-prj", 2)], "coord-1")
    assert db.inserted["equipment_requests"] == []


def test_unknown_type_is_rejected(db):
    with pytest.raises(ValidationError, match="does not exist"):
        service.create_request(EVENT, [_line("type-nope")], "coord-1")
    assert db.inserted["equipment_requests"] == []


def test_requirements_must_be_text_and_within_the_limit(db):
    with pytest.raises(ValidationError, match="must be text"):
        service.create_request(EVENT, [_line(requirements=5)], "coord-1")
    with pytest.raises(ValidationError, match="too long"):
        service.create_request(EVENT, [_line(requirements="x" * 2001)], "coord-1")
    service.create_request(EVENT, [_line(requirements="x" * 2000)], "coord-1")


def test_a_non_object_line_is_rejected(db):
    with pytest.raises(ValidationError, match="Item 1"):
        service.create_request(EVENT, ["projector"], "coord-1")


# -- failure clean-up --------------------------------------------------------


def test_request_row_is_deleted_if_its_lines_cannot_be_saved(monkeypatch):
    fake = _DB(fail_items=True)
    monkeypatch.setattr(service, "supabase", fake)
    monkeypatch.setattr(service, "get_request", lambda request_id: {"id": request_id})

    with pytest.raises(RuntimeError, match="items insert failed"):
        service.create_request(EVENT, [_line()], "coord-1")

    created_id = fake.inserted["equipment_requests"][0]["id"]
    assert fake.deleted["equipment_requests"] == [[("id", created_id, "eq")]]


# -- list_equipment_types ----------------------------------------------------


def test_lists_equipment_types(db):
    assert service.list_equipment_types() == [PROJECTOR, MIC]
