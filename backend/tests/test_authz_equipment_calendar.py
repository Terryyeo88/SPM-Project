"""
Tests for the equipment.calendar_view authz rule (IS-47). Mirrors
test_authz_venue_calendar.py, with the role matrix IS-47 asks for:
Technical Support Staff only, everyone else a 404 (DENY_NOT_FOUND), not
the venue calendar's 403.
"""

from __future__ import annotations

import pytest

from app.authz import actions
from app.authz.policy import authorise, can
from app.shared.errors import NotFoundError
from tests.factories import make_user


def test_technical_staff_allowed_calendar_view():
    user = make_user(["technical_support_staff"], user_id="tech-1")
    assert can(user, actions.EQUIPMENT_CALENDAR_VIEW) is True


@pytest.mark.parametrize(
    "role", ["event_coordinator", "event_coordinator_lead", "event_organizer", "venue_staff", "attendee"]
)
def test_every_other_role_denied_calendar_view(role):
    user = make_user([role], user_id="u-1")
    assert can(user, actions.EQUIPMENT_CALENDAR_VIEW) is False


@pytest.mark.parametrize("role", ["event_coordinator", "venue_staff", "attendee"])
def test_denial_is_a_404_not_a_403(role):
    user = make_user([role], user_id="u-1")
    with pytest.raises(NotFoundError):
        authorise(user, actions.EQUIPMENT_CALENDAR_VIEW)


def test_no_roles_denied():
    assert can(make_user([], user_id="u-1"), actions.EQUIPMENT_CALENDAR_VIEW) is False


def test_multi_role_union_grants_calendar_view():
    user = make_user(["event_coordinator", "technical_support_staff"], user_id="u-1")
    assert can(user, actions.EQUIPMENT_CALENDAR_VIEW) is True
