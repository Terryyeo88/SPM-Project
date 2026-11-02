"""
Authorisation rules for notifications (IS-69): notification.list /
mark_read / mark_all_read. Pure rule tests, no app, no database.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.authz import actions
from app.authz.policy import authorise, can
from app.shared.errors import NotFoundError
from tests.factories import make_user

# Every app_role (20260911120000_init_users_events.sql and the role
# migrations since), a multi-role user, and no role at all.
EVERY_ROLE_SET = [
    [],
    ["event_organizer"],
    ["event_coordinator"],
    ["event_coordinator_lead"],
    ["venue_staff"],
    ["technical_support_staff"],
    ["attendee"],
    ["safety_officer"],
    ["event_coordinator", "venue_staff"],
]


def _notification(recipient_id="me"):
    return SimpleNamespace(id="n-1", recipient_id=recipient_id)


@pytest.mark.parametrize("roles", EVERY_ROLE_SET)
@pytest.mark.parametrize("action", [actions.NOTIFICATION_LIST, actions.NOTIFICATION_MARK_ALL_READ])
def test_every_authenticated_user_may_list_and_mark_all_their_own(roles, action):
    assert can(make_user(roles, user_id="me"), action)


@pytest.mark.parametrize("roles", EVERY_ROLE_SET)
def test_the_recipient_may_mark_their_notification_read(roles):
    assert can(make_user(roles, user_id="me"), actions.NOTIFICATION_MARK_READ, _notification("me"))


@pytest.mark.parametrize("roles", EVERY_ROLE_SET)
def test_anyone_elses_notification_is_a_404_whatever_their_role(roles):
    """No relationship to it: a 403 would confirm the id exists."""
    with pytest.raises(NotFoundError):
        authorise(make_user(roles, user_id="me"), actions.NOTIFICATION_MARK_READ, _notification("someone-else"))
