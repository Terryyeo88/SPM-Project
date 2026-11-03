"""
Tests for the equipment_request.cancel rule (the coordinator cancelling an
equipment request, Nawaz, Sprint 3). Pure rule tests.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.authz import actions
from app.authz.policy import authorise, can
from app.shared.errors import AuthorisationError, NotFoundError
from tests.factories import make_user


def _request(status="confirmed", event_status="planning", requested_by="coord-1"):
    return SimpleNamespace(id="req-1", requested_by=requested_by, status=status, event_status=event_status)


@pytest.mark.parametrize("status", ["pending", "confirmed"])
def test_the_coordinator_who_raised_a_live_request_can_cancel_it(status):
    user = make_user(["event_coordinator"], user_id="coord-1")
    assert can(user, actions.EQUIPMENT_REQUEST_CANCEL, _request(status=status)) is True


@pytest.mark.parametrize("event_status", ["planning", "safety_review", "confirmed"])
def test_cancelling_works_while_the_event_is_live(event_status):
    user = make_user(["event_coordinator"], user_id="coord-1")
    assert can(user, actions.EQUIPMENT_REQUEST_CANCEL, _request(event_status=event_status)) is True


@pytest.mark.parametrize("event_status", ["cancelled", "completed", "rejected", "draft", None])
def test_no_cancelling_once_the_event_is_over_or_cancelled(event_status):
    user = make_user(["event_coordinator"], user_id="coord-1")
    assert can(user, actions.EQUIPMENT_REQUEST_CANCEL, _request(event_status=event_status)) is False


@pytest.mark.parametrize("status", ["rejected", "cancelled"])
def test_a_request_that_is_already_over_cannot_be_cancelled(status):
    user = make_user(["event_coordinator"], user_id="coord-1")
    with pytest.raises(AuthorisationError):
        authorise(user, actions.EQUIPMENT_REQUEST_CANCEL, _request(status=status))


def test_another_coordinator_gets_a_404():
    user = make_user(["event_coordinator"], user_id="someone-else")
    with pytest.raises(NotFoundError):
        authorise(user, actions.EQUIPMENT_REQUEST_CANCEL, _request())


@pytest.mark.parametrize("role", ["technical_support_staff", "event_organizer", "venue_staff", "attendee"])
def test_other_roles_get_a_404(role):
    user = make_user([role], user_id="coord-1")
    with pytest.raises(NotFoundError):
        authorise(user, actions.EQUIPMENT_REQUEST_CANCEL, _request())


def test_a_change_on_a_cancelled_request_cannot_be_accepted_but_can_be_rejected():
    """IS-43 interplay: a cancelled request has nothing left to change."""
    tech = make_user(["technical_support_staff"])
    change = SimpleNamespace(id="chg-1", status="pending", event_status="planning", request_status="cancelled")
    assert can(tech, actions.EQUIPMENT_CHANGE_ACCEPT, change) is False
    assert can(tech, actions.EQUIPMENT_CHANGE_REJECT, change) is True
