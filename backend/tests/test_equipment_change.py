"""
Unit tests for app.equipment.change_service -- update quantity on an
existing equipment reservation (Nawaz, Sprint 3, IS-43).

The reads that join several tables (the change row with its embeds,
get_request, the availability check) are stubbed so each test states what
the world looks like; the writes go to the fake database from the accept
tests so what was reserved, released, claimed and updated can be asserted.
"""

from __future__ import annotations

import pytest
from postgrest.exceptions import APIError

import app.equipment.change_service as service
from app.shared.errors import ValidationError
from tests.test_equipment_accept import _DB, END, PROJECTOR, PROJECTORS, START, _unit

TYPE_ID = PROJECTOR["id"]


def _change_row(old=2, new=3, status="pending"):
    return {
        "id": "chg-1",
        "request_item_id": "item-1",
        "requested_by": "coord-1",
        "old_quantity": old,
        "new_quantity": new,
        "status": status,
        "rejection_reason": None,
        "decided_at": None,
        "created_at": "2026-11-01T00:00:00+00:00",
        "equipment_request_items": {
            "id": "item-1",
            "request_id": "req-1",
            "equipment_type_id": TYPE_ID,
            "quantity": old,
            "equipment_types": {"name": "projector"},
            "equipment_requests": {"events": {"name": "Tech Symposium"}},
        },
    }


def _request(quantity=2):
    return {
        "id": "req-1",
        "status": "confirmed",
        "event_id": "event-1",
        "event_name": "Tech Symposium",
        "event_status": "planning",
        "requested_by": "coord-1",
        "needed_start": START,
        "needed_end": END,
        "items": [
            {"id": "item-1", "equipment_type_id": TYPE_ID, "type": "projector", "quantity": quantity,
             "technical_requirements": None}
        ],
    }


def _availability(available):
    return {
        "items": [{"equipment_type_id": TYPE_ID, "type": "projector", "available": available}],
        "all_sufficient": True,
    }


def _own(tags):
    ids = {"PRJ-001": "p1", "PRJ-002": "p2", "PRJ-003": "p3"}
    return [
        {"id": f"own-{tag}", "equipment_id": ids[tag], "request_item_id": "item-1",
         "equipment_units": {"asset_tag": tag}}
        for tag in tags
    ]


class _World:
    """Installs the stubs and a fake database; `change` is the change row
    as it currently stands (updated by the fake's writes)."""

    def __init__(self, monkeypatch, *, old=2, new=3, available=3, held=("PRJ-001", "PRJ-002")):
        self.db = _DB(PROJECTORS, [])
        self.db.tables["equipment_change_requests"] = [{"id": "chg-1", "status": "pending"}]
        self.db.tables["equipment_request_items"] = [{"id": "item-1", "quantity": old}]
        self.db.tables["equipment_reservations"] = _own(held)
        self.request = _request(old)
        monkeypatch.setattr(service, "supabase", self.db)
        monkeypatch.setattr(service, "get_request", lambda request_id: self.request)
        self.free = [_unit(u["id"], u["asset_tag"], PROJECTOR) for u in PROJECTORS]
        monkeypatch.setattr(
            service,
            "_compute_availability",
            lambda request_id: (_availability(available), {TYPE_ID: self.free}, self.request),
        )
        self.change = _change_row(old, new)
        monkeypatch.setattr(service, "_get_change_row", lambda change_id: self._row())
        self.notified = []
        monkeypatch.setattr(service, "_notify_request_decision", lambda *args: self.notified.append(args))

    def _row(self):
        stored = self.db.tables["equipment_change_requests"][0]
        return {**self.change, **{k: v for k, v in stored.items() if k != "id"}}

    @property
    def reservation_tags(self):
        return sorted(
            (row.get("equipment_units") or {}).get("asset_tag") or row["equipment_id"]
            for row in self.db.tables["equipment_reservations"]
        )


# -- the recalculation -------------------------------------------------------


def test_an_increase_is_accommodated_when_enough_units_could_cover_the_request():
    change = service._flatten_change(_change_row(2, 3))
    assert service._recalculate(change, _availability(3)) == {
        "current": 2, "requested": 3, "available": 3, "accommodated": True, "shortfall": 0,
    }


def test_an_increase_is_not_accommodated_when_short_and_says_by_how_much():
    change = service._flatten_change(_change_row(2, 5))
    check = service._recalculate(change, _availability(3))
    assert check["accommodated"] is False
    assert check["shortfall"] == 2


def test_a_decrease_is_always_accommodated():
    change = service._flatten_change(_change_row(3, 1))
    assert service._recalculate(change, _availability(0))["accommodated"] is True


