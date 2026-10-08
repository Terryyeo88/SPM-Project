"""
Tests for the equipment.* / equipment_request.* authz rules (Check
Equipment Availability, Nawaz, Sprint 2, IS-18). Technical Support Staff
are the story's actor; a coordinator can additionally see requests they
raised ("Submitted equipment request is viewable later").
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.authz import actions
from app.authz.policy import authorise, can
from app.shared.errors import AuthorisationError, NotFoundError
from tests.factories import make_user


@dataclass(frozen=True)
class FakeEquipmentRequest:
    id: str = "req-1"
    requested_by: str = "coord-1"
    status: str = "pending"


# -- equipment.list / equipment.view -----------------------------------------


@pytest.mark.parametrize("action", [actions.EQUIPMENT_LIST, actions.EQUIPMENT_VIEW])
def test_technical_staff_allowed_equipment_records(action):
    assert can(make_user(["technical_support_staff"]), action) is True


@pytest.mark.parametrize("action", [actions.EQUIPMENT_LIST, actions.EQUIPMENT_VIEW])
@pytest.mark.parametrize("role", ["event_organizer", "event_coordinator", "venue_staff", "attendee"])
def test_other_roles_denied_equipment_records(role, action):
    user = make_user([role])
    assert can(user, action) is False
    with pytest.raises(AuthorisationError):
        authorise(user, action)


# -- equipment_request.list --------------------------------------------------


@pytest.mark.parametrize("role", ["technical_support_staff", "event_coordinator"])
def test_staff_and_coordinator_allowed_request_list(role):
    assert can(make_user([role]), actions.EQUIPMENT_REQUEST_LIST) is True


@pytest.mark.parametrize("role", ["event_organizer", "venue_staff", "attendee"])
def test_other_roles_denied_request_list(role):
    assert can(make_user([role]), actions.EQUIPMENT_REQUEST_LIST) is False


# -- equipment_request.view --------------------------------------------------


def test_technical_staff_can_view_any_request():
    user = make_user(["technical_support_staff"], user_id="tech-1")
    assert can(user, actions.EQUIPMENT_REQUEST_VIEW, FakeEquipmentRequest(requested_by="someone-else")) is True


def test_coordinator_can_view_their_own_request():
    user = make_user(["event_coordinator"], user_id="coord-1")
    assert can(user, actions.EQUIPMENT_REQUEST_VIEW, FakeEquipmentRequest(requested_by="coord-1")) is True


def test_coordinator_cannot_view_someone_elses_request_and_gets_404():
    user = make_user(["event_coordinator"], user_id="coord-2")
    request = FakeEquipmentRequest(requested_by="coord-1")
    assert can(user, actions.EQUIPMENT_REQUEST_VIEW, request) is False
    with pytest.raises(NotFoundError):
        authorise(user, actions.EQUIPMENT_REQUEST_VIEW, request)


@pytest.mark.parametrize("role", ["event_organizer", "venue_staff", "attendee"])
def test_other_roles_get_404_on_request_view(role):
    with pytest.raises(NotFoundError):
        authorise(make_user([role]), actions.EQUIPMENT_REQUEST_VIEW, FakeEquipmentRequest())


# -- equipment_request.check_availability ------------------------------------


def test_technical_staff_can_check_availability():
    user = make_user(["technical_support_staff"])
    assert can(user, actions.EQUIPMENT_REQUEST_CHECK_AVAILABILITY, FakeEquipmentRequest()) is True


def test_requesting_coordinator_cannot_check_availability():
    # The check shows which OTHER events hold equipment, so it is not
    # opened to the requester.
    user = make_user(["event_coordinator"], user_id="coord-1")
    request = FakeEquipmentRequest(requested_by="coord-1")
    assert can(user, actions.EQUIPMENT_REQUEST_CHECK_AVAILABILITY, request) is False
    with pytest.raises(NotFoundError):
        authorise(user, actions.EQUIPMENT_REQUEST_CHECK_AVAILABILITY, request)


@pytest.mark.parametrize("status", ["pending", "confirmed", "rejected"])
def test_availability_check_not_gated_on_request_status(status):
    user = make_user(["technical_support_staff"])
    assert can(user, actions.EQUIPMENT_REQUEST_CHECK_AVAILABILITY, FakeEquipmentRequest(status=status)) is True


def test_multi_role_union_grants_access():
    user = make_user(["event_organizer", "technical_support_staff"])
    assert can(user, actions.EQUIPMENT_LIST) is True
    assert can(user, actions.EQUIPMENT_REQUEST_CHECK_AVAILABILITY, FakeEquipmentRequest()) is True
