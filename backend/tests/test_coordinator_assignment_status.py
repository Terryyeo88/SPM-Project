"""
assign_initial_coordinator's status handling after moving onto
app.events.transitions -- unit level, no database.

The bug being pinned: the old update wrote
`"status": "under_review" if event["status"] == "submitted" else event["status"]`
-- i.e. it wrote back a status read moments earlier, silently reverting any
change made in between. Now the coordinator claim never touches status, and
the status change goes through transition(), conditional on `submitted`.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.events.coordinator_service as cs
import app.events.transitions as transitions
from app.events.transitions import TransitionConflictError


class _Recorder:
    def __init__(self, calls, table, claim_matches):
        self.calls, self.table, self.claim_matches = calls, table, claim_matches
        self.op = None

    def update(self, values):
        self.op = ("update", values)
        self.calls.append((self.table, "update", values))
        return self

    def insert(self, values):
        self.op = ("insert", values)
        self.calls.append((self.table, "insert", values))
        return self

    def eq(self, column, value):
        self.calls.append((self.table, "eq", (column, value)))
        return self

    def is_(self, column, value):
        self.calls.append((self.table, "is_", (column, value)))
        return self

    def execute(self):
        if self.op and self.op[0] == "update":
            return SimpleNamespace(data=[{"id": "event-1"}] if self.claim_matches else [])
        return SimpleNamespace(data=[])


@pytest.fixture
def world(monkeypatch):
    def setup(status="submitted", claim_matches=True, current_status=None):
        calls, history = [], []
        monkeypatch.setattr(
            cs, "_get_event",
            lambda event_id: {"id": event_id, "status": status, "coordinator_id": None, "name": "E",
                              "preferred_start_date": "2026-12-01"},
        )
        monkeypatch.setattr(cs, "_get_all_coordinators", lambda: [{"id": "coord-1", "name": "C", "email": "c@x"}])
        monkeypatch.setattr(cs, "_is_available", lambda cid, event: True)
        monkeypatch.setattr(cs, "_workload", lambda cid: 0)
        monkeypatch.setattr(cs, "_notify_coordinator_assigned", lambda event, coordinator: None)
        monkeypatch.setattr(cs, "supabase", SimpleNamespace(table=lambda name: _Recorder(calls, name, claim_matches)))

        db = {"status": current_status or status}

        def conditional_update(event_id, from_status, to_status):
            if db["status"] != from_status:
                return None
            db["status"] = to_status
            return {"id": event_id, "status": to_status}

        monkeypatch.setattr(transitions, "_db_conditional_update", conditional_update)
        monkeypatch.setattr(transitions, "_db_insert_history", lambda *args: history.append(args))
        return calls, history, db

    return setup


def _event_updates(calls):
    return [c[2] for c in calls if c[0] == "events" and c[1] == "update"]


def test_claim_never_writes_status(world):
    calls, _, _ = world()
    cs.assign_initial_coordinator("event-1", actor="org-1")
    assert _event_updates(calls) == [{"coordinator_id": "coord-1"}]


def test_claim_is_conditional_on_still_being_unassigned(world):
    calls, _, _ = world()
    cs.assign_initial_coordinator("event-1", actor="org-1")
    assert ("events", "is_", ("coordinator_id", "null")) in calls


def test_submitted_event_moves_to_under_review_attributed_to_actor(world):
    _, history, db = world()
    cs.assign_initial_coordinator("event-1", actor="org-1")
    assert db["status"] == "under_review"
    assert history == [("event-1", "submitted", "under_review", "org-1", None)]


def test_actor_is_optional_for_existing_callers(world):
    """Backward compatible: callers that don't pass actor still work, and the
    history row records NULL (no human actor)."""
    _, history, _ = world()
    cs.assign_initial_coordinator("event-1")
    assert history[0][3] is None


def test_non_submitted_event_gets_coordinator_but_status_untouched(world):
    """Old behaviour preserved: assigning to a non-submitted event leaves
    its status alone -- but now by not writing it at all, instead of by
    writing back a copy of it."""
    calls, history, db = world(status="planning")
    cs.assign_initial_coordinator("event-1", actor="org-1")
    assert db["status"] == "planning"
    assert history == []
    assert all("status" not in u for u in _event_updates(calls))


def test_concurrent_status_change_is_not_reverted(world):
    """The regression itself. _get_event read `submitted`, but by the time
    the status is written the event has been moved (here: to cancelled,
    via some concurrent path). The old code would have written
    `under_review` over it. Now the conditional transition refuses, and
    the concurrent change stands."""
    _, history, db = world(status="submitted", current_status="cancelled")
    with pytest.raises(TransitionConflictError):
        cs.assign_initial_coordinator("event-1", actor="org-1")
    assert db["status"] == "cancelled"
    assert history == []


def test_lost_claim_race_is_refused_not_double_assigned(world):
    calls, history, _ = world(claim_matches=False)
    with pytest.raises(ValueError, match="already has a coordinator"):
        cs.assign_initial_coordinator("event-1", actor="org-1")
    assert history == []
    assert not [c for c in calls if c[0] == "coordinator_assignment_log"]
