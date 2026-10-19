"""
Tests for the equipment_change.* rules (Update quantity on an existing
equipment reservation, Nawaz, Sprint 3, IS-43). Pure rule tests.
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


def _change(status="pending", event_status="planning"):
    return SimpleNamespace(id="chg-1", status=status, event_status=event_status)


# -- create (the coordinator's ask) -------------------------------------------


def test_the_coordinator_who_raised_a_confirmed_request_can_ask_for_a_change():
    user = make_user(["event_coordinator"], user_id="coord-1")
    assert can(user, actions.EQUIPMENT_CHANGE_CREATE, _request()) is True


@pytest.mark.parametrize("event_status", ["planning", "safety_review", "confirmed"])
def test_a_change_can_be_asked_for_while_the_event_is_live(event_status):
    user = make_user(["event_coordinator"], user_id="coord-1")
    assert can(user, actions.EQUIPMENT_CHANGE_CREATE, _request(event_status=event_status)) is True


@pytest.mark.parametrize("event_status", ["cancelled", "completed", "rejected", "draft", None])
def test_no_change_once_the_event_is_over_or_cancelled(event_status):
    user = make_user(["event_coordinator"], user_id="coord-1")
    assert can(user, actions.EQUIPMENT_CHANGE_CREATE, _request(event_status=event_status)) is False


@pytest.mark.parametrize("status", ["pending", "rejected"])
def test_only_a_confirmed_request_has_reservations_to_change(status):
    user = make_user(["event_coordinator"], user_id="coord-1")
    with pytest.raises(AuthorisationError):
        authorise(user, actions.EQUIPMENT_CHANGE_CREATE, _request(status=status))


def test_another_coordinator_gets_a_404():
    user = make_user(["event_coordinator"], user_id="someone-else")
    with pytest.raises(NotFoundError):
        authorise(user, actions.EQUIPMENT_CHANGE_CREATE, _request())


def test_technical_staff_cannot_ask_for_a_change():
    user = make_user(["technical_support_staff"], user_id="tech-1")
    with pytest.raises(NotFoundError):
        authorise(user, actions.EQUIPMENT_CHANGE_CREATE, _request())


# -- list / accept / reject (Technical Support) -------------------------------


def test_only_technical_staff_see_the_queue():
    assert can(make_user(["technical_support_staff"]), actions.EQUIPMENT_CHANGE_LIST, None) is True
    with pytest.raises(NotFoundError):
        authorise(make_user(["event_coordinator"]), actions.EQUIPMENT_CHANGE_LIST, None)


@pytest.mark.parametrize("action", [actions.EQUIPMENT_CHANGE_ACCEPT, actions.EQUIPMENT_CHANGE_REJECT])
def test_technical_staff_decide_a_pending_change(action):
    assert can(make_user(["technical_support_staff"]), action, _change()) is True


@pytest.mark.parametrize("action", [actions.EQUIPMENT_CHANGE_ACCEPT, actions.EQUIPMENT_CHANGE_REJECT])
@pytest.mark.parametrize("status", ["accepted", "rejected"])
def test_a_decided_change_cannot_be_decided_again(action, status):
    with pytest.raises(AuthorisationError):
        authorise(make_user(["technical_support_staff"]), action, _change(status=status))


@pytest.mark.parametrize("action", [actions.EQUIPMENT_CHANGE_ACCEPT, actions.EQUIPMENT_CHANGE_REJECT])
@pytest.mark.parametrize("role", ["event_coordinator", "event_organizer", "venue_staff", "attendee"])
def test_other_roles_cannot_decide_and_get_a_404(action, role):
    with pytest.raises(NotFoundError):
        authorise(make_user([role]), action, _change())


def test_accepting_needs_a_live_event_but_rejecting_does_not():
    tech = make_user(["technical_support_staff"])
    cancelled = _change(event_status="cancelled")
    assert can(tech, actions.EQUIPMENT_CHANGE_ACCEPT, cancelled) is False
    assert can(tech, actions.EQUIPMENT_CHANGE_REJECT, cancelled) is True
