"""
Tests for app.authz.policy / app.authz.rules -- named after the
acceptance criteria they prove, weighted toward denials because that's
what the criteria mostly specify. No database, no network, no Flask --
rules.py is pure, so these call can()/authorise() directly against
FakeEvent/make_user test doubles (tests/factories.py). See
docs/traceability.md for the full criterion -> test mapping.
"""

from __future__ import annotations

import pytest

from app.authz import actions
from app.authz.policy import authorise, can
from app.shared.errors import AuthorisationError, NotFoundError
from tests.factories import FakeEvent, make_user

# -- event.view ---------------------------------------------------------


def test_organiser_denied_on_another_organisers_event():
    user = make_user(["event_organizer"], user_id="org-1")
    event = FakeEvent(organizer_id="org-2", status="submitted")
    assert can(user, actions.EVENT_VIEW, event) is False
    with pytest.raises(NotFoundError):
        authorise(user, actions.EVENT_VIEW, event)


def test_organiser_allowed_on_own_event():
    user = make_user(["event_organizer"], user_id="org-1")
    event = FakeEvent(organizer_id="org-1")
    assert can(user, actions.EVENT_VIEW, event) is True


def test_coordinator_allowed_view_on_assigned_event():
    user = make_user(["event_coordinator"], user_id="coord-1")
    event = FakeEvent(organizer_id="org-1", coordinator_id="coord-1")
    assert can(user, actions.EVENT_VIEW, event) is True


# -- event.edit -----------------------------------------------------------


def test_organiser_denied_edit_after_submission():
    user = make_user(["event_organizer"], user_id="org-1")
    event = FakeEvent(organizer_id="org-1", status="submitted")
    assert can(user, actions.EVENT_EDIT, event) is False
    with pytest.raises(AuthorisationError):
        authorise(user, actions.EVENT_EDIT, event)


def test_organiser_allowed_edit_while_draft():
    user = make_user(["event_organizer"], user_id="org-1")
    event = FakeEvent(organizer_id="org-1", status="draft")
    assert can(user, actions.EVENT_EDIT, event) is True


def test_organiser_allowed_edit_after_rejection():
    """A rejected request returns to the organizer for corrections."""
    user = make_user(["event_organizer"], user_id="org-1")
    event = FakeEvent(organizer_id="org-1", status="rejected")
    assert can(user, actions.EVENT_EDIT, event) is True


def test_coordinator_allowed_edit_assigned_event_in_planning():
    user = make_user(["event_coordinator"], user_id="coord-1")
    event = FakeEvent(coordinator_id="coord-1", status="planning")
    assert can(user, actions.EVENT_EDIT, event) is True


def test_coordinator_denied_edit_assigned_event_outside_planning():
    user = make_user(["event_coordinator"], user_id="coord-1")
    event = FakeEvent(coordinator_id="coord-1", status="approved")
    assert can(user, actions.EVENT_EDIT, event) is False
    with pytest.raises(AuthorisationError):
        authorise(user, actions.EVENT_EDIT, event)


def test_coordinator_denied_edit_on_event_assigned_to_someone_else():
    user = make_user(["event_coordinator"], user_id="coord-1")
    event = FakeEvent(coordinator_id="coord-2", status="planning")
    assert can(user, actions.EVENT_EDIT, event) is False
    with pytest.raises(NotFoundError):
        authorise(user, actions.EVENT_EDIT, event)


def test_organiser_edit_behaviour_unchanged_by_coordinator_window():
    """Regression guard: adding the coordinator branch to rule_event_edit
    must not change what an organiser can or can't do."""
    user = make_user(["event_organizer"], user_id="org-1")
    assert can(user, actions.EVENT_EDIT, FakeEvent(organizer_id="org-1", status="draft")) is True
    assert can(user, actions.EVENT_EDIT, FakeEvent(organizer_id="org-1", status="planning")) is False
    assert can(user, actions.EVENT_EDIT, FakeEvent(organizer_id="org-2", status="draft")) is False


