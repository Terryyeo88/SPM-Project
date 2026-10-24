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
#   coordinator: assigned, in ANY status except completed / cancelled.
#                Sources: the Event Information Management story, which
#                has the coordinator updating event information; IS-31
#                Submit event request, where once a request is submitted
#                "only the Event Coordinator is allowed to edit the event
#                request"; and the team's IS-21 decision that the
#                coordinator "should be able to edit the event details
#                when they want to" (widened from under_review/planning
#                only). Still closed once completed (IS-38: "completed
#                events are read-only going forward") or cancelled
#                (nothing left to arrange). The organiser, by contrast,
#                asks for changes through a change request (IS-21).
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


_COORDINATOR_EDIT_CLOSED = ("completed", "cancelled")


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
        if not _event_status_in(event, *_COORDINATOR_EDIT_CLOSED):
            return Decision.ALLOW
    # IS-9: "others can view but not edit" -- the Lead oversees (views)
    # every submitted request, so a refusal is a 403, not a 404.
    if has_relationship or _is_lead_over(user, event):
        return Decision.DENY_FORBIDDEN
    return Decision.DENY_NOT_FOUND


def explain_event_edit_denial(user: Any, event: Any) -> str:
    """The reason given with a 403 from rule_event_edit (IS-9: "update
    attempts are refused with a given reason"). Only called once the rule
    has said DENY_FORBIDDEN, so the caller may already see the event."""
    if (
        _has_role(user, "event_coordinator")
        and _is_assigned_coordinator(user, event)
        and _event_status_in(event, *_COORDINATOR_EDIT_CLOSED)
    ):
        return f"This event is {event.status}, so its details can no longer be updated."
    if _has_role(user, "event_organizer") and _owns_event(user, event):
        return (
            "This event has been submitted, so only its assigned Event Coordinator can update it. "
            "Request a change instead."
        )
    return "Only the Event Coordinator assigned to this event can update it. You can view it, but not edit it."


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

# safety_review added with the Safety Officer (Week 7 change #6): a session
# waiting for its safety check is still before confirmation, so the
# coordinator can still cancel it.
_CANCELLABLE_STATUSES = ("approved", "planning", "safety_review", "confirmed")


def rule_event_cancel(user: Any, event: Any) -> Decision:
    if not (_has_role(user, "event_coordinator") and _is_assigned_coordinator(user, event)):
        return Decision.DENY_NOT_FOUND
    if not _event_status_in(event, *_CANCELLABLE_STATUSES):
        return Decision.DENY_FORBIDDEN
    return Decision.ALLOW


# -- event.reassign_coordinator -------------------------------------------
# Lead only. Week 9 clarification (Sreya): "Is the reassignment of
# coordinators now handled by Event Coordinator Lead role instead of
# offline agreement by coordinators?" -- "yes, it is now manually assigned
# by the lead". That supersedes the Sprint 1 "Coordinator needs
# reassignment" story and the Week 4 answer, under which the CURRENT
# coordinator handed the event over themselves; that path is removed.
# Week 7 change #5 already let the Lead "reassign events where
# necessary", and Week 9 (Shanise) confirms the Lead may reassign even
# after venue and technical arrangements are confirmed.
#
# Relationship first, same shape as rule_event_assign_coordinator: the
# Lead may act on any event that already HAS a coordinator (an
# unassigned one goes through event.assign_coordinator instead). Anyone
# else who can see the event -- its coordinator, its organiser -- gets a
# 403, not a 404: they already know it exists. Everyone else, 404.
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


def rule_event_reassign_coordinator(user: Any, event: Any) -> Decision:
    if not _is_lead_over(user, event):
        if rule_event_view(user, event) is Decision.ALLOW:
            return Decision.DENY_FORBIDDEN
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
#   confirm         safety_review         Week 7 change #6: "The event cannot
#                   -> confirmed          proceed to preparation until the
#                                         Safety Officer has approved it";
#                                         Week 9: "The co-ordinator will
#                                         decide on the subsequent action."
#                                         (Was planning -> confirmed before
#                                         the safety check existed.) The
#                                         route additionally requires the
#                                         latest safety review to be
#                                         approved -- a database fact, so
#                                         it lives in app.safety, not in
#                                         this pure rule. The Confirmed
#                                         Status story's field-locking half
#                                         is still NOT implemented.
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
    return _assigned_coordinator_from(user, event, "safety_review")


def rule_event_complete(user: Any, event: Any) -> Decision:
    return _assigned_coordinator_from(user, event, "confirmed")


