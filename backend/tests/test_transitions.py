"""
The event status state machine (app.events.transitions) -- unit level,
no database.

The _db_* functions are swapped for a tiny in-memory store that honours
the same contract as the real conditional UPDATE: a write only lands if
the row is still in the expected status, and reports zero rows otherwise.
That the real query actually carries that filter is proven separately --
narrowly in test_conditional_update_filters_on_expected_status below, and
against real Postgres in test_transitions_integration.py.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.events.transitions as transitions
from app.events.transitions import (
    ALLOWED,
    REASON_REQUIRED,
    IllegalTransitionError,
    TransitionConflictError,
    transition,
)
from app.shared.errors import NotFoundError, ValidationError

ALL_STATUSES = [
    "draft", "submitted", "under_review", "approved", "planning",
    "confirmed", "completed", "cancelled", "rejected",
]


class _Store:
    """In-memory stand-in for the events row + event_status_log."""

    def __init__(self, status):
        self.status = status
        self.history = []
        self.before_write = None  # hook: simulate a concurrent change

    def current_status(self, event_id):
        if event_id != "event-1":
            raise NotFoundError("Event not found.")
        return self.status

    def conditional_update(self, event_id, from_status, to_status):
        if self.before_write:
            self.before_write(self)
        if self.status != from_status:
            return None
        self.status = to_status
        return {"id": event_id, "status": to_status}

    def insert_history(self, event_id, from_status, to_status, actor, reason):
        self.history.append((from_status, to_status, actor, reason))


@pytest.fixture
def store(monkeypatch):
    def make(status):
        s = _Store(status)
        monkeypatch.setattr(transitions, "_db_current_status", s.current_status)
        monkeypatch.setattr(transitions, "_db_conditional_update", s.conditional_update)
        monkeypatch.setattr(transitions, "_db_insert_history", s.insert_history)
        return s

    return make


def _reason_for(to_status):
    return "a reason" if to_status in REASON_REQUIRED else None


# -- every legal edge is allowed -------------------------------------------


def test_edge_set_is_exactly_the_sourced_edges():
    assert ALLOWED == {
        ("draft", "submitted"),
        ("rejected", "submitted"),
        ("submitted", "under_review"),
        ("under_review", "approved"),
        ("under_review", "rejected"),
        ("approved", "planning"),
        ("planning", "confirmed"),
        ("confirmed", "completed"),
        ("approved", "cancelled"),
        ("planning", "cancelled"),
        ("confirmed", "cancelled"),
    }
    # Every edge carries its story text.
    assert all(transitions._EDGE_SOURCES[edge] for edge in ALLOWED)


@pytest.mark.parametrize("from_status,to_status", sorted(ALLOWED))
def test_every_legal_edge_is_allowed(store, from_status, to_status):
    s = store(from_status)
    result = transition("event-1", to_status, "actor-1", reason=_reason_for(to_status), expected_from=from_status)

    assert result["status"] == to_status
    assert s.status == to_status
    assert s.history == [(from_status, to_status, "actor-1", _reason_for(to_status))]


# -- illegal edges are refused ------------------------------------------------


@pytest.mark.parametrize(
    "from_status,to_status",
    [
        ("approved", "completed"),  # skips planning and confirmed
        ("draft", "confirmed"),
        ("draft", "approved"),  # organiser can't self-approve past review
        ("submitted", "approved"),  # skips under_review
        ("under_review", "planning"),
        ("cancelled", "approved"),
        ("rejected", "approved"),
        ("planning", "approved"),  # no going backwards
    ],
)
def test_representative_illegal_edges_are_refused(store, from_status, to_status):
    s = store(from_status)
    with pytest.raises(IllegalTransitionError):
        transition("event-1", to_status, "actor-1", reason="r", expected_from=from_status)
    assert s.status == from_status
    assert s.history == []


@pytest.mark.parametrize("to_status", ALL_STATUSES)
def test_completed_event_cannot_move_anywhere(store, to_status):
    """IS-38: completed events are read-only going forward."""
    s = store("completed")
    with pytest.raises(IllegalTransitionError):
        transition("event-1", to_status, "actor-1", reason="r", expected_from="completed")
    assert s.status == "completed"


@pytest.mark.parametrize("to_status", ALL_STATUSES)
def test_cancelled_event_cannot_move_anywhere(store, to_status):
    s = store("cancelled")
    with pytest.raises(IllegalTransitionError):
        transition("event-1", to_status, "actor-1", reason="r", expected_from="cancelled")
    assert s.status == "cancelled"


# -- reasons ----------------------------------------------------------------


def test_reason_is_required_exactly_for_cancelled_and_rejected():
    assert REASON_REQUIRED == {"cancelled", "rejected"}


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_cancel_without_a_reason_is_refused(store, reason):
    """IS-39: cancellation requires a reason."""
    s = store("planning")
    with pytest.raises(ValidationError):
        transition("event-1", "cancelled", "coord-1", reason=reason, expected_from="planning")
    assert s.status == "planning"
    assert s.history == []


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_reject_without_a_reason_is_refused(store, reason):
    s = store("under_review")
    with pytest.raises(ValidationError):
        transition("event-1", "rejected", "coord-1", reason=reason, expected_from="under_review")
    assert s.status == "under_review"


def test_non_string_reason_is_refused(store):
    store("planning")
    with pytest.raises(ValidationError):
        transition("event-1", "cancelled", "coord-1", reason=42, expected_from="planning")


def test_reason_is_stored_trimmed(store):
    s = store("approved")
    transition("event-1", "cancelled", "coord-1", reason="  Venue fell through  ", expected_from="approved")
    assert s.history == [("approved", "cancelled", "coord-1", "Venue fell through")]


def test_optional_reason_is_kept_when_given(store):
    s = store("approved")
    transition("event-1", "planning", "coord-1", reason="kicking off", expected_from="approved")
    assert s.history[0][3] == "kicking off"


# -- conflicts and stale writes ---------------------------------------------


def test_zero_rows_matched_is_a_conflict_not_a_silent_success(store):
    """The conditional update matched nothing (someone moved the event
    first): the caller gets a 409, and no history row is written for a
    change that didn't happen."""
    s = store("cancelled")  # really cancelled...
    with pytest.raises(TransitionConflictError) as exc_info:
        # ...but the caller authorised against a stale "planning"
        transition("event-1", "confirmed", "coord-1", expected_from="planning")
    assert exc_info.value.status_code == 409
    assert s.status == "cancelled"
    assert s.history == []


