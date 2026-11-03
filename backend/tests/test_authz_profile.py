"""
Authorisation rule for IS-68: profile.edit_own. Pure rule tests, no app,
no database. The rule allows every authenticated caller because PATCH
/me/profile cannot name any profile but the caller's own -- what keeps it
to their own is the service's scope (test_profile_service.py).
"""

from __future__ import annotations

import pytest

from app.authz import actions
from app.authz.policy import _RULES, can
from tests.factories import make_user


@pytest.mark.parametrize(
    "roles",
    [[], ["attendee"], ["event_organizer"], ["event_coordinator"], ["event_coordinator_lead"], ["venue_staff"],
     ["technical_support_staff"], ["safety_officer"], ["event_coordinator", "venue_staff"]],
)
def test_every_authenticated_user_may_edit_their_own_profile(roles):
    assert can(make_user(roles, user_id="me"), actions.PROFILE_EDIT_OWN)


def test_profile_edit_own_is_wired_into_the_policy():
    """Deny-by-default would turn a forgotten _RULES entry into a 403."""
    assert actions.PROFILE_EDIT_OWN in _RULES