def test_pending_changes_carry_a_fresh_check_and_decided_ones_do_not(monkeypatch):
    world = _World(monkeypatch)
    decided = {**_change_row(), "id": "chg-0", "status": "rejected", "rejection_reason": "No stock"}
    world.db.tables["equipment_change_requests"].append({})
    monkeypatch.setattr(
        world.db, "table", lambda name: _Rows([_change_row(), decided]) if name == "equipment_change_requests" else None
    )
    changes = service.list_changes_for_request("req-1")
    assert changes[0]["check"]["accommodated"] is True
    assert "check" not in changes[1]
    assert changes[1]["rejection_reason"] == "No stock"


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def select(self, *_a, **_k):
        return self

    def in_(self, *_a, **_k):
        return self

    def order(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def execute(self):
        from types import SimpleNamespace

        return SimpleNamespace(data=self._rows)


# -- the coordinator's ask ---------------------------------------------------


def test_create_stores_the_ask_with_the_current_and_requested_quantity(monkeypatch):
    world = _World(monkeypatch, old=2, new=3)
    world.db.tables["equipment_change_requests"] = []
    monkeypatch.setattr(service, "_get_change_row", lambda change_id: _change_row(2, 4))

    result = service.create_change_request("req-1", "item-1", 4, "coord-1")

    stored = world.db.tables["equipment_change_requests"][0]
    assert (stored["request_item_id"], stored["old_quantity"], stored["new_quantity"]) == ("item-1", 2, 4)
    assert stored["requested_by"] == "coord-1"
    assert result["new_quantity"] == 4
    # Asking changes nothing on the confirmed request itself.
    assert world.db.tables["equipment_request_items"][0]["quantity"] == 2
    assert len(world.db.tables["equipment_reservations"]) == 2


@pytest.mark.parametrize("quantity", [0, -1, "3", 2.5, True, None])
def test_the_new_quantity_must_be_a_whole_number_of_at_least_one(monkeypatch, quantity):
    _World(monkeypatch)
    with pytest.raises(ValidationError, match="whole number"):
        service.create_change_request("req-1", "item-1", quantity, "coord-1")


def test_an_item_is_required_and_must_belong_to_the_request(monkeypatch):
    _World(monkeypatch)
    with pytest.raises(ValidationError, match="Choose which item"):
        service.create_change_request("req-1", None, 3, "coord-1")
    with pytest.raises(ValidationError, match="not part of this request"):
        service.create_change_request("req-1", "other-item", 3, "coord-1")


def test_asking_for_the_quantity_it_already_has_is_refused(monkeypatch):
    _World(monkeypatch, old=2)
    with pytest.raises(ValidationError, match="already 2"):
        service.create_change_request("req-1", "item-1", 2, "coord-1")


def test_a_second_ask_while_one_is_waiting_is_refused(monkeypatch):
    world = _World(monkeypatch)
    world.db.tables["equipment_change_requests"] = [{"id": "chg-0", "request_item_id": "item-1", "status": "pending"}]
    with pytest.raises(ValidationError, match="already has a change waiting"):
        service.create_change_request("req-1", "item-1", 4, "coord-1")


def test_the_unique_index_catching_a_simultaneous_ask_is_a_clear_error(monkeypatch):
    world = _World(monkeypatch)
    world.db.tables["equipment_change_requests"] = []

    real_table = world.db.table

    class _RefusesInsert:
        def __init__(self, table):
            self._table = table

        def __getattr__(self, name):
            return getattr(self._table, name)

        def insert(self, payload):
            return self

        def execute(self):
            raise APIError({"code": "23505", "message": "duplicate key", "details": "", "hint": ""})

    monkeypatch.setattr(
        world.db,
        "table",
        lambda name: _RefusesInsert(real_table(name)) if name == "equipment_change_requests" else real_table(name),
    )
    with pytest.raises(ValidationError, match="already has a change waiting"):
        service.create_change_request("req-1", "item-1", 4, "coord-1")


# -- accepting: increase -----------------------------------------------------


def test_accepting_an_increase_reserves_the_extra_unit_and_updates_the_quantity(monkeypatch):
    world = _World(monkeypatch, old=2, new=3, available=3)

    service.accept_change("chg-1", "tech-1")

    added = [r for r in world.db.tables["equipment_reservations"] if not r["id"].startswith("own-")]
    assert [r["equipment_id"] for r in added] == ["p3"]
    assert (added[0]["reserved_start"], added[0]["reserved_end"]) == (START, END)
    assert added[0]["request_item_id"] == "item-1"
    assert world.db.tables["equipment_request_items"][0]["quantity"] == 3
    stored = world.db.tables["equipment_change_requests"][0]
    assert (stored["status"], stored["decided_by"]) == ("accepted", "tech-1")
    assert world.notified == [("req-1", "change accepted")]


def test_the_extra_units_are_never_ones_the_request_already_holds(monkeypatch):
    world = _World(monkeypatch, old=1, new=2, available=3, held=("PRJ-002",))
    world.request = _request(1)

    service.accept_change("chg-1", "tech-1")

    added = [r["equipment_id"] for r in world.db.tables["equipment_reservations"] if not r["id"].startswith("own-")]
    assert added == ["p1"]  # lowest free tag that is not p2, which it already holds


def test_an_increase_the_stock_cannot_cover_is_refused_and_changes_nothing(monkeypatch):
    world = _World(monkeypatch, old=2, new=5, available=3)

    with pytest.raises(ValidationError, match=r"projector: 5 wanted, 3 available"):
        service.accept_change("chg-1", "tech-1")

    assert world.db.kinds("insert") == [] and world.db.kinds("update") == []
    assert world.db.tables["equipment_change_requests"][0]["status"] == "pending"
    assert world.db.tables["equipment_request_items"][0]["quantity"] == 2


def test_the_exclusion_constraint_refusing_the_extra_unit_is_a_clear_error(monkeypatch):
    world = _World(monkeypatch, old=2, new=3, available=3)
    world.db.insert_error = APIError({"code": "23P01", "message": "overlap", "details": "", "hint": ""})

    with pytest.raises(ValidationError, match="just reserved for another event"):
        service.accept_change("chg-1", "tech-1")

    assert world.db.tables["equipment_change_requests"][0]["status"] == "pending"
    assert world.db.tables["equipment_request_items"][0]["quantity"] == 2


def test_someone_deciding_it_first_releases_the_extra_unit(monkeypatch):
    world = _World(monkeypatch, old=2, new=3, available=3)
    world.db.before_update = lambda: world.db.tables["equipment_change_requests"][0].update(status="accepted")

    with pytest.raises(ValidationError, match="no longer pending"):
        service.accept_change("chg-1", "tech-1")

    assert len(world.db.tables["equipment_reservations"]) == 2
    assert world.db.tables["equipment_request_items"][0]["quantity"] == 2


def test_a_failure_updating_the_quantity_undoes_the_claim_and_the_reservation(monkeypatch):
    world = _World(monkeypatch, old=2, new=3, available=3)
    real_table = world.db.table

    def table(name):
        if name == "equipment_request_items":
            raise RuntimeError("db down")
        return real_table(name)

    monkeypatch.setattr(world.db, "table", table)
    with pytest.raises(RuntimeError):
        service.accept_change("chg-1", "tech-1")

    assert len(world.db.tables["equipment_reservations"]) == 2
    stored = world.db.tables["equipment_change_requests"][0]
    assert stored["status"] == "pending" and stored["decided_by"] is None


def test_a_line_whose_quantity_moved_since_the_ask_is_refused(monkeypatch):
    world = _World(monkeypatch, old=2, new=3)
    world.request = _request(4)
    with pytest.raises(ValidationError, match="has changed since the ask"):
        service.accept_change("chg-1", "tech-1")
    assert world.db.kinds("update") == []


# -- accepting: decrease -----------------------------------------------------


def test_accepting_a_decrease_releases_the_highest_asset_tags(monkeypatch):
    world = _World(monkeypatch, old=3, new=1, available=0, held=("PRJ-001", "PRJ-002", "PRJ-003"))
    world.request = _request(3)

    service.accept_change("chg-1", "tech-1")

    assert world.reservation_tags == ["PRJ-001"]
    assert world.db.tables["equipment_request_items"][0]["quantity"] == 1
    assert world.db.tables["equipment_change_requests"][0]["status"] == "accepted"
    assert world.db.kinds("insert") == []


# -- rejecting ---------------------------------------------------------------


def test_reject_records_the_reason_and_leaves_the_reservation_alone(monkeypatch):
    world = _World(monkeypatch, old=2, new=5)

    result = service.reject_change("chg-1", "  Only 3 projectors are free.  ", "tech-1")

    stored = world.db.tables["equipment_change_requests"][0]
    assert (stored["status"], stored["rejection_reason"], stored["decided_by"]) == (
        "rejected", "Only 3 projectors are free.", "tech-1",
    )
    assert result["rejection_reason"] == "Only 3 projectors are free."
    assert world.db.tables["equipment_request_items"][0]["quantity"] == 2
    assert len(world.db.tables["equipment_reservations"]) == 2
    assert world.notified == [("req-1", "change rejected")]


@pytest.mark.parametrize("reason", [None, "", "   ", 5])
def test_rejecting_requires_a_reason(monkeypatch, reason):
    world = _World(monkeypatch)
    with pytest.raises(ValidationError, match="reason is required"):
        service.reject_change("chg-1", reason, "tech-1")
    assert world.db.kinds("update") == []


def test_a_very_long_reason_is_refused(monkeypatch):
    _World(monkeypatch)
    with pytest.raises(ValidationError, match="too long"):
        service.reject_change("chg-1", "x" * 1001, "tech-1")


def test_rejecting_a_change_decided_a_moment_ago_does_not_overwrite_it(monkeypatch):
    world = _World(monkeypatch)
    world.db.before_update = lambda: world.db.tables["equipment_change_requests"][0].update(status="accepted")
    with pytest.raises(ValidationError, match="no longer pending"):
        service.reject_change("chg-1", "No stock", "tech-1")
    assert "rejection_reason" not in world.db.tables["equipment_change_requests"][0]