def test_transition_cannot_write_back_a_stale_status(store):
    """Regression for coordinator_service's old under_review write, which
    wrote back a status it had read earlier. Here the status is read,
    then changes concurrently before the write. The write must be
    conditional on from_status, so it fails with a conflict instead of
    overwriting (reverting) the concurrent change."""
    s = store("submitted")

    def concurrent_cancel(st):
        st.status = "approved"  # someone else moved it after our read

    s.before_write = concurrent_cancel
    with pytest.raises(TransitionConflictError):
        transition("event-1", "under_review", "org-1")  # expected_from omitted -> read first

    assert s.status == "approved"  # not reverted to under_review
    assert s.history == []


def test_conditional_update_filters_on_expected_status(monkeypatch):
    """The real _db_conditional_update puts from_status in the WHERE clause
    (not just the id). Recorded narrowly here; proven against Postgres in
    the integration test."""
    calls = []

    class Recorder:
        def __getattr__(self, name):
            def method(*args, **kwargs):
                calls.append((name, args))
                return self

            return method

        def execute(self):
            return SimpleNamespace(data=[])

    def table(name):
        calls.append(("table", (name,)))
        return Recorder()

    monkeypatch.setattr(transitions, "supabase", SimpleNamespace(table=table))

    assert transitions._db_conditional_update("event-1", "approved", "planning") is None
    assert ("table", ("events",)) in calls
    assert ("update", ({"status": "planning"},)) in calls
    assert ("eq", ("id", "event-1")) in calls
    assert ("eq", ("status", "approved")) in calls


def test_missing_event_is_not_found_when_status_must_be_read(store):
    store("draft")
    with pytest.raises(NotFoundError):
        transition("no-such-event", "submitted", "org-1")


def test_current_status_read_treats_maybe_single_none_as_not_found(monkeypatch):
    """maybe_single().execute() returns None itself on zero rows."""

    class Q:
        def __getattr__(self, name):
            return lambda *a, **k: self

        def execute(self):
            return None

    monkeypatch.setattr(transitions, "supabase", SimpleNamespace(table=lambda name: Q()))
    with pytest.raises(NotFoundError):
        transitions._db_current_status("event-1")


# -- creation --------------------------------------------------------------


def test_record_creation_writes_a_null_from_status_row(store):
    s = store("draft")
    transitions.record_creation("event-1", "org-1")
    assert s.history == [(None, "draft", "org-1", None)]