# -- event.request_change / event.review_change (IS-21) ---------------------
# Source: IS-21 Request for Event Change.
#
#   request_change  owning organiser. "The Event Organiser can request
#                   permitted changes for an event that has been
#                   submitted" -- every status from submitted up to and
#                   including confirmed. NOT draft or rejected: the
#                   organiser edits those directly (rule_event_edit), so a
#                   change request there would be a detour around their own
#                   form.
#   review_change   the assigned coordinator ("The assigned Event
#                   Coordinator can view and review the requested change"),
#                   in the same status window -- once an event is completed
#                   or cancelled, a still-pending change no longer applies.
#
# Neither widens rule_event_edit: "Given that an event is confirmed, the
# Event Organiser cannot directly overwrite the current confirmed event
# details" stays true because the organiser's edit window is still
# draft/rejected only. A change request is the only way in, and it only
# reaches public.events through review_change.

# safety_review added with the Safety Officer (Week 7 change #6): it sits
# between planning and confirmed, both of which already allow change requests.
CHANGE_REQUEST_STATUSES = ("submitted", "under_review", "approved", "planning", "safety_review", "confirmed")


def rule_event_request_change(user: Any, event: Any) -> Decision:
    if not (_has_role(user, "event_organizer") and _owns_event(user, event)):
        # Anyone else who can see the event (its coordinator, the Lead)
        # already knows it exists: 403, not 404.
        if rule_event_view(user, event) is Decision.ALLOW:
            return Decision.DENY_FORBIDDEN
        return Decision.DENY_NOT_FOUND
    if not _event_status_in(event, *CHANGE_REQUEST_STATUSES):
        return Decision.DENY_FORBIDDEN
    return Decision.ALLOW


def rule_event_review_change(user: Any, event: Any) -> Decision:
    if not (_has_role(user, "event_coordinator") and _is_assigned_coordinator(user, event)):
        # The organiser and the Lead can already see the event (and its
        # change requests), so they learn nothing new from a 403.
        if rule_event_view(user, event) is Decision.ALLOW:
            return Decision.DENY_FORBIDDEN
        return Decision.DENY_NOT_FOUND
    if not _event_status_in(event, *CHANGE_REQUEST_STATUSES):
        return Decision.DENY_FORBIDDEN
    return Decision.ALLOW


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


# -- venue.create / venue.edit / venue.delete (IS-61) -----------------------
# Source: "As a Venue staff, I want to add, edit and delete venues". Venue
# Staff only. Everyone else gets 403, not 404: venues are shared inventory
# every coordinator can already list, so there's no existence to hide (same
# reasoning as rule_room_layout_manage).


def rule_venue_create(user: Any, venue: Any = None) -> Decision:
    if _has_role(user, "venue_staff"):
        return Decision.ALLOW
    return Decision.DENY_FORBIDDEN


def rule_venue_edit(user: Any, venue: Any = None) -> Decision:
    return rule_venue_create(user, venue)


def rule_venue_delete(user: Any, venue: Any = None) -> Decision:
    return rule_venue_create(user, venue)


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
# Status precondition: "planning" only. The Event Status Management
# "Planning Status" story: "the Coordinator has to change the status to
# 'planning' before... searching for a venue". The coordinator does that
# themselves with Start Planning (event.start_planning, approved ->
# planning); requesting a venue no longer moves an approved event there
# as a side effect. See docs/design-decisions.md.


def rule_venue_booking_create(user: Any, event: Any) -> Decision:
    if not (_has_role(user, "event_coordinator") and _is_assigned_coordinator(user, event)):
        return Decision.DENY_NOT_FOUND
    if not _event_status_in(event, "planning"):
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


# -- venue_booking.cancel (IS-9) --------------------------------------------
# Source: IS-9 "Changes or cancellation of one venue arrangement should not
# automatically remove the other venue bookings." The event's CURRENT
# assigned coordinator (not necessarily whoever requested the booking --
# the Lead may have reassigned the event since) cancels one booking that
# is still pending or confirmed, until the event itself is completed or
# cancelled (the same window rule_event_edit gives the coordinator). The
# resource is the booking with its event's coordinator_id and status
# attached (app.venues.routes.load_booking_with_event).


def rule_venue_booking_cancel(user: Any, booking: Any) -> Decision:
    if not (_has_role(user, "event_coordinator") and booking.event_coordinator_id == user.id):
        return Decision.DENY_NOT_FOUND
    if not _booking_status_in(booking, "pending", "confirmed"):
        return Decision.DENY_FORBIDDEN
    if booking.event_status in _COORDINATOR_EDIT_CLOSED:
        return Decision.DENY_FORBIDDEN
    return Decision.ALLOW


