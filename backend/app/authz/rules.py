"""
One small predicate per rule, composed into one function per action.

PURITY IS DELIBERATE: every function here is a pure function of
(user, resource) -- no database access, no Flask imports, no I/O of any
kind. That's what makes them testable with plain Python objects (see
tests/factories.py) instead of a running app or a database, and it's
what makes app.authz.policy safe to call from anywhere (a route
decorator, a service function, a test) without worrying what it might
do besides answer a question.

DECISION, NOT BOOL: each rule returns a Decision, not a plain bool,
because "no" has two different meanings here and callers need to know
which one they got (see app.authz.policy's docstring for how this
becomes a 403 or a 404):

    ALLOW           -- the action is permitted.
    DENY_NOT_FOUND  -- the caller has NO qualifying relationship to this
                       resource at all (not their event, not assigned to
                       them). They aren't entitled to know it exists.
    DENY_FORBIDDEN  -- the caller DOES have a qualifying relationship,
                       but some other condition blocks the action (wrong
                       status, wrong coordinator-of-record). They already
                       legitimately know the resource exists.

Every rule below checks relationship FIRST and returns DENY_NOT_FOUND
immediately if that fails, before ever looking at status -- so a caller
with no relationship gets the same answer regardless of what status the
resource happens to be in. Role-only actions (EVENT_CREATE, EVENT_LIST --
see their own section below) have no resource to have a relationship
with, so their only possible denial is DENY_FORBIDDEN.

MULTI-ROLE UNION IS STRUCTURAL: a rule checks role membership with
`"some_role" in user.roles` (a frozenset), never `user.role ==
"some_role"` or anything that assumes exactly one role. A user holding
both event_organizer and event_coordinator gets access through EITHER
path in e.g. rule_event_view below -- there is no special multi-role
case to maintain, because there's only one way these checks were ever
written. This is the customer's explicit multi-role requirement (one
person may be both Coordinator and Venue Staff), made structural rather
than bolted on.

WHY SEPARATE ACTIONS FOR APPROVE / REJECT / REQUEST_CLARIFICATION /
CANCEL, NOT ONE event.change_status: each has a different status
precondition (approve/reject/request_clarification all require
under_review; cancel requires a post-approval status -- see below), and
collapsing them into one action would just move that branch inside the
rule, keyed off a target-status argument instead of off the action
string. That's strictly harder to test (you'd assert on
(action, target_status) pairs instead of one name each) and harder to
explain -- "what can a coordinator do to an event" should be answerable
by reading a list of action names, not by reading a branch.

EVENT_LIST / EVENT_CREATE ARE ROLE-ONLY, AND THAT IS NOT A SECURITY
HOLE: there is no single resource to evaluate a relationship against --
"list" operates over a whole collection, and "create" happens before any
row exists. Both rules below answer a narrower question than usual:
"does this role get to attempt this kind of operation at all", NOT "does
this user get to see this specific row". The actual per-row scoping for
EVENT_LIST (an organiser's list query must filter to their own
organizer_id; a future coordinator listing would filter to their own
coordinator_id) lives in the CALLER's query, not here -- app.authz has
no way to see a query the caller hasn't written yet. Whoever builds the
event-listing route MUST apply that filter themselves; can() passing is
necessary but not sufficient for that endpoint. This is the same
division of responsibility as the field-visibility decision (see
docs/design-decisions.md): can() answers yes/no questions about actions,
it was never meant to reach into a query or a serialiser on your behalf.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class Decision(Enum):
    ALLOW = "allow"
    DENY_NOT_FOUND = "deny_not_found"
    DENY_FORBIDDEN = "deny_forbidden"


# -- low-level predicates, composed by the per-action rules below -----------


def _has_role(user: Any, role: str) -> bool:
    return role in user.roles


def _owns_event(user: Any, event: Any) -> bool:
    return event.organizer_id == user.id


def _is_assigned_coordinator(user: Any, event: Any) -> bool:
    return event.coordinator_id == user.id


def _event_status_in(event: Any, *statuses: str) -> bool:
    return event.status in statuses


# -- event.view --------------------------------------------------------------
# Source: "an organiser sees full details of their own events; other
# organisers' events are hidden" (ruled: hidden, not restricted -- a 404,
# not a partial view) + the implicit prerequisite for an assigned
# coordinator acting on an event at all.


def rule_event_view(user: Any, event: Any) -> Decision:
    if _has_role(user, "event_organizer") and _owns_event(user, event):
        return Decision.ALLOW
    if _has_role(user, "event_coordinator") and _is_assigned_coordinator(user, event):
        return Decision.ALLOW
    return Decision.DENY_NOT_FOUND


# -- event.list (role-only -- see module docstring) --------------------------
# Source: View Event Requests story -- "can view all the event requests
# that have been created or drafted by him or her". That story is
# organiser-specific; it does NOT establish a coordinator listing right,
# so this is organiser-only until a story says otherwise (flagged in the
# Phase 4 report, not assumed here).


def rule_event_list(user: Any, event: Any = None) -> Decision:
    if _has_role(user, "event_organizer"):
        return Decision.ALLOW
    return Decision.DENY_FORBIDDEN


# -- event.create (role-only -- see module docstring) -------------------
# Source: "a user's access is limited to their role" -- only an Event
# Organizer creates an event request; an Attendee POSTing one is a
# policy decision, not a route-level afterthought.


def rule_event_create(user: Any, event: Any = None) -> Decision:
    if _has_role(user, "event_organizer"):
        return Decision.ALLOW
    return Decision.DENY_FORBIDDEN


# -- event.submit -------------------------------------------------------
# Source: Event Status Management story -- "submitting a completed
# request changes status to Submitted", organiser-only, and only from
# draft (status precondition taken directly from that quote).


def rule_event_submit(user: Any, event: Any) -> Decision:
    if not (_has_role(user, "event_organizer") and _owns_event(user, event)):
        return Decision.DENY_NOT_FOUND
    if not _event_status_in(event, "draft"):
        return Decision.DENY_FORBIDDEN
    return Decision.ALLOW


# -- event.edit --------------------------------------------------------------
# Source: "an organiser cannot edit directly after submission; changes go
# via the coordinator" -- status precondition (draft only) taken
# directly from that criterion. Same precondition as event.submit by
# coincidence of the criteria, not because the two actions are secretly
# one thing -- kept as separate functions so either can change
# independently if a future clarification splits them.


def rule_event_edit(user: Any, event: Any) -> Decision:
    if not (_has_role(user, "event_organizer") and _owns_event(user, event)):
        return Decision.DENY_NOT_FOUND
    if not _event_status_in(event, "draft"):
        return Decision.DENY_FORBIDDEN
    return Decision.ALLOW


# -- event.approve / event.reject ----------------------------------------
# Source: "a coordinator acts only on events assigned to them" + the
# migration's own comment naming the Event Status Management story's
# workflow (approved/rejected are the two real terminal-from-review
# statuses). Status precondition (under_review) taken from that
# workflow ordering: draft -> submitted -> under_review -> approved/
# rejected.


def rule_event_approve(user: Any, event: Any) -> Decision:
    if not (_has_role(user, "event_coordinator") and _is_assigned_coordinator(user, event)):
        return Decision.DENY_NOT_FOUND
    if not _event_status_in(event, "under_review"):
        return Decision.DENY_FORBIDDEN
    return Decision.ALLOW


def rule_event_reject(user: Any, event: Any) -> Decision:
    if not (_has_role(user, "event_coordinator") and _is_assigned_coordinator(user, event)):
        return Decision.DENY_NOT_FOUND
    if not _event_status_in(event, "under_review"):
        return Decision.DENY_FORBIDDEN
    return Decision.ALLOW


# -- event.request_clarification -----------------------------------------
# Source: Event Review and Approval story -- coordinator selects "Request
# Clarification" and enters comments; status STAYS under_review. Read as:
# the action is only valid to invoke while status already is
# under_review (same precondition as approve/reject, same source story).


def rule_event_request_clarification(user: Any, event: Any) -> Decision:
    if not (_has_role(user, "event_coordinator") and _is_assigned_coordinator(user, event)):
        return Decision.DENY_NOT_FOUND
    if not _event_status_in(event, "under_review"):
        return Decision.DENY_FORBIDDEN
    return Decision.ALLOW


# -- event.cancel -------------------------------------------------------
# Source: Cancelled Status story -- "Coordinator can change status to
# cancelled after approval of the event request". The literal quote only
# says "approved"; FLAGGED (not invented silently): the set below also
# includes "planning" and "confirmed", inferred from the migration
# comment's own lifecycle ordering (approved -> planning -> confirmed ->
# completed) on the reasoning that "after approval" describes the whole
# span of the post-approval lifecycle, not only the single "approved"
# status, and matches coordinator_service.py's own ACTIVE_STATUSES minus
# under_review. "completed" is deliberately excluded -- cancelling a
# finished event doesn't match "after approval of the request", it's a
# different (and unasked-for) lifecycle question. Confirm this reading
# if it's wrong; it's an inference, not a quote.

_CANCELLABLE_STATUSES = ("approved", "planning", "confirmed")


def rule_event_cancel(user: Any, event: Any) -> Decision:
    if not (_has_role(user, "event_coordinator") and _is_assigned_coordinator(user, event)):
        return Decision.DENY_NOT_FOUND
    if not _event_status_in(event, *_CANCELLABLE_STATUSES):
        return Decision.DENY_FORBIDDEN
    return Decision.ALLOW


# -- event.reassign_coordinator -------------------------------------------
# Source: explicit instruction to ready this for coordinator_service.py's
# reassign_coordinator(requested_by=...) escape hatch. Mirrors that
# function's own existing check exactly: only the CURRENT coordinator of
# record may request a reassignment. No status precondition --
# coordinator_service.py's own docstring says reassignment "doesn't
# change where the event is in its lifecycle", so none is encoded here
# either.


def rule_event_reassign_coordinator(user: Any, event: Any) -> Decision:
    if not (_has_role(user, "event_coordinator") and _is_assigned_coordinator(user, event)):
        return Decision.DENY_NOT_FOUND
    return Decision.ALLOW
