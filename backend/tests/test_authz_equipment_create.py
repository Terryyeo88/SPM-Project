"""
Tests for equipment_request.create and equipment_type.list (Record
Equipment Request for Event, Nawaz, Sprint 3, IS-17). Pure rule tests,
same style as test_authz_venue_bookings.py.
"""

from __future__ import annotations

import pytest

from app.authz import actions
from app.authz.policy import authorise, can
from app.shared.errors import AuthorisationError, NotFoundError
from tests.factories import FakeEvent, make_user

# -- equipment_request.create ------------------------------------------------


def test_assigned_coordinator_can_create_when_event_planning():
    user = make_user(["event_coordinator"], user_id="coord-1")
    event = FakeEvent(id="event-1", coordinator_id="coord-1", status="planning")
    assert can(user, actions.EQUIPMENT_REQUEST_CREATE, event) is True


@pytest.mark.parametrize(
    "status",
    ["draft", "submitted", "under_review", "approved", "rejected", "safety_review", "confirmed", "cancelled"],
)
def test_assigned_coordinator_cannot_create_outside_planning(status):
    """Aaralyn's IS-9 note: equipment requests need planning, like venues."""
    user = make_user(["event_coordinator"], user_id="coord-1")
    event = FakeEvent(id="event-1", coordinator_id="coord-1", status=status)
    assert can(user, actions.EQUIPMENT_REQUEST_CREATE, event) is False
    with pytest.raises(AuthorisationError):
        authorise(user, actions.EQUIPMENT_REQUEST_CREATE, event)


def test_coordinator_not_assigned_gets_404_not_403():
    user = make_user(["event_coordinator"], user_id="someone-else")
    event = FakeEvent(id="event-1", coordinator_id="coord-1", status="planning")
    assert can(user, actions.EQUIPMENT_REQUEST_CREATE, event) is False
    with pytest.raises(NotFoundError):
        authorise(user, actions.EQUIPMENT_REQUEST_CREATE, event)


@pytest.mark.parametrize("role", ["event_organizer", "venue_staff", "technical_support_staff", "attendee"])
def test_other_roles_cannot_create(role):
    user = make_user([role], user_id="coord-1")
    event = FakeEvent(id="event-1", coordinator_id="coord-1", organizer_id="coord-1", status="planning")
    assert can(user, actions.EQUIPMENT_REQUEST_CREATE, event) is False


# -- equipment_type.list -----------------------------------------------------


@pytest.mark.parametrize("role", ["event_coordinator", "technical_support_staff"])
def test_coordinator_and_technical_staff_can_list_types(role):
    assert can(make_user([role]), actions.EQUIPMENT_TYPE_LIST, None) is True


@pytest.mark.parametrize("role", ["event_organizer", "venue_staff", "attendee"])
def test_other_roles_cannot_list_types(role):
    user = make_user([role])
    assert can(user, actions.EQUIPMENT_TYPE_LIST, None) is False
    with pytest.raises(AuthorisationError):
        authorise(user, actions.EQUIPMENT_TYPE_LIST, None)