def explain_venue_booking_cancel_denial(user: Any, booking: Any) -> str:
    """The reason given with a 403 from rule_venue_booking_cancel."""
    if booking.event_status in _COORDINATOR_EDIT_CLOSED:
        return f"This event is {booking.event_status}, so its venue bookings can no longer be changed."
    return f"This booking is already {booking.status}, so it can't be cancelled."


# -- equipment.* / equipment_request.* (Nawaz, Sprint 2: IS-18) -------------
# Source: Check Equipment Availability -- "As a Technical Support Staff,
# I want to check whether sufficient equipment is available...". Equipment
# is shared inventory (no owner), so equipment.list/view are role-only and
# Technical Support Staff only: the AC names them as the ones who view an
# equipment record's occupancy, and the occupancy lists other events'
# names, which nobody else has a reason to see.
#
# equipment_request.view also admits the coordinator who raised the
# request ("Submitted equipment request is viewable later" -- Record
# Equipment Request AC, whose author is the requester). Any other role
# gets a 404, not a 403: a request's existence is not theirs to know.
# equipment_request.list is role-only and, like rule_venue_booking_list,
# passing it does NOT mean "every request" -- the service scopes a
# coordinator to their own. check_availability is Technical Support Staff
# only: it is their story, and it reveals what OTHER events have reserved.


def rule_equipment_list(user: Any, resource: Any = None) -> Decision:
    if _has_role(user, "technical_support_staff"):
        return Decision.ALLOW
    return Decision.DENY_FORBIDDEN


def rule_equipment_view(user: Any, resource: Any = None) -> Decision:
    return rule_equipment_list(user, resource)


def rule_equipment_request_list(user: Any, resource: Any = None) -> Decision:
    if _has_role(user, "technical_support_staff") or _has_role(user, "event_coordinator"):
        return Decision.ALLOW
    return Decision.DENY_FORBIDDEN


def rule_equipment_request_create(user: Any, event: Any) -> Decision:
    """Record Equipment Request for Event (IS-17). Resource is the EVENT
    (session) the equipment is for, not a request. Exact mirror of
    rule_venue_booking_create: only that event's assigned coordinator (a
    stranger gets the same 404 as a missing event), and only while it is
    in "planning" -- a coordinator starts planning themselves, and a
    request raised before then, or after the event has moved on, would be
    committing equipment to an arrangement that is not being made."""
    if not (_has_role(user, "event_coordinator") and _is_assigned_coordinator(user, event)):
        return Decision.DENY_NOT_FOUND
    if not _event_status_in(event, "planning"):
        return Decision.DENY_FORBIDDEN
    return Decision.ALLOW


def rule_equipment_request_accept(user: Any, request: Any) -> Decision:
    """Accept an equipment request and reserve stock (IS-19). Technical
    Support Staff only (anyone else gets the same 404 as the availability
    check). The AC: "Only requests in a 'pending' status can be accepted".
    Also only while the request's event is still in planning: a request on
    a cancelled event (or one that has moved on) must not take stock, and
    the safety-review gate already requires no pending request by then."""
    if not _has_role(user, "technical_support_staff"):
        return Decision.DENY_NOT_FOUND
    if request.status != "pending":
        return Decision.DENY_FORBIDDEN
    if getattr(request, "event_status", None) != "planning":
        return Decision.DENY_FORBIDDEN
    return Decision.ALLOW


def rule_equipment_request_reject(user: Any, request: Any) -> Decision:
    """Reject an equipment request with a reason (IS-41). Technical Support
    Staff only (anyone else gets the same 404 as accept), and only a
    pending request. Unlike accept, the event's status is NOT checked: a
    pending request left behind on a cancelled or moved-on event must
    still be clearable from Technical Support's queue -- rejecting takes
    no stock, so there is nothing to protect."""
    if not _has_role(user, "technical_support_staff"):
        return Decision.DENY_NOT_FOUND
    if request.status != "pending":
        return Decision.DENY_FORBIDDEN
    return Decision.ALLOW


# -- equipment_change.* (IS-43) ----------------------------------------------
# The event may have moved on from "planning" since the request was accepted
# (safety review, confirmed), and a change to its equipment is still
# legitimate then; it is not once the event is cancelled, completed or
# rejected. `request` below is the equipment request for create, and the
# change request (carrying event_status) for accept/reject.
CHANGEABLE_EVENT_STATUSES = ("planning", "safety_review", "confirmed")


