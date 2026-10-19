"""
Tests for the equipment_request.accept rule (Accept an equipment request
and reserve stock, Nawaz, Sprint 3, IS-19). Pure rule tests, same style as
test_authz_venue_bookings.py.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.authz import actions
from app.authz.policy import authorise, can
from app.shared.errors import AuthorisationError, NotFoundError
from tests.factories import make_user


def _request(status="pending", event_status="planning", requested_by="coord-1"):
    return SimpleNamespace(id="req-1", requested_by=requested_by, status=status, event_status=event_status)


def test_technical_staff_can_accept_a_pending_request_on_a_planning_event():
    user = make_user(["technical_support_staff"])
    assert can(user, actions.EQUIPMENT_REQUEST_ACCEPT, _request()) is True


@pytest.mark.parametrize("status", ["confirmed", "rejected"])
def test_only_a_pending_request_can_be_accepted(status):
    """AC: "Only requests in a 'pending' status can be accepted"."""
    user = make_user(["technical_support_staff"])
    assert can(user, actions.EQUIPMENT_REQUEST_ACCEPT, _request(status=status)) is False
    with pytest.raises(AuthorisationError):
        authorise(user, actions.EQUIPMENT_REQUEST_ACCEPT, _request(status=status))


@pytest.mark.parametrize("event_status", ["cancelled", "approved", "safety_review", "confirmed", "completed", None])
def test_a_request_is_only_accepted_while_its_event_is_in_planning(event_status):
    user = make_user(["technical_support_staff"])
    assert can(user, actions.EQUIPMENT_REQUEST_ACCEPT, _request(event_status=event_status)) is False


@pytest.mark.parametrize("role", ["event_coordinator", "event_organizer", "venue_staff", "attendee"])
def test_other_roles_cannot_accept_and_get_a_404(role):
    user = make_user([role], user_id="coord-1")
    assert can(user, actions.EQUIPMENT_REQUEST_ACCEPT, _request()) is False
    with pytest.raises(NotFoundError):
        authorise(user, actions.EQUIPMENT_REQUEST_ACCEPT, _request())
