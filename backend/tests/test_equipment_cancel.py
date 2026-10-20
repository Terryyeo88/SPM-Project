"""
Unit tests for app.equipment.equipment_service.cancel_request -- the
coordinator cancelling an equipment request (Nawaz, Sprint 3). Reuses the
fake database from the accept tests.
"""

from __future__ import annotations

import pytest

import app.equipment.equipment_service as service
from app.shared.errors import ValidationError
from tests.test_equipment_accept import _DB, PROJECTOR, PROJECTORS, _request


def _world(monkeypatch, status="confirmed"):
    db = _DB(PROJECTORS, [_request([(PROJECTOR, 2)], status=status)])
    db.tables["equipment_reservations"] = [
        {"id": "r1", "equipment_id": "p1", "request_item_id": "item-1"},
        {"id": "r2", "equipment_id": "p2", "request_item_id": "item-1"},
        {"id": "other", "equipment_id": "p3", "request_item_id": "item-other"},
    ]
    db.tables["equipment_change_requests"] = [
        {"id": "chg-waiting", "request_item_id": "item-1", "status": "pending"},
        {"id": "chg-done", "request_item_id": "item-1", "status": "accepted"},
        {"id": "chg-other", "request_item_id": "item-other", "status": "pending"},
    ]
    monkeypatch.setattr(service, "supabase", db)
    notified = []
    monkeypatch.setattr(service, "_notify_request_decision", lambda *args: notified.append(args))
    return db, notified


def _status(db):
    return db.tables["equipment_requests"][0]["status"]


def test_cancelling_a_confirmed_request_frees_its_units_and_keeps_everyone_elses(monkeypatch):
    db, notified = _world(monkeypatch)

    result = service.cancel_request("req-1", "coord-1")

    assert result["status"] == "cancelled"
    assert [r["id"] for r in db.tables["equipment_reservations"]] == ["other"]
    assert notified == [("req-1", "cancelled")]


def test_cancelling_a_pending_request_just_marks_it_cancelled(monkeypatch):
    db, _ = _world(monkeypatch, status="pending")
    db.tables["equipment_reservations"] = []
    assert service.cancel_request("req-1", "coord-1")["status"] == "cancelled"


def test_a_waiting_quantity_change_is_rejected_with_a_reason_and_others_are_untouched(monkeypatch):
    db, _ = _world(monkeypatch)

    service.cancel_request("req-1", "coord-1")

    changes = {row["id"]: row for row in db.tables["equipment_change_requests"]}
    assert changes["chg-waiting"]["status"] == "rejected"
    assert changes["chg-waiting"]["rejection_reason"] == "The equipment request was cancelled."
    assert changes["chg-done"]["status"] == "accepted"
    assert changes["chg-other"]["status"] == "pending"


@pytest.mark.parametrize("status", ["rejected", "cancelled"])
def test_a_request_that_is_already_over_is_refused(monkeypatch, status):
    db, _ = _world(monkeypatch, status=status)
    with pytest.raises(ValidationError, match="no longer be cancelled"):
        service.cancel_request("req-1", "coord-1")
    assert db.kinds("update") == [] and db.kinds("delete") == []


def test_the_status_update_is_conditional_so_a_racing_decision_wins(monkeypatch):
    """Technical Support rejects between our read and our write: the
    conditional update matches nothing, and no units are freed."""
    db, notified = _world(monkeypatch, status="pending")
    db.before_update = lambda: db.tables["equipment_requests"][0].update(status="rejected")

    with pytest.raises(ValidationError, match="changed while you were cancelling"):
        service.cancel_request("req-1", "coord-1")

    assert _status(db) == "rejected"
    assert len(db.tables["equipment_reservations"]) == 3
    assert notified == []


def test_a_failure_freeing_the_units_puts_the_status_back(monkeypatch):
    db, notified = _world(monkeypatch)
    real_table = db.table

    def table(name):
        if name == "equipment_reservations":
            raise RuntimeError("db down")
        return real_table(name)

    monkeypatch.setattr(db, "table", table)
    with pytest.raises(RuntimeError):
        service.cancel_request("req-1", "coord-1")

    assert _status(db) == "confirmed"
    assert len(db.tables["equipment_reservations"]) == 3
    assert notified == []


def test_cancelled_is_a_valid_status_filter():
    assert "cancelled" in service.REQUEST_STATUSES
