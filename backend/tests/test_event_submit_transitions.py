"""
Submit and resubmit through app.events.transitions -- unit level, no
database. Covers the dead end this ticket closes: an organiser could edit a
rejected request (rule_event_edit) but nothing let them submit it again.

event_service.submit_event_request is driven with transitions' _db_*
functions faked, and assign_initial_coordinator replaced by a spy.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.events.event_service as service_module
import app.events.transitions as transitions
from app.authz import actions
from app.authz.policy import can
from app.events.coordinator_service import NoCoordinatorAvailableError
from app.events.transitions import TransitionConflictError
from tests.factories import FakeEvent, make_user

ORG = "org-1"


def _complete_event(status, coordinator_id=None):
    return SimpleNamespace(
        id="event-1", organizer_id=ORG, coordinator_id=coordinator_id, status=status,
        name="Conference", description="d", purpose="p",
        preferred_start_date="2099-01-10", preferred_end_date="2099-01-10",
        preferred_start_time=None, preferred_end_time=None, expected_attendance=10,
        accessibility_needs=[], room_layout="theatre", equipment_needed={"equipment": []},
        registration_needs=False, special_requests="",
    )


@pytest.fixture
def world(monkeypatch):
    def setup(status, assign_raises=None, coordinator_id=None):
        db = {"status": status, "coordinator_id": coordinator_id}
        history, assign_calls = [], []

        def conditional_update(event_id, from_status, to_status):
            if db["status"] != from_status:
                return None
            db["status"] = to_status
            return {"id": event_id, "status": to_status}

        def fake_assign(event_id, actor=None):
            assign_calls.append((event_id, actor))
            if assign_raises:
                raise assign_raises
            transitions.transition(event_id, "under_review", actor, expected_from="submitted")
            return {"id": "coord-new"}

        monkeypatch.setattr(transitions, "_db_conditional_update", conditional_update)
        monkeypatch.setattr(transitions, "_db_insert_history", lambda *args: history.append(args[1:]))
        monkeypatch.setattr(service_module, "assign_initial_coordinator", fake_assign)
        class _ReRead:
            """submit_event_request re-reads the submitted sessions (by id)
            after moving them -- return whatever the fake DB now holds."""

            def table(self, name):
                return self

            def select(self, *args):
                return self

            def eq(self, *args):
                return self

            def in_(self, *args):
                return self

            def single(self):
                return self

            def execute(self):
                return SimpleNamespace(
                    data=[{"id": "event-1", "status": db["status"], "coordinator_id": db["coordinator_id"]}]
                )

        monkeypatch.setattr(service_module, "supabase", _ReRead())
        return db, history, assign_calls

    return setup


def test_first_submission_goes_draft_submitted_then_auto_assigns_attributed_to_organiser(world):
    db, history, assign_calls = world("draft")
    service_module.submit_event_request("event-1", _complete_event("draft"))

    assert db["status"] == "under_review"
    assert assign_calls == [("event-1", ORG)]
    assert history == [("draft", "submitted", ORG, None), ("submitted", "under_review", ORG, None)]


def test_resubmission_keeps_same_coordinator_and_returns_to_review(world):
    """rejected -> submitted -> under_review with the SAME coordinator, and
    assign_initial_coordinator (which refuses an assigned event) is never called."""
    db, history, assign_calls = world("rejected", coordinator_id="coord-1")
    service_module.submit_event_request("event-1", _complete_event("rejected", coordinator_id="coord-1"))

    assert db["status"] == "under_review"
    assert assign_calls == []
    assert history == [("rejected", "submitted", ORG, None), ("submitted", "under_review", ORG, None)]


def test_no_coordinator_available_leaves_event_submitted(world):
    db, history, _ = world("draft", assign_raises=NoCoordinatorAvailableError("everyone busy"))
    result = service_module.submit_event_request("event-1", _complete_event("draft"))

    assert result["status"] == "submitted"
    assert db["status"] == "submitted"
    assert history == [("draft", "submitted", ORG, None)]


def test_submit_against_stale_status_is_a_conflict(world):
    """The route authorised `draft`, but the event is now something else:
    nothing is written, and auto-assignment is never attempted."""
    db, history, assign_calls = world("submitted")
    with pytest.raises(TransitionConflictError):
        service_module.submit_event_request("event-1", _complete_event("draft"))
    assert db["status"] == "submitted"
    assert history == []
    assert assign_calls == []


def test_organiser_may_resubmit_a_rejected_request():
    organiser = make_user(["event_organizer"], user_id=ORG)
    assert can(organiser, actions.EVENT_SUBMIT, FakeEvent(organizer_id=ORG, coordinator_id="c", status="rejected"))
    assert can(organiser, actions.EVENT_EDIT, FakeEvent(organizer_id=ORG, coordinator_id="c", status="rejected"))


@pytest.mark.parametrize("status", ["submitted", "under_review", "approved", "planning", "confirmed",
                                    "completed", "cancelled"])
def test_organiser_still_cannot_submit_from_other_statuses(status):
    organiser = make_user(["event_organizer"], user_id=ORG)
    assert not can(organiser, actions.EVENT_SUBMIT, FakeEvent(organizer_id=ORG, status=status))
