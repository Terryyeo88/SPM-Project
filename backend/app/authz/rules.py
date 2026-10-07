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
this user get to see this specific row". This is the same division of
responsibility as the field-visibility decision (see
docs/design-decisions.md): can() answers yes/no questions about actions,
it was never meant to reach into a query or a serialiser on your behalf.

    *** READ THIS BEFORE WIRING UP EVENT_LIST ***
    can(user, EVENT_LIST) passing means "this role is allowed to list
    SOMETHING" -- it does NOT mean "show them every event". The per-row
    scoping is entirely the CALLER's responsibility, applied to the
    query itself, BEFORE rows reach the response:
        - an organiser's list query must filter to `organizer_id ==
          user.id`
        - a coordinator's list query must filter to `coordinator_id ==
          user.id`
    app.authz has no way to see a query the caller hasn't written yet,
    so it cannot enforce this for you. Forgetting this filter is not a
    degraded experience, it is every event in the table leaked to
    whoever asks -- this is the one place in this module where passing
    can() is necessary but nowhere near sufficient.
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


# Week 7 change #5: the Event Coordinator Lead "oversees incoming event
# requests" and "should be able to view all coordinator assignments and
# active events under their supervision". Read as: every event that has
# been SUBMITTED (any status but draft). A draft hasn't been sent to
# anyone yet, so it stays private to its organiser. Every coordinator
# reports to the one Lead (no teams in the brief), so "under their
# supervision" is all of them -- see docs/open-questions.md.
LEAD_ROLE = "event_coordinator_lead"


def _is_lead_over(user: Any, event: Any) -> bool:
    return _has_role(user, LEAD_ROLE) and not _event_status_in(event, "draft")


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
    if _is_lead_over(user, event):
        return Decision.ALLOW
    return Decision.DENY_NOT_FOUND


# -- event.list (role-only -- see *** warning *** in module docstring) -------
# Source: organiser grant from the View Event Requests story -- "can view
# all the event requests that have been created or drafted by him or
# her". Coordinator grant from the View Assigned Event Requests story --
# a coordinator can view a list of event requests assigned to them. Two
# different stories, two different roles, same role-only shape -- see the
# module docstring's warning: EACH of these two roles depends on the
# CALLER filtering by a DIFFERENT column (organizer_id for the organiser,
# coordinator_id for the coordinator). Forgetting either filter leaks
# every event to that caller.


def rule_event_list(user: Any, event: Any = None) -> Decision:
    # The Lead's per-row scope (every non-draft event) is applied by
    # event_service.list_event_requests, same as the other two roles.
    if _has_role(user, "event_organizer") or _has_role(user, "event_coordinator") or _has_role(user, LEAD_ROLE):
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
# request changes status to Submitted", organiser-only. Allowed from
# draft (first submission) and from rejected (resubmission after the
# organiser fixes what the coordinator rejected -- "a rejected request
# can be re-submitted for review after the Organizer makes changes";
# ruling: rejected -> submitted, via the same /submit). This closes the
# dead end where rule_event_edit let an organiser edit a rejected request
# that nothing then let them submit. "After changes" is NOT verified
# (see docs/open-questions.md).


def rule_event_submit(user: Any, event: Any) -> Decision:
    if not (_has_role(user, "event_organizer") and _owns_event(user, event)):
        return Decision.DENY_NOT_FOUND
    if not _event_status_in(event, "draft", "rejected"):
        return Decision.DENY_FORBIDDEN
    return Decision.ALLOW


# -- event.edit --------------------------------------------------------------
# Two sources, one action, by explicit decision (not a second action) --
# it's the same verb (change the event's own fields) on the same
# resource, just gated by a different role-dependent status window:
#
#   organiser:   draft only. Source: "an organiser cannot edit directly
#                after submission; changes go via the coordinator".
#   coordinator: assigned, AND status in ("under_review", "planning").
#                Sources: the Event Information Management story, which
#                has the coordinator updating event information during
#                planning; and IS-31 Submit event request, where once a
#                request is submitted "only the Event Coordinator is
#                allowed to edit the event request" -- so the assigned
#                coordinator can also correct it while reviewing it
#                (under_review), instead of nobody being able to.
#
# A second action (e.g. event.update_planning) was the alternative and
# was rejected: the rule below is two clearly separate branches (check
# one relationship, check one status, independently of the other
# branch), not a tangle, and "what can change this event's fields" stays
# answerable by one action name instead of two. This does mean
# event.edit and event.submit, byte-identical until this change, no
# longer are -- which is the retroactive justification for having kept
# them as separate functions even when they were identical: the moment
# one criterion applies to only one of them, a shared implementation
# would have had to split apart anyway.


def rule_event_edit(user: Any, event: Any) -> Decision:
    # Checks BOTH branches rather than returning on the first matching
    # relationship, unlike the simpler rules above -- this is the one
    # rule in this module where a single user could plausibly satisfy
    # both relationships on the SAME event (e.g. a coordinator who is
    # also its organiser), each with its OWN status window. Returning
    # early on the first relationship found, regardless of its status
    # outcome, would deny a union-eligible multi-role user who'd have
    # been allowed via the other branch -- exactly the "special case
    # that breaks the union" the module docstring says not to write.
    has_relationship = False
    if _has_role(user, "event_organizer") and _owns_event(user, event):
        has_relationship = True
        if _event_status_in(event, "draft", "rejected"):
            return Decision.ALLOW
    if _has_role(user, "event_coordinator") and _is_assigned_coordinator(user, event):
        has_relationship = True
        if _event_status_in(event, "under_review", "planning"):
            return Decision.ALLOW
    if has_relationship:
        return Decision.DENY_FORBIDDEN
    return Decision.DENY_NOT_FOUND


# -- event.delete --------------------------------------------------------
# Source: same organiser-draft window as event.submit/event.edit's
# organiser branch. An organiser may discard a request they haven't submitted
# anywhere yet; once it's submitted, it's left their hands (a coordinator
# may be assigned, reviewing it, etc.) so deletion is no longer theirs to
# do -- withdrawing a submitted request is a status change (e.g. cancel),
# not a delete, and out of scope here.


def rule_event_delete(user: Any, event: Any) -> Decision:
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
# cancelled after approval of the event request". DECIDED (see
# docs/design-decisions.md) that this covers approved, planning, AND
# confirmed -- not literally just "approved". Reasoning: the Cancelled
# Status story is explicitly about a coordinator who cannot secure a
# venue or equipment, which happens during planning, not at the instant
# approval is granted; a literal approved-only reading would make that
# story's own scenario unimplementable. "completed" is still excluded --
# cancelling a finished event is a different, unasked-for lifecycle
# question. "after approval" as a range (not a single status) is noted
# in docs/open-questions.md for customer confirmation -- that's a request
# to confirm a decision already made, not an open implementation gap.

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
# record may request a reassignment.
#
# Status precondition (IS-38, added Sprint 2): not once `completed`.
# Source: "completed events are read-only going forward". Reassigning
# the coordinator of record is a write to a completed event, so it is
# refused like edit/submit/cancel are. Reassignment itself still doesn't
# change the lifecycle status (coordinator_service.py's docstring). ONLY
# `completed` is excluded, because that's the only status a story makes
# read-only. `cancelled` and `rejected` are NOT excluded -- no story
# says so, and that's flagged in docs/open-questions.md rather than
# guessed.


#
# Week 7 change #5: the Event Coordinator Lead may also reassign ("assign
# a suitable Event Coordinator, and reassign events where necessary"),
# any event that already HAS a coordinator -- an unassigned one goes
# through event.assign_coordinator instead. Same `completed` exclusion.


def rule_event_reassign_coordinator(user: Any, event: Any) -> Decision:
    is_current = _has_role(user, "event_coordinator") and _is_assigned_coordinator(user, event)
    if not (is_current or _is_lead_over(user, event)):
        return Decision.DENY_NOT_FOUND
    if _event_status_in(event, "completed") or not event.coordinator_id:
        return Decision.DENY_FORBIDDEN
    return Decision.ALLOW


# -- event.assign_coordinator ---------------------------------------------
# Source: Week 7 change #5 -- "Newly submitted event requests should no
# longer be assigned directly to an Event Coordinator. Instead, they first
# enter an unassigned queue that can be viewed by the Event Coordinator
# Lead. The Lead can ... assign a suitable Event Coordinator". Lead only,
# and only for a request still in that queue: submitted, nobody assigned.
# Anyone else who can see the event (its organiser, its coordinator) gets
# a 403, not a 404 -- they already know it exists.


def rule_event_assign_coordinator(user: Any, event: Any) -> Decision:
    if not _is_lead_over(user, event):
        if rule_event_view(user, event) is Decision.ALLOW:
            return Decision.DENY_FORBIDDEN
        return Decision.DENY_NOT_FOUND
    if not _event_status_in(event, "submitted") or event.coordinator_id:
        return Decision.DENY_FORBIDDEN
    return Decision.ALLOW


# -- event.start_planning / event.confirm / event.complete --------------
# Assigned coordinator only, each from exactly one status -- the same
# relationship-first shape as approve/reject. The status here is the
# authz precondition (which decides the 403). The same pair is ALSO an
# entry in app.events.transitions.ALLOWED, which decides whether the
# write is legal and makes it conditional. The duplication is
# deliberate: see docs/design-decisions.md on why authz and the state
# machine are separate.
#
#   start_planning  approved  -> planning   IS-36. Source: "Coordinator can
#                                           set planning only if current
#                                           status is approved".
#   confirm         planning  -> confirmed  Source: "Coordinator can set
#                                           confirmed only from planning".
#                                           Built for end-to-end testability
#                                           of IS-38 only -- the Confirmed
#                                           Status story's field-locking
#                                           half is NOT implemented.
#   complete        confirmed -> completed  IS-38. Source: "Coordinator can
#                                           set completed only from
#                                           confirmed".


def _assigned_coordinator_from(user: Any, event: Any, status: str) -> Decision:
    if not (_has_role(user, "event_coordinator") and _is_assigned_coordinator(user, event)):
        return Decision.DENY_NOT_FOUND
    if not _event_status_in(event, status):
        return Decision.DENY_FORBIDDEN
    return Decision.ALLOW


def rule_event_start_planning(user: Any, event: Any) -> Decision:
    return _assigned_coordinator_from(user, event, "approved")


def rule_event_confirm(user: Any, event: Any) -> Decision:
    return _assigned_coordinator_from(user, event, "planning")


def rule_event_complete(user: Any, event: Any) -> Decision:
    return _assigned_coordinator_from(user, event, "confirmed")


# -- venue.view / venue.list (role-only -- see actions.py's venues section) -
# Source: View Venue Catalogue story -- "As an Event Coordinator, I want
# to see venue details so that I can find the appropriate venue for the
# event request." No ownership relationship exists for a venue (it's
# shared inventory, not a per-user resource), so both actions are
# role-only, same shape as event.list/event.create above -- unlike
# event.list, though, there is no additional per-row filter the caller
# must apply afterwards, because every coordinator is entitled to see
# every venue in the catalogue.
#
# venue_staff is included alongside event_coordinator: Venue Staff are
# the ones who approve or reject bookings against these same records
# (Venue Booking Approval story, later sprint), so they need to see venue
# details too. This is our own inference, not a line from the story text
# -- flagged in docs/open-questions.md for customer confirmation, same
# as any other assumption this codebase has made ahead of a confirmed
# answer.


def rule_venue_list(user: Any, venue: Any = None) -> Decision:
    if _has_role(user, "event_coordinator") or _has_role(user, "venue_staff"):
        return Decision.ALLOW
    return Decision.DENY_FORBIDDEN


def rule_venue_view(user: Any, venue: Any = None) -> Decision:
    return rule_venue_list(user, venue)


# -- venue.calendar_view (Nawaz, Sprint 2: IS-11) --------------------------
# Same event_coordinator/venue_staff pair as rule_venue_view above -- see
# actions.py's VENUE_CALENDAR_VIEW comment for why this isn't just a
# reuse of VENUE_VIEW. Role-only, no per-row scoping needed here either:
# "Can only view calendars for venues the user's role permits" (AC) is
# fully answered by the role check -- there's no per-venue-staff
# assignment table (see rule_venue_booking_list's own comment on the same
# gap) that would make it mean anything narrower than "every venue".


def rule_venue_calendar_view(user: Any, venue: Any = None) -> Decision:
    return rule_venue_list(user, venue)


# -- venue_booking.create -------------------------------------------------
# Source: Venue Booking Request story -- the assigned Event Coordinator
# submits a request against an event they're coordinating. The resource
# checked here is the EVENT (the booking doesn't exist yet), reusing
# EventLike/_is_assigned_coordinator exactly like event.edit does.
#
# Status precondition: "approved" or "planning". The Event Status
# Management "Planning Status" story says a venue/equipment search
# requires the event to already be in "planning" -- but nothing in this
# codebase transitions an event TO "planning" (that's a separate,
# unassigned sub-story; see app.events.event_service, which only ever
# writes draft/submitted/under_review/approved/rejected). Rather than
# make this feature unreachable until someone else ships that
# transition, app.venues.booking_service.create_booking_request performs
# the narrow approved -> planning transition itself, as a documented
# side effect of starting the venue search -- directly matching the
# story's own framing ("the Coordinator has to change the status to
# 'planning' before... searching for a venue"). Allowing "planning" here
# too covers a second booking request on an event already in planning
# (e.g. a multi-session request's other sessions, or a second attempt
# after a rejection). See docs/design-decisions.md for the full
# reasoning and the sign-off this needed.


def rule_venue_booking_create(user: Any, event: Any) -> Decision:
    if not (_has_role(user, "event_coordinator") and _is_assigned_coordinator(user, event)):
        return Decision.DENY_NOT_FOUND
    if not _event_status_in(event, "approved", "planning"):
        return Decision.DENY_FORBIDDEN
    return Decision.ALLOW


# -- venue_booking.view / venue_booking.list -------------------------------
# view: the requesting coordinator (so they "can view" a rejection
# reason -- Approval AC2) or any venue_staff (so they can open a booking
# from their queue to decide on it).
#
# list is role-only, same *** WARNING *** as rule_event_list /
# rule_venue_list above: passing this does NOT mean "see every booking".
# app.venues.booking_service.list_bookings is where the actual per-row
# scoping happens (coordinator -> requested_by == user.id; venue_staff
# -> unfiltered, since no per-venue-staff-assignment table exists yet --
# flagged in docs/open-questions.md, same as rule_venue_list's own
# venue_staff-access assumption above).


def _is_booking_requester(user: Any, booking: Any) -> bool:
    return booking.requested_by == user.id


def rule_venue_booking_view(user: Any, booking: Any) -> Decision:
    if _has_role(user, "event_coordinator") and _is_booking_requester(user, booking):
        return Decision.ALLOW
    if _has_role(user, "venue_staff"):
        return Decision.ALLOW
    return Decision.DENY_NOT_FOUND


def rule_venue_booking_list(user: Any, resource: Any = None) -> Decision:
    if _has_role(user, "event_coordinator") or _has_role(user, "venue_staff"):
        return Decision.ALLOW
    return Decision.DENY_FORBIDDEN


# -- venue_booking.approve / venue_booking.reject --------------------------
# Source: Venue Booking Approval story -- "As a Venue Staff member, I
# want to review pending venue booking requests and approve or reject
# them". Role-only relationship check (no per-venue-staff-assignment
# table -- see rule_venue_booking_list's comment above), status
# precondition "pending" only, same status-gated shape as
# rule_event_approve/rule_event_reject.


def _booking_status_in(booking: Any, *statuses: str) -> bool:
    return booking.status in statuses


def rule_venue_booking_approve(user: Any, booking: Any) -> Decision:
    if not _has_role(user, "venue_staff"):
        return Decision.DENY_NOT_FOUND
    if not _booking_status_in(booking, "pending"):
        return Decision.DENY_FORBIDDEN
    return Decision.ALLOW


def rule_venue_booking_reject(user: Any, booking: Any) -> Decision:
    # Same precondition as approve -- kept as a separate function per this
    # module's own stated reasoning (see "WHY SEPARATE ACTIONS..." above)
    # for not collapsing distinct decisions into one action.
    return rule_venue_booking_approve(user, booking)


# -- coordinator.list (role-only -- see actions.py's coordinators section) -
# Only an Event Coordinator or the Event Coordinator Lead can (re)assign
# (rule_event_reassign_coordinator / rule_event_assign_coordinator), so
# only they need to see who they could pick.


def rule_coordinator_list(user: Any, resource: Any = None) -> Decision:
    if _has_role(user, "event_coordinator") or _has_role(user, LEAD_ROLE):
        return Decision.ALLOW
    return Decision.DENY_FORBIDDEN


# -- event.register / registration.list (Attendee Registration, Justin) ---
# Source: "The Attendee can register only for an event that is confirmed
# and enabled for registration." An attendee has no relationship to any
# event until they register, so the only sessions that exist as far as
# they're concerned are the public ones: confirmed with registration
# enabled. Anything else is a 404 for them, the same as an outsider gets.
# Someone without the attendee role who can already see the event (its
# organiser, coordinator, the Lead) gets a 403 instead.
#
# The registration PERIOD is not checked here: it's time-based, not a
# property of (user, event), so the database function that records the
# registration checks it (supabase/migrations/20261005000000_registrations.sql).


def _is_public_for_registration(event: Any) -> bool:
    return _event_status_in(event, "confirmed") and getattr(event, "registration_needs", None) is True


def rule_event_register(user: Any, event: Any) -> Decision:
    if _has_role(user, "attendee"):
        return Decision.ALLOW if _is_public_for_registration(event) else Decision.DENY_NOT_FOUND
    if rule_event_view(user, event) is Decision.ALLOW:
        return Decision.DENY_FORBIDDEN
    return Decision.DENY_NOT_FOUND


def rule_event_view_public(user: Any, event: Any) -> Decision:
    """The attendee's event page shows only public fields, so it has exactly
    the same audience as registering: attendees, for public sessions."""
    return rule_event_register(user, event)


def rule_registration_withdraw(user: Any, event: Any) -> Decision:
    """Any attendee may ask to withdraw from a session; whether they hold a
    registration there is checked by the database function (no
    registration -> 404), so this reveals nothing about non-public
    sessions. Withdrawing stays possible after a session stops being
    public (e.g. cancelled) -- the attendee already knew about it."""
    if _has_role(user, "attendee"):
        return Decision.ALLOW
    if rule_event_view(user, event) is Decision.ALLOW:
        return Decision.DENY_FORBIDDEN
    return Decision.DENY_NOT_FOUND


def rule_registration_list(user: Any, resource: Any = None) -> Decision:
    if _has_role(user, "attendee"):
        return Decision.ALLOW
    return Decision.DENY_FORBIDDEN
