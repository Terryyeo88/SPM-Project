"""
Tests for the venue_booking.* authz rules (app/authz/rules.py, wired via
app/authz/policy.py) -- create/view/list/approve/reject for the Venue
Booking Request / Approval stories (Josiah, Sprint 2).

Pure rule tests, same style as test_authz_venues.py / the EVENT_APPROVE
section of test_authz_policy.py: plain FakeEvent/FakeVenueBooking objects,
no Flask, no database.
"""

from __future__ import annotations

import pytest

from app.authz import actions
from app.authz.policy import authorise, can
from app.shared.errors import AuthorisationError, NotFoundError
from tests.factories import FakeEvent, FakeVenueBooking, make_user

# -- venue_booking.create --------------------------------------------------


def test_assigned_coordinator_can_create_when_event_approved():
    user = make_user(["event_coordinator"], user_id="coord-1")
    event = FakeEvent(id="event-1", coordinator_id="coord-1", status="approved")
    assert can(user, actions.VENUE_BOOKING_CREATE, event) is True


def test_assigned_coordinator_can_create_when_event_already_planning():
    user = make_user(["event_coordinator"], user_id="coord-1")
    event = FakeEvent(id="event-1", coordinator_id="coord-1", status="planning")
    assert can(user, actions.VENUE_BOOKING_CREATE, event) is True


@pytest.mark.parametrize("status", ["draft", "submitted", "under_review", "rejected", "confirmed"])
def test_assigned_coordinator_cannot_create_outside_approved_or_planning(status):
    user = make_user(["event_coordinator"], user_id="coord-1")
    event = FakeEvent(id="event-1", coordinator_id="coord-1", status=status)
    assert can(user, actions.VENUE_BOOKING_CREATE, event) is False
    with pytest.raises(AuthorisationError):
        authorise(user, actions.VENUE_BOOKING_CREATE, event)


def test_coordinator_not_assigned_gets_404_not_403():
    """Not the event's own coordinator -- no qualifying relationship at
    all, so this must be DENY_NOT_FOUND (404), not DENY_FORBIDDEN (403),
    same as rule_event_approve's own not-assigned case."""
    user = make_user(["event_coordinator"], user_id="someone-else")
    event = FakeEvent(id="event-1", coordinator_id="coord-1", status="approved")
    assert can(user, actions.VENUE_BOOKING_CREATE, event) is False
    with pytest.raises(NotFoundError):
        authorise(user, actions.VENUE_BOOKING_CREATE, event)


def test_organiser_cannot_create_even_on_their_own_event():
    user = make_user(["event_organizer"], user_id="org-1")
    event = FakeEvent(id="event-1", organizer_id="org-1", coordinator_id="coord-1", status="approved")
    assert can(user, actions.VENUE_BOOKING_CREATE, event) is False


def test_venue_staff_cannot_create():
    user = make_user(["venue_staff"], user_id="staff-1")
    event = FakeEvent(id="event-1", coordinator_id="staff-1", status="approved")
    assert can(user, actions.VENUE_BOOKING_CREATE, event) is False


# -- venue_booking.view -----------------------------------------------------


def test_requesting_coordinator_can_view_their_own_booking():
    user = make_user(["event_coordinator"], user_id="coord-1")
    booking = FakeVenueBooking(requested_by="coord-1")
    assert can(user, actions.VENUE_BOOKING_VIEW, booking) is True


def test_coordinator_cannot_view_someone_elses_booking():
    user = make_user(["event_coordinator"], user_id="coord-2")
    booking = FakeVenueBooking(requested_by="coord-1")
    assert can(user, actions.VENUE_BOOKING_VIEW, booking) is False
    with pytest.raises(NotFoundError):
        authorise(user, actions.VENUE_BOOKING_VIEW, booking)


def test_any_venue_staff_can_view_any_booking():
    """No per-venue-staff-assignment table exists -- see
    rule_venue_booking_view's own comment and docs/open-questions.md."""
    user = make_user(["venue_staff"], user_id="staff-1")
    booking = FakeVenueBooking(requested_by="coord-1")
    assert can(user, actions.VENUE_BOOKING_VIEW, booking) is True


# -- venue_booking.list (role-only) -----------------------------------------


def test_coordinator_allowed_venue_booking_list():
    assert can(make_user(["event_coordinator"]), actions.VENUE_BOOKING_LIST) is True


def test_venue_staff_allowed_venue_booking_list():
    assert can(make_user(["venue_staff"]), actions.VENUE_BOOKING_LIST) is True


def test_attendee_denied_venue_booking_list():
    assert can(make_user(["attendee"]), actions.VENUE_BOOKING_LIST) is False


# -- venue_booking.approve / venue_booking.reject ---------------------------


@pytest.mark.parametrize("action", [actions.VENUE_BOOKING_APPROVE, actions.VENUE_BOOKING_REJECT])
def test_venue_staff_can_decide_a_pending_booking(action):
    user = make_user(["venue_staff"], user_id="staff-1")
    booking = FakeVenueBooking(status="pending")
    assert can(user, action, booking) is True


@pytest.mark.parametrize("action", [actions.VENUE_BOOKING_APPROVE, actions.VENUE_BOOKING_REJECT])
@pytest.mark.parametrize("status", ["confirmed", "rejected"])
def test_venue_staff_cannot_redecide_an_already_decided_booking(action, status):
    """DENY_FORBIDDEN (403), not 404 -- venue_staff has a qualifying
    relationship (the role), it's just too late to act."""
    user = make_user(["venue_staff"], user_id="staff-1")
    booking = FakeVenueBooking(status=status)
    assert can(user, action, booking) is False
    with pytest.raises(AuthorisationError):
        authorise(user, action, booking)


@pytest.mark.parametrize("action", [actions.VENUE_BOOKING_APPROVE, actions.VENUE_BOOKING_REJECT])
def test_requesting_coordinator_cannot_decide_their_own_booking(action):
    """DENY_NOT_FOUND (404) -- a coordinator has no qualifying
    relationship for this action at all, even on their own request:
    deciding is venue_staff's action, not theirs."""
    user = make_user(["event_coordinator"], user_id="coord-1")
    booking = FakeVenueBooking(requested_by="coord-1", status="pending")
    assert can(user, action, booking) is False
    with pytest.raises(NotFoundError):
        authorise(user, action, booking)


def test_multi_role_union_grants_venue_booking_create():
    """Structural multi-role union (see rules.py's module docstring): a
    user holding venue_staff (no create grant) AND event_coordinator
    assigned to the event (a grant) gets access through the coordinator
    path."""
    user = make_user(["venue_staff", "event_coordinator"], user_id="both-1")
    event = FakeEvent(id="event-1", coordinator_id="both-1", status="approved")
    assert can(user, actions.VENUE_BOOKING_CREATE, event) is True
