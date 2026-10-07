"""
Tests for venue.calendar_view authz rule (View Venue Availability
Calendar, Nawaz, Sprint 2, IS-11). Mirrors test_authz_venues.py exactly
-- rule_venue_calendar_view is defined as a straight delegate to
rule_venue_list (see rules.py), so the same coordinator/venue_staff
pair applies.
"""

from __future__ import annotations

import pytest

from app.authz import actions
from app.authz.policy import authorise, can
from app.shared.errors import AuthorisationError
from tests.factories import make_user


def test_coordinator_allowed_calendar_view():
    user = make_user(["event_coordinator"], user_id="coord-1")
    assert can(user, actions.VENUE_CALENDAR_VIEW) is True


def test_venue_staff_allowed_calendar_view():
    user = make_user(["venue_staff"], user_id="staff-1")
    assert can(user, actions.VENUE_CALENDAR_VIEW) is True


def test_organiser_denied_calendar_view():
    user = make_user(["event_organizer"], user_id="org-1")
    assert can(user, actions.VENUE_CALENDAR_VIEW) is False
    with pytest.raises(AuthorisationError):
        authorise(user, actions.VENUE_CALENDAR_VIEW)


def test_attendee_denied_calendar_view():
    user = make_user(["attendee"], user_id="att-1")
    assert can(user, actions.VENUE_CALENDAR_VIEW) is False


def test_multi_role_union_grants_calendar_view():
    user = make_user(["event_organizer", "venue_staff"], user_id="both-1")
    assert can(user, actions.VENUE_CALENDAR_VIEW) is True