def test_multi_role_union_on_same_event_for_edit():
    """A user who is BOTH the organiser AND the assigned coordinator of
    the SAME event (the schema permits organizer_id == coordinator_id ==
    one person) must be allowed via EITHER branch independently -- not
    denied just because the first-checked branch's status window
    happened to fail. This is the exact bug rule_event_edit's early
    multi-branch structure exists to avoid."""
    user = make_user(["event_organizer", "event_coordinator"], user_id="user-1")

    # Status fails the organiser window (draft) but satisfies the
    # coordinator window (planning) -- must still be ALLOW.
    event = FakeEvent(organizer_id="user-1", coordinator_id="user-1", status="planning")
    assert can(user, actions.EVENT_EDIT, event) is True

    # Neither window satisfied -- must be DENY_FORBIDDEN (403), since a
    # relationship exists (both, in fact), not DENY_NOT_FOUND (404).
    event_wrong_status = FakeEvent(organizer_id="user-1", coordinator_id="user-1", status="submitted")
    assert can(user, actions.EVENT_EDIT, event_wrong_status) is False
    with pytest.raises(AuthorisationError):
        authorise(user, actions.EVENT_EDIT, event_wrong_status)


# -- event.approve / event.reject ----------------------------------------


def test_coordinator_denied_approve_on_event_assigned_to_someone_else():
    user = make_user(["event_coordinator"], user_id="coord-1")
    event = FakeEvent(coordinator_id="coord-2", status="under_review")
    assert can(user, actions.EVENT_APPROVE, event) is False
    with pytest.raises(NotFoundError):
        authorise(user, actions.EVENT_APPROVE, event)


def test_coordinator_denied_approve_from_status_other_than_under_review():
    user = make_user(["event_coordinator"], user_id="coord-1")
    event = FakeEvent(coordinator_id="coord-1", status="approved")
    assert can(user, actions.EVENT_APPROVE, event) is False
    with pytest.raises(AuthorisationError):
        authorise(user, actions.EVENT_APPROVE, event)


def test_coordinator_allowed_approve_on_own_assigned_event_under_review():
    user = make_user(["event_coordinator"], user_id="coord-1")
    event = FakeEvent(coordinator_id="coord-1", status="under_review")
    assert can(user, actions.EVENT_APPROVE, event) is True


def test_coordinator_denied_reject_on_event_assigned_to_someone_else():
    user = make_user(["event_coordinator"], user_id="coord-1")
    event = FakeEvent(coordinator_id="coord-2", status="under_review")
    assert can(user, actions.EVENT_REJECT, event) is False


def test_coordinator_denied_reject_from_status_other_than_under_review():
    user = make_user(["event_coordinator"], user_id="coord-1")
    event = FakeEvent(coordinator_id="coord-1", status="approved")
    assert can(user, actions.EVENT_REJECT, event) is False
    with pytest.raises(AuthorisationError):
        authorise(user, actions.EVENT_REJECT, event)


def test_coordinator_allowed_reject_on_own_assigned_event_under_review():
    user = make_user(["event_coordinator"], user_id="coord-1")
    event = FakeEvent(coordinator_id="coord-1", status="under_review")
    assert can(user, actions.EVENT_REJECT, event) is True


# -- event.request_clarification ------------------------------------------


def test_coordinator_allowed_request_clarification_under_review():
    user = make_user(["event_coordinator"], user_id="coord-1")
    event = FakeEvent(coordinator_id="coord-1", status="under_review")
    assert can(user, actions.EVENT_REQUEST_CLARIFICATION, event) is True


def test_coordinator_denied_request_clarification_on_unassigned_event():
    user = make_user(["event_coordinator"], user_id="coord-1")
    event = FakeEvent(coordinator_id="coord-2", status="under_review")
    assert can(user, actions.EVENT_REQUEST_CLARIFICATION, event) is False


def test_coordinator_denied_request_clarification_from_status_other_than_under_review():
    user = make_user(["event_coordinator"], user_id="coord-1")
    event = FakeEvent(coordinator_id="coord-1", status="approved")
    assert can(user, actions.EVENT_REQUEST_CLARIFICATION, event) is False
    with pytest.raises(AuthorisationError):
        authorise(user, actions.EVENT_REQUEST_CLARIFICATION, event)


