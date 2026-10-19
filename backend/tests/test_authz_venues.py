"""
Tests for venue.view / venue.list authz rules (app/authz/rules.py,
wired via app/authz/policy.py). Mirrors the style of the EVENT_LIST
tests in test_authz_policy.py -- both venue actions are role-only, same
shape as event.list/event.create (see rules.py's module docstring on
why role-only actions have no resource to check a relationship against).
"""

from __future__ import annotations

import pytest

from app.authz import actions
from app.authz.policy import authorise, can
from app.shared.errors import AuthorisationError
from tests.factories import make_user


def test_coordinator_allowed_venue_list():
    user = make_user(["event_coordinator"], user_id="coord-1")
    assert can(user, actions.VENUE_LIST) is True


def test_venue_staff_allowed_venue_list():
    user = make_user(["venue_staff"], user_id="staff-1")
    assert can(user, actions.VENUE_LIST) is True


def test_organiser_denied_venue_list():
    """An Event Organizer has no venue-catalogue grant in Sprint 1 --
    the story is written for the Event Coordinator (and, per this
    codebase's own assumption, Venue Staff); nothing asks for organiser
    access to the catalogue."""
    user = make_user(["event_organizer"], user_id="org-1")
    assert can(user, actions.VENUE_LIST) is False
    with pytest.raises(AuthorisationError):
        authorise(user, actions.VENUE_LIST)


def test_attendee_denied_venue_list():
    user = make_user(["attendee"], user_id="att-1")
    assert can(user, actions.VENUE_LIST) is False


def test_coordinator_allowed_venue_view():
    user = make_user(["event_coordinator"], user_id="coord-1")
    assert can(user, actions.VENUE_VIEW) is True


def test_venue_staff_allowed_venue_view():
    user = make_user(["venue_staff"], user_id="staff-1")
    assert can(user, actions.VENUE_VIEW) is True


def test_organiser_denied_venue_view():
    user = make_user(["event_organizer"], user_id="org-1")
    assert can(user, actions.VENUE_VIEW) is False
    with pytest.raises(AuthorisationError):
        authorise(user, actions.VENUE_VIEW)


def test_multi_role_union_grants_venue_list():
    """Structural multi-role union (see rules.py's module docstring):
    a user holding event_organizer (no grant) AND event_coordinator (a
    grant) gets access through the coordinator path -- there's no
    special case needed for holding an unrelated extra role."""
    user = make_user(["event_organizer", "event_coordinator"], user_id="both-1")
    assert can(user, actions.VENUE_LIST) is True


# -- venue.manage / venue.block (Josiah, Sprint 3) --------------------------
# Role-only, venue_staff-only -- exact shape of ROOM_LAYOUT_MANAGE's own
# tests (test_room_layouts.py), the closest existing precedent.


@pytest.mark.parametrize("action", [actions.VENUE_MANAGE, actions.VENUE_BLOCK])
def test_venue_staff_allowed_manage_and_block(action):
    user = make_user(["venue_staff"], user_id="staff-1")
    assert can(user, action) is True


@pytest.mark.parametrize("action", [actions.VENUE_MANAGE, actions.VENUE_BLOCK])
@pytest.mark.parametrize("role", ["event_organizer", "event_coordinator", "attendee", "technical_support_staff"])
def test_every_other_role_denied_manage_and_block(action, role):
    user = make_user([role], user_id="user-1")
    assert can(user, action) is False
    with pytest.raises(AuthorisationError):
        authorise(user, action)


def test_multi_role_union_grants_venue_manage():
    user = make_user(["event_coordinator", "venue_staff"], user_id="both-1")
    assert can(user, actions.VENUE_MANAGE) is True
    assert can(user, actions.VENUE_BLOCK) is True
