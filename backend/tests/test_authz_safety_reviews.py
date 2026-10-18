"""
Authorisation rules for the Operational Feasibility Check (Week 7 change #6):
safety_review.submit / list / view / approve / reject / request_changes, and
the confirm and cancel windows that changed with it. Pure rule tests, no
app, no database.
"""

from __future__ import annotations

import pytest

from app.authz import actions
from app.authz.policy import authorise, can
from app.shared.errors import AuthorisationError, NotFoundError
from tests.factories import FakeEvent, FakeSafetyReview, make_user

ALL_EVENT_STATUSES = [
    "draft",
    "submitted",
    "under_review",
    "approved",
    "planning",
    "safety_review",
    "confirmed",
    "completed",
    "cancelled",
    "rejected",
]
DECISIONS = [actions.SAFETY_REVIEW_APPROVE, actions.SAFETY_REVIEW_REJECT, actions.SAFETY_REVIEW_REQUEST_CHANGES]
OTHER_ROLES = [
    "event_organizer",
    "event_coordinator",
    "event_coordinator_lead",
    "venue_staff",
    "technical_support_staff",
    "attendee",
]


def _officer(user_id="officer-1"):
    return make_user(["safety_officer"], user_id=user_id)


def _coordinator(user_id="coord-1"):
    return make_user(["event_coordinator"], user_id=user_id)


def _event(status, coordinator_id="coord-1"):
    return FakeEvent(id="event-1", organizer_id="org-1", coordinator_id=coordinator_id, status=status)


# -- submit ------------------------------------------------------------------


def test_assigned_coordinator_may_submit_a_planning_session():
    assert can(_coordinator(), actions.SAFETY_REVIEW_SUBMIT, _event("planning"))


@pytest.mark.parametrize("status", [s for s in ALL_EVENT_STATUSES if s != "planning"])
def test_submit_refused_outside_planning_with_a_403(status):
    with pytest.raises(AuthorisationError):
        authorise(_coordinator(), actions.SAFETY_REVIEW_SUBMIT, _event(status))


def test_submit_by_another_coordinator_is_a_404():
    with pytest.raises(NotFoundError):
        authorise(_coordinator("someone-else"), actions.SAFETY_REVIEW_SUBMIT, _event("planning"))


@pytest.mark.parametrize("role", ["event_organizer", "event_coordinator_lead", "safety_officer", "venue_staff"])
def test_only_the_coordinator_submits(role):
    user = make_user([role], user_id="org-1" if role == "event_organizer" else "u-1")
    assert not can(user, actions.SAFETY_REVIEW_SUBMIT, _event("planning"))


# -- list / view ---------------------------------------------------------------


def test_safety_officer_may_list_and_view():
    assert can(_officer(), actions.SAFETY_REVIEW_LIST)
    assert can(_officer(), actions.SAFETY_REVIEW_VIEW, FakeSafetyReview(status="approved"))


@pytest.mark.parametrize("role", OTHER_ROLES)
def test_other_roles_cannot_list(role):
    with pytest.raises(AuthorisationError):
        authorise(make_user([role]), actions.SAFETY_REVIEW_LIST)


@pytest.mark.parametrize("role", OTHER_ROLES)
def test_other_roles_get_a_404_viewing_a_review(role):
    with pytest.raises(NotFoundError):
        authorise(make_user([role]), actions.SAFETY_REVIEW_VIEW, FakeSafetyReview())


# -- decisions -----------------------------------------------------------------


@pytest.mark.parametrize("action", DECISIONS)
def test_any_safety_officer_may_decide_a_pending_review(action):
    """No assignment step: every Safety Officer may decide any pending review."""
    assert can(_officer("officer-1"), action, FakeSafetyReview())
    assert can(_officer("officer-2"), action, FakeSafetyReview())


@pytest.mark.parametrize("action", DECISIONS)
@pytest.mark.parametrize("status", ["approved", "rejected", "changes_requested"])
def test_a_decided_review_cannot_be_decided_again(action, status):
    with pytest.raises(AuthorisationError):
        authorise(_officer(), action, FakeSafetyReview(status=status))


@pytest.mark.parametrize("action", DECISIONS)
@pytest.mark.parametrize("role", OTHER_ROLES)
def test_nobody_else_decides_and_gets_a_404(action, role):
    with pytest.raises(NotFoundError):
        authorise(make_user([role]), action, FakeSafetyReview())


def test_multi_role_officer_and_coordinator_gets_both():
    user = make_user(["event_coordinator", "safety_officer"], user_id="coord-1")
    assert can(user, actions.SAFETY_REVIEW_SUBMIT, _event("planning"))
    assert can(user, actions.SAFETY_REVIEW_APPROVE, FakeSafetyReview())


# -- confirm and cancel windows ------------------------------------------------


def test_confirm_is_from_safety_review_only():
    for status in ALL_EVENT_STATUSES:
        assert can(_coordinator(), actions.EVENT_CONFIRM, _event(status)) is (status == "safety_review"), status


def test_a_session_in_safety_review_can_still_be_cancelled():
    assert can(_coordinator(), actions.EVENT_CANCEL, _event("safety_review"))


def test_change_requests_stay_open_during_safety_review():
    organiser = make_user(["event_organizer"], user_id="org-1")
    assert can(organiser, actions.EVENT_REQUEST_CHANGE, _event("safety_review"))
    assert can(_coordinator(), actions.EVENT_REVIEW_CHANGE, _event("safety_review"))