# -- event.cancel ---------------------------------------------------------


def test_coordinator_denied_cancel_before_approval():
    user = make_user(["event_coordinator"], user_id="coord-1")
    event = FakeEvent(coordinator_id="coord-1", status="under_review")
    assert can(user, actions.EVENT_CANCEL, event) is False
    with pytest.raises(AuthorisationError):
        authorise(user, actions.EVENT_CANCEL, event)


def test_coordinator_allowed_cancel_post_approval_on_own_event():
    user = make_user(["event_coordinator"], user_id="coord-1")
    event = FakeEvent(coordinator_id="coord-1", status="approved")
    assert can(user, actions.EVENT_CANCEL, event) is True


def test_coordinator_denied_cancel_on_event_assigned_to_someone_else():
    user = make_user(["event_coordinator"], user_id="coord-1")
    event = FakeEvent(coordinator_id="coord-2", status="approved")
    assert can(user, actions.EVENT_CANCEL, event) is False


# -- event.create / event.list (role-only, no resource) ----------------------


def test_attendee_denied_event_create_role_only_no_resource():
    user = make_user(["attendee"], user_id="att-1")
    assert can(user, actions.EVENT_CREATE) is False
    with pytest.raises(AuthorisationError):
        authorise(user, actions.EVENT_CREATE)


def test_organiser_allowed_event_create():
    user = make_user(["event_organizer"], user_id="org-1")
    assert can(user, actions.EVENT_CREATE) is True


def test_event_list_denied_for_role_with_no_listing_rights():
    user = make_user(["attendee"], user_id="att-1")
    assert can(user, actions.EVENT_LIST) is False
    with pytest.raises(AuthorisationError):
        authorise(user, actions.EVENT_LIST)


def test_organiser_allowed_event_list():
    user = make_user(["event_organizer"], user_id="org-1")
    assert can(user, actions.EVENT_LIST) is True


def test_coordinator_allowed_event_list():
    """Ruling: event.list extends to coordinators (View Assigned Event
    Requests story). Passing this only means the role may list
    something -- see rule_event_list's module-docstring warning about
    caller-applied scoping."""
    user = make_user(["event_coordinator"], user_id="coord-1")
    assert can(user, actions.EVENT_LIST) is True


# -- event.submit ---------------------------------------------------------


def test_organiser_denied_event_submit_on_event_that_isnt_theirs():
    user = make_user(["event_organizer"], user_id="org-1")
    event = FakeEvent(organizer_id="org-2", status="draft")
    assert can(user, actions.EVENT_SUBMIT, event) is False
    with pytest.raises(NotFoundError):
        authorise(user, actions.EVENT_SUBMIT, event)


def test_organiser_denied_event_submit_from_status_other_than_draft():
    user = make_user(["event_organizer"], user_id="org-1")
    event = FakeEvent(organizer_id="org-1", status="submitted")
    assert can(user, actions.EVENT_SUBMIT, event) is False
    with pytest.raises(AuthorisationError):
        authorise(user, actions.EVENT_SUBMIT, event)


def test_organiser_allowed_event_submit_from_draft():
    user = make_user(["event_organizer"], user_id="org-1")
    event = FakeEvent(organizer_id="org-1", status="draft")
    assert can(user, actions.EVENT_SUBMIT, event) is True


# -- event.reassign_coordinator (for Justin -- not wired into coordinator_service.py) --


def test_coordinator_allowed_reassign_when_currently_assigned():
    user = make_user(["event_coordinator"], user_id="coord-1")
    event = FakeEvent(coordinator_id="coord-1", status="planning")
    assert can(user, actions.EVENT_REASSIGN_COORDINATOR, event) is True


def test_coordinator_denied_reassign_when_not_currently_assigned():
    user = make_user(["event_coordinator"], user_id="coord-1")
    event = FakeEvent(coordinator_id="coord-2", status="planning")
    assert can(user, actions.EVENT_REASSIGN_COORDINATOR, event) is False