def rule_equipment_change_create(user: Any, request: Any) -> Decision:
    """The coordinator who raised the request asks to change a line's
    quantity. Only a CONFIRMED request has reservations to change (a
    pending one is still just a request -- Technical Support decide it as
    it stands)."""
    if not (_has_role(user, "event_coordinator") and request.requested_by == user.id):
        return Decision.DENY_NOT_FOUND
    if request.status != "confirmed":
        return Decision.DENY_FORBIDDEN
    if getattr(request, "event_status", None) not in CHANGEABLE_EVENT_STATUSES:
        return Decision.DENY_FORBIDDEN
    return Decision.ALLOW


def rule_equipment_change_list(user: Any, resource: Any = None) -> Decision:
    if _has_role(user, "technical_support_staff"):
        return Decision.ALLOW
    return Decision.DENY_NOT_FOUND


def rule_equipment_change_accept(user: Any, change: Any) -> Decision:
    """Technical Support only; a pending change only; and not once the
    event is cancelled/completed/rejected, because accepting moves stock."""
    if not _has_role(user, "technical_support_staff"):
        return Decision.DENY_NOT_FOUND
    if change.status != "pending":
        return Decision.DENY_FORBIDDEN
    if getattr(change, "event_status", None) not in CHANGEABLE_EVENT_STATUSES:
        return Decision.DENY_FORBIDDEN
    return Decision.ALLOW


def rule_equipment_change_reject(user: Any, change: Any) -> Decision:
    """Like accept, but with no event-status gate: rejecting moves no stock,
    and a pending change on a cancelled event should still be clearable."""
    if not _has_role(user, "technical_support_staff"):
        return Decision.DENY_NOT_FOUND
    if change.status != "pending":
        return Decision.DENY_FORBIDDEN
    return Decision.ALLOW


def rule_equipment_type_list(user: Any, resource: Any = None) -> Decision:
    """The equipment catalogue (kinds, not units) is what a coordinator
    picks from on the request form; Technical Support Staff see it too.
    Role-only, nothing per-row: a type name is not sensitive."""
    if _has_role(user, "technical_support_staff") or _has_role(user, "event_coordinator"):
        return Decision.ALLOW
    return Decision.DENY_FORBIDDEN


def rule_equipment_request_view(user: Any, request: Any) -> Decision:
    if _has_role(user, "technical_support_staff"):
        return Decision.ALLOW
    if _has_role(user, "event_coordinator") and request.requested_by == user.id:
        return Decision.ALLOW
    return Decision.DENY_NOT_FOUND


def rule_equipment_request_check_availability(user: Any, request: Any) -> Decision:
    if _has_role(user, "technical_support_staff"):
        return Decision.ALLOW
    return Decision.DENY_NOT_FOUND


# -- equipment.calendar_view (IS-47) ----------------------------------------
# Technical Support Staff only -- the same role as equipment.list/view above,
# NOT rule_venue_calendar_view's coordinator/venue_staff pair. Whether
# Event Coordinators should also see equipment calendars is open for
# Justin (docs/open-questions.md); widening this is one more _has_role.
#
# 404, not 403, for everyone else (AC6: "the same response an unknown unit
# would give"). Unlike equipment.view's 403, the calendar names every event
# the unit is reserved for and when, and a caller with no role in
# equipment has no relationship to the unit at all -- so, per the
# 403-vs-404 rule in docs/authz-usage.md, they are not told it exists.
# Role-only: no per-unit check, so it reads nothing off the resource.


def rule_equipment_calendar_view(user: Any, resource: Any = None) -> Decision:
    if _has_role(user, "technical_support_staff"):
        return Decision.ALLOW
    return Decision.DENY_NOT_FOUND


# -- coordinator.list (role-only -- see actions.py's coordinators section) -
# Only the Event Coordinator Lead assigns and reassigns
# (rule_event_assign_coordinator / rule_event_reassign_coordinator), so
# only they need to see who they could pick. Event Coordinators lost
# this with reassignment (Week 9 clarification): nothing they can do
# needs the list of other coordinators' names and emails.


def rule_coordinator_list(user: Any, resource: Any = None) -> Decision:
    if _has_role(user, LEAD_ROLE):
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
# View Events Without Registration (Justin): attendees can also SEE
# confirmed sessions that don't need registration (public fields only), so
# for viewing, "public" is just "confirmed". Registering for one of those is
# a 403, not a 404 -- the attendee can already see it exists.
#
# The registration PERIOD is not checked here: it's time-based, not a
# property of (user, event), so the database function that records the
# registration checks it (supabase/migrations/20261005000000_registrations.sql).


def _is_public_for_registration(event: Any) -> bool:
    return _event_status_in(event, "confirmed") and getattr(event, "registration_needs", None) is True


