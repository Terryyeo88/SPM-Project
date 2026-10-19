"""
Unit tests for app.equipment.equipment_service.reject_request -- reject an
equipment request with an explanation (Nawaz, Sprint 3, IS-41). Reuses the
fake database from the accept tests.
"""

from __future__ import annotations

import pytest

import app.equipment.equipment_service as service
from app.shared.errors import ValidationError
from tests.test_equipment_accept import PROJECTOR, PROJECTORS, _install, _request


def _setup(monkeypatch, status="pending"):
    return _install(monkeypatch, PROJECTORS[:1], [_request([(PROJECTOR, 2)], status=status)])


def test_reject_marks_the_request_rejected_with_the_reason_and_who_decided(monkeypatch):
    db = _setup(monkeypatch)

    result = service.reject_request("req-1", "  Only 1 projector free that day.  ", "tech-1")

    row = db.tables["equipment_requests"][0]
    assert row["status"] == "rejected"
    assert row["rejection_reason"] == "Only 1 projector free that day."
    assert row["decided_by"] == "tech-1"
    assert row["decided_at"]
    assert result["status"] == "rejected"
    assert result["rejection_reason"] == "Only 1 projector free that day."


def test_reject_reserves_nothing(monkeypatch):
    db = _setup(monkeypatch)
    service.reject_request("req-1", "Not enough stock", "tech-1")
    assert db.tables["equipment_reservations"] == []
    assert db.kinds("insert") == []


def test_reject_notifies_the_coordinator_of_the_decision(monkeypatch):
    _setup(monkeypatch)
    calls = []
    monkeypatch.setattr(service, "_notify_request_decision", lambda *args: calls.append(args))
    service.reject_request("req-1", "Not enough stock", "tech-1")
    assert calls == [("req-1", "rejected")]


@pytest.mark.parametrize("reason", [None, "", "   ", 5, ["x"]])
def test_a_reason_is_required(monkeypatch, reason):
    db = _setup(monkeypatch)
    with pytest.raises(ValidationError, match="reason is required"):
        service.reject_request("req-1", reason, "tech-1")
    assert db.tables["equipment_requests"][0]["status"] == "pending"
    assert db.kinds("update") == []


def test_a_very_long_reason_is_refused(monkeypatch):
    _setup(monkeypatch)
    with pytest.raises(ValidationError, match="too long"):
        service.reject_request("req-1", "x" * (service.MAX_REJECTION_REASON_LENGTH + 1), "tech-1")


def test_the_update_is_conditional_on_the_request_still_being_pending(monkeypatch):
    """Someone accepts between the authz check and the update: the rejection
    must match no row instead of overwriting the confirmed request."""
    db = _setup(monkeypatch)

    def accepted_meanwhile():
        db.tables["equipment_requests"][0]["status"] = "confirmed"

    db.before_update = accepted_meanwhile
    with pytest.raises(ValidationError, match="no longer pending"):
        service.reject_request("req-1", "Not enough stock", "tech-1")
    row = db.tables["equipment_requests"][0]
    assert row["status"] == "confirmed"
    assert "rejection_reason" not in row
    assert ("status", "pending", "eq") in db.kinds("update")[0][2]
