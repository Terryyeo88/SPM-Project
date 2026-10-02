"""Unit tests for one-coordinator-per-request assignment
(app.events.coordinator_service).

An event request with several sessions is stored as several events rows
sharing a shared_event_id. The whole request gets ONE coordinator, who can
then view and edit every session -- so initial assignment and reassignment
both act on all of a request's sessions together.

No database: the module's `supabase` client is swapped for FakeSupabase,
and the helpers that read user_roles/profiles are replaced with fixed
coordinator data. The real-database behaviour of the single-event case is
covered by test_coordinator_assignment_integration.py.
"""

from __future__ import annotations

import pytest

import app.events.coordinator_service as cs
from app.events.coordinator_service import (
    NoCoordinatorAvailableError,
    assign_initial_coordinator,
    reassign_coordinator,
)
from tests.fake_supabase import FakeSupabase

COORDINATORS = {
    "coord-a": {"id": "coord-a", "name": "Alice", "email": "alice@example.com"},
    "coord-b": {"id": "coord-b", "name": "Brandon", "email": "brandon@example.com"},
}


def _event(event_id, day, **overrides):
    row = {
        "id": event_id,
        "name": "Workshop",
        "organizer_id": "organizer-1",
        "coordinator_id": None,
        "status": "submitted",
        "shared_event_id": "group-1",
        "preferred_start_date": f"2026-11-{day:02d}",
        "preferred_end_date": f"2026-11-{day:02d}",
        "preferred_start_time": "09:00",
        "preferred_end_time": "17:00",
    }
    row.update(overrides)
    return row


@pytest.fixture
def db(monkeypatch):
    """A FakeSupabase plus fixed coordinators. Alice (coord-a) has the
    lighter workload, so she's picked whenever she's free."""
    fake = FakeSupabase()
    notified = []
    monkeypatch.setattr(cs, "supabase", fake)
    monkeypatch.setattr(cs, "_get_all_coordinators", lambda: list(COORDINATORS.values()))
    monkeypatch.setattr(cs, "_get_coordinator_profile", lambda coordinator_id: COORDINATORS[coordinator_id])
    monkeypatch.setattr(cs, "_workload", lambda coordinator_id: {"coord-a": 0, "coord-b": 5}[coordinator_id])
    monkeypatch.setattr(
        cs, "_notify_coordinator_assigned", lambda event, coordinator: notified.append(coordinator["id"])
    )
    fake.notified = notified
    return fake


def _log(db):
    return db.tables.get("coordinator_assignment_log", [])


# -- Initial assignment --------------------------------------------------------


def test_one_coordinator_is_assigned_to_every_submitted_session_of_the_request(db):
    """Assigning from one session gives every submitted session of the
    request the SAME coordinator and moves each to under_review. A draft
    session of the same request and another request's session are left
    alone. Each assigned session gets its own log row, and the coordinator
    is notified once for the request."""
    db.rows = [
        _event("s1", 10),
        _event("s2", 11),
        _event("s3", 12),
        _event("still-draft", 13, status="draft"),
        _event("other-request", 10, shared_event_id="group-2"),
    ]

    chosen = assign_initial_coordinator("s1")

    assert chosen["id"] == "coord-a"
    for session_id in ("s1", "s2", "s3"):
        assert db.get(session_id)["coordinator_id"] == "coord-a"
        assert db.get(session_id)["status"] == "under_review"
    assert db.get("still-draft")["coordinator_id"] is None
    assert db.get("other-request")["coordinator_id"] is None
    assert sorted(row["event_id"] for row in _log(db)) == ["s1", "s2", "s3"]
    assert db.notified == ["coord-a"]


def test_coordinator_must_be_free_for_every_session(db):
    """Alice is free on the first session's date but already busy on the
    second's, so she can't take the request -- Brandon gets all of it,
    even though Alice has the lighter workload."""
    db.rows = [
        _event("s1", 10),
        _event("s2", 11),
        _event("alice-busy", 11, shared_event_id="group-9", coordinator_id="coord-a", status="planning"),
    ]

    chosen = assign_initial_coordinator("s1")

    assert chosen["id"] == "coord-b"
    assert {db.get("s1")["coordinator_id"], db.get("s2")["coordinator_id"]} == {"coord-b"}