def _is_public_to_attendees(event: Any) -> bool:
    """Every confirmed session, whether or not it needs registration."""
    return _event_status_in(event, "confirmed")


def rule_event_register(user: Any, event: Any) -> Decision:
    if _has_role(user, "attendee"):
        if _is_public_for_registration(event):
            return Decision.ALLOW
        return Decision.DENY_FORBIDDEN if _is_public_to_attendees(event) else Decision.DENY_NOT_FOUND
    if rule_event_view(user, event) is Decision.ALLOW:
        return Decision.DENY_FORBIDDEN
    return Decision.DENY_NOT_FOUND


def rule_event_view_public(user: Any, event: Any) -> Decision:
    """The attendee's event page shows only public fields: attendees may
    see every confirmed session, with or without registration. Anything
    else is a 404 to them."""
    if _has_role(user, "attendee"):
        return Decision.ALLOW if _is_public_to_attendees(event) else Decision.DENY_NOT_FOUND
    if rule_event_view(user, event) is Decision.ALLOW:
        return Decision.DENY_FORBIDDEN
    return Decision.DENY_NOT_FOUND


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


# -- room_layout.list / room_layout.manage ----------------------------------
# Source: see ROOM_LAYOUT_LIST / ROOM_LAYOUT_MANAGE in actions.py. Role-only;
# there's no per-row scoping to apply afterwards -- the active list is the
# same for everyone who may read it.

_ROOM_LAYOUT_READERS = ("event_organizer", "event_coordinator", LEAD_ROLE, "venue_staff")


def rule_room_layout_list(user: Any, resource: Any = None) -> Decision:
    if any(_has_role(user, role) for role in _ROOM_LAYOUT_READERS):
        return Decision.ALLOW
    return Decision.DENY_FORBIDDEN


def rule_room_layout_manage(user: Any, resource: Any = None) -> Decision:
    if _has_role(user, "venue_staff"):
        return Decision.ALLOW
    return Decision.DENY_FORBIDDEN


# -- safety_review.* (Week 7 change #6: Operational Feasibility Check) -------
# Source: "After the venue and technical arrangements have been confirmed,
# the Safety Officer must conduct an Operational Safety Check before the
# event can proceed to preparation. ... The Safety Officer may approve the
# event, reject the safety arrangement, or request changes." Week 9: "It is
# similar to Venue and technical approval. The safety officer role will pick
# up the event request and perform the necessary checks and update the
# status of approval with a comment. The co-ordinator will decide on the
# subsequent action."
#
#   submit   the session's assigned coordinator, from planning only
#            (resource: the EVENT, like venue_booking.create). Whether its
#            arrangements are actually ready (a confirmed venue, nothing
#            pending) is a database fact checked by
#            app.safety.safety_service.submit_for_safety_check, not here.
#   list     role-only, safety_officer. Same *** WARNING *** as
#            rule_venue_booking_list: list_reviews does its own role check.
#            Every Safety Officer sees every review (no assignment step --
#            team decision, flagged in docs/open-questions.md).
#   view     any safety_officer; anyone else 404. The coordinator reads a
#            session's reviews via GET /events/<id>/safety-reviews (gated by
#            event.view), so they need no access to the officer's view.
#   approve / reject / request_changes
#            any safety_officer, review must still be pending; same shape as
#            rule_venue_booking_approve/reject.

SAFETY_OFFICER_ROLE = "safety_officer"


def rule_safety_review_submit(user: Any, event: Any) -> Decision:
    return _assigned_coordinator_from(user, event, "planning")


def rule_safety_review_list(user: Any, resource: Any = None) -> Decision:
    if _has_role(user, SAFETY_OFFICER_ROLE):
        return Decision.ALLOW
    return Decision.DENY_FORBIDDEN


def rule_safety_review_view(user: Any, review: Any) -> Decision:
    if _has_role(user, SAFETY_OFFICER_ROLE):
        return Decision.ALLOW
    return Decision.DENY_NOT_FOUND


def rule_safety_review_approve(user: Any, review: Any) -> Decision:
    if not _has_role(user, SAFETY_OFFICER_ROLE):
        return Decision.DENY_NOT_FOUND
    if review.status != "pending":
        return Decision.DENY_FORBIDDEN
    return Decision.ALLOW


def rule_safety_review_reject(user: Any, review: Any) -> Decision:
    # Same precondition as approve, kept separate per "WHY SEPARATE ACTIONS".
    return rule_safety_review_approve(user, review)


def rule_safety_review_request_changes(user: Any, review: Any) -> Decision:
    return rule_safety_review_approve(user, review)
