"""
Tests for the equipment_request.reject rule (Get warned and reject when the
requested quantity exceeds availability, Nawaz, Sprint 3, IS-41).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.authz import actions
from app.authz.policy import authorise, can
from app.shared.errors import AuthorisationError, NotFoundError
from tests.factories import make_user


def _request(status="pending", event_status="planning"):
    return SimpleNamespace(id="req-1", requested_by="coord-1", status=status, event_status=event_status)


def test_technical_staff_can_reject_a_pending_request():
    user = make_user(["technical_support_staff"])
    assert can(user, actions.EQUIPMENT_REQUEST_REJECT, _request()) is True


@pytest.mark.parametrize("event_status", ["cancelled", "approved", "completed", None])
def test_rejecting_does_not_depend_on_the_event_status(event_status):
    """Unlike accept: a pending request left on a cancelled event must still
    be clearable, and rejecting takes no stock."""
    user = make_user(["technical_support_staff"])
    assert can(user, actions.EQUIPMENT_REQUEST_REJECT, _request(event_status=event_status)) is True


@pytest.mark.parametrize("status", ["confirmed", "rejected"])
def test_only_a_pending_request_can_be_rejected(status):
    user = make_user(["technical_support_staff"])
    assert can(user, actions.EQUIPMENT_REQUEST_REJECT, _request(status=status)) is False
    with pytest.raises(AuthorisationError):
        authorise(user, actions.EQUIPMENT_REQUEST_REJECT, _request(status=status))


@pytest.mark.parametrize("role", ["event_coordinator", "event_organizer", "venue_staff", "attendee"])
def test_other_roles_cannot_reject_and_get_a_404(role):
    user = make_user([role], user_id="coord-1")
    assert can(user, actions.EQUIPMENT_REQUEST_REJECT, _request()) is False
    with pytest.raises(NotFoundError):
        authorise(user, actions.EQUIPMENT_REQUEST_REJECT, _request())