def test_no_coordinator_free_for_every_session_assigns_nobody(db):
    """If no single coordinator is free for all the sessions, the request is
    left unassigned (still "submitted") rather than split between
    coordinators, and nothing is logged."""
    db.rows = [
        _event("s1", 10),
        _event("s2", 11),
        _event("alice-busy", 10, shared_event_id="group-8", coordinator_id="coord-a", status="planning"),
        _event("brandon-busy", 11, shared_event_id="group-9", coordinator_id="coord-b", status="planning"),
    ]

    with pytest.raises(NoCoordinatorAvailableError, match="2026-11-10, 2026-11-11"):
        assign_initial_coordinator("s1")

    assert db.get("s1")["coordinator_id"] is None
    assert db.get("s2")["status"] == "submitted"
    assert _log(db) == []


def test_sessions_of_the_same_request_do_not_clash_with_each_other(db):
    """Two sessions of one request on overlapping times don't count as the
    coordinator being double-booked -- they're the same request."""
    db.rows = [_event("morning", 10), _event("overlapping", 10, preferred_start_time="12:00")]

    chosen = assign_initial_coordinator("morning")

    assert chosen["id"] == "coord-a"
    assert db.get("overlapping")["coordinator_id"] == "coord-a"


def test_a_request_that_already_has_a_coordinator_keeps_them(db):
    """If another session of the request already has a coordinator, that
    same coordinator is reused, so the request is never split -- even if
    someone else would win the workload pick."""
    db.rows = [
        _event("assigned", 10, coordinator_id="coord-b", status="under_review"),
        _event("unassigned", 11),
    ]

    chosen = assign_initial_coordinator("unassigned")

    assert chosen["id"] == "coord-b"
    assert db.get("unassigned")["coordinator_id"] == "coord-b"
    assert db.get("unassigned")["status"] == "under_review"


def test_a_single_session_request_without_shared_id_is_assigned_on_its_own(db):
    """Requests created before sessions existed (no shared_event_id) are
    assigned exactly as before -- just that one event."""
    db.rows = [_event("legacy", 10, shared_event_id=None), _event("other-legacy", 10, shared_event_id=None)]

    assign_initial_coordinator("legacy")

    assert db.get("legacy")["coordinator_id"] == "coord-a"
    assert db.get("other-legacy")["coordinator_id"] is None


# -- Reassignment --------------------------------------------------------------


def test_reassignment_moves_every_session_of_the_request(db):
    """Reassigning from one session hands the whole request to the new
    coordinator: every session the outgoing coordinator held moves, with
    a log row each, and statuses are unchanged. The outgoing coordinator's
    other requests stay with them."""
    db.rows = [
        _event("s1", 10, coordinator_id="coord-a", status="under_review"),
        _event("s2", 11, coordinator_id="coord-a", status="planning"),
        _event("alice-other", 20, shared_event_id="group-2", coordinator_id="coord-a", status="planning"),
    ]

    reassign_coordinator("s1", "coord-b", requested_by="coord-a", reason="on leave")

    assert db.get("s1")["coordinator_id"] == "coord-b"
    assert db.get("s2")["coordinator_id"] == "coord-b"
    assert db.get("s1")["status"] == "under_review"
    assert db.get("s2")["status"] == "planning"
    assert db.get("alice-other")["coordinator_id"] == "coord-a"
    assert sorted(row["event_id"] for row in _log(db)) == ["s1", "s2"]
    assert {row["reason"] for row in _log(db)} == {"on leave"}


def test_reassignment_refused_when_new_coordinator_is_busy_on_any_session(db):
    """The new coordinator must be free for every session of the request;
    if they're busy on even one, nothing moves."""
    db.rows = [
        _event("s1", 10, coordinator_id="coord-a", status="under_review"),
        _event("s2", 11, coordinator_id="coord-a", status="under_review"),
        _event("brandon-busy", 11, shared_event_id="group-9", coordinator_id="coord-b", status="planning"),
    ]

    with pytest.raises(NoCoordinatorAvailableError, match="Brandon"):
        reassign_coordinator("s1", "coord-b", requested_by="coord-a")

    assert db.get("s1")["coordinator_id"] == "coord-a"
    assert db.get("s2")["coordinator_id"] == "coord-a"
    assert _log(db) == []