# -- attendee denied everything internal ----------------------------------


def test_attendee_denied_every_internal_action():
    user = make_user(["attendee"], user_id="att-1")
    event = FakeEvent(organizer_id="someone-else", coordinator_id="someone-else-2", status="under_review")

    resource_actions = [
        actions.EVENT_VIEW,
        actions.EVENT_SUBMIT,
        actions.EVENT_EDIT,
        actions.EVENT_APPROVE,
        actions.EVENT_REJECT,
        actions.EVENT_REQUEST_CLARIFICATION,
        actions.EVENT_CANCEL,
        actions.EVENT_REASSIGN_COORDINATOR,
    ]
    for action in resource_actions:
        assert can(user, action, event) is False, f"attendee should be denied {action}"

    for action in (actions.EVENT_CREATE, actions.EVENT_LIST):
        assert can(user, action) is False, f"attendee should be denied {action}"


# -- multi-role union (customer requirement) -------------------------------


def test_multi_role_user_gets_union_of_permissions():
    """A user holding BOTH event_organizer and event_coordinator gets
    access via EITHER role's relationship -- the customer's explicit
    multi-role requirement (one person may hold Coordinator and Venue
    Staff simultaneously), proven structurally, not by a special case."""
    user = make_user(["event_organizer", "event_coordinator"], user_id="user-1")

    own_event_as_organiser = FakeEvent(organizer_id="user-1", coordinator_id="someone-else", status="draft")
    assert can(user, actions.EVENT_VIEW, own_event_as_organiser) is True
    assert can(user, actions.EVENT_EDIT, own_event_as_organiser) is True

    assigned_event_as_coordinator = FakeEvent(
        organizer_id="someone-else", coordinator_id="user-1", status="under_review"
    )
    assert can(user, actions.EVENT_VIEW, assigned_event_as_coordinator) is True
    assert can(user, actions.EVENT_APPROVE, assigned_event_as_coordinator) is True

    neither_relationship = FakeEvent(organizer_id="a", coordinator_id="b", status="under_review")
    assert can(user, actions.EVENT_VIEW, neither_relationship) is False


# -- deny-by-default meta-tests --------------------------------------------


def test_unknown_action_denied():
    """A string that was never a real action constant at all -- a typo,
    not a wiring gap."""
    user = make_user(["event_organizer"], user_id="org-1")
    event = FakeEvent(organizer_id="org-1")
    assert can(user, "totally.made.up.action", event) is False


def test_registered_action_with_no_rule_denied(monkeypatch):
    """A REAL constant from app.authz.actions whose rule was never wired
    into policy._RULES -- the scenario a teammate would actually hit,
    distinct from a plain typo. Simulated by deleting one real
    registration at runtime; monkeypatch.delitem restores it after this
    test regardless of outcome."""
    from app.authz import policy

    user = make_user(["event_coordinator"], user_id="coord-1")
    event = FakeEvent(coordinator_id="coord-1", status="approved")
    # Sanity check: this WOULD be allowed if the rule stayed registered.
    assert can(user, actions.EVENT_CANCEL, event) is True

    monkeypatch.delitem(policy._RULES, actions.EVENT_CANCEL)
    assert can(user, actions.EVENT_CANCEL, event) is False
    with pytest.raises(AuthorisationError):
        authorise(user, actions.EVENT_CANCEL, event)


# -- 403 vs 404 selection ---------------------------------------------------


def test_403_not_404_when_relationship_exists_but_status_blocks():
    user = make_user(["event_organizer"], user_id="org-1")
    event = FakeEvent(organizer_id="org-1", status="submitted")
    with pytest.raises(AuthorisationError):
        authorise(user, actions.EVENT_EDIT, event)


def test_404_not_403_when_no_relationship_exists():
    user = make_user(["event_organizer"], user_id="org-1")
    event = FakeEvent(organizer_id="org-2", status="draft")
    with pytest.raises(NotFoundError):
        authorise(user, actions.EVENT_EDIT, event)
