"""
Action constants for the authorisation policy (app.authz.policy).

Plain strings, not an enum -- callers pass these directly to can()/
authorise(), and they need to read cleanly in a route decorator and a
traceback alike. Grouped by resource; "event.*" is everything this
schema (public.events) can express today.

Every action here traces to a specific acceptance criterion or user
story clarification -- see app/authz/rules.py's module docstring for the
rule built against each one, and docs/traceability.md for the test that
proves it. "The schema could technically support it" is not a source on
its own -- see rules.py's docstring on EVENT_LIST / EVENT_CREATE for why
that distinction matters.

Deliberately NOT here: anything about equipment REQUEST CREATION or
RESERVATION (the "Record Equipment Request" and "Accept an equipment
request" stories are not built -- whoever builds them should add their
own actions the same way, sourced the same way), and no profile.view_*
(GET /me needs no policy check at all; see app/me/routes.py).
"""

from __future__ import annotations

# -- events ------------------------------------------------------------

EVENT_VIEW = "event.view"
EVENT_LIST = "event.list"
EVENT_CREATE = "event.create"
EVENT_SUBMIT = "event.submit"
EVENT_EDIT = "event.edit"
EVENT_DELETE = "event.delete"
EVENT_APPROVE = "event.approve"
EVENT_REJECT = "event.reject"
EVENT_REQUEST_CLARIFICATION = "event.request_clarification"
EVENT_CANCEL = "event.cancel"
EVENT_REASSIGN_COORDINATOR = "event.reassign_coordinator"
# Week 7 change #5 (Event Coordinator Lead): "Newly submitted event
# requests ... first enter an unassigned queue ... The Lead can review
# basic event information, assign a suitable Event Coordinator".
EVENT_ASSIGN_COORDINATOR = "event.assign_coordinator"

# Lifecycle after approval (IS-36 / IS-38, plus confirm for end-to-end
# testability -- see rules.py). Each is one edge in
# app.events.transitions.ALLOWED; the rule checks who may take it, the
# transition checks that it is legal.
EVENT_START_PLANNING = "event.start_planning"
EVENT_CONFIRM = "event.confirm"
EVENT_COMPLETE = "event.complete"

# IS-21 Request for Event Change: "The Event Organiser can request
# permitted changes for an event that has been submitted" (request) and
# "The assigned Event Coordinator can view and review the requested
# change" (review = approve or reject). Viewing reuses EVENT_VIEW.
EVENT_REQUEST_CHANGE = "event.request_change"
EVENT_REVIEW_CHANGE = "event.review_change"

# -- coordinators --------------------------------------------------------
# Source: "Coordinator needs reassignment" -- the current coordinator
# picks who to hand the event to, so they need the list of other Event
# Coordinators to choose from (the Reassign dropdown on the coordinator's
# event review page). Role-only: it lists names/emails of staff, not
# anything tied to a particular event.

COORDINATOR_LIST = "coordinator.list"

# -- registrations (Justin: Attendee Registration) ----------------------
# Source: "As an Attendee, I want to register for an event, so that I can
# secure a place to attend the event." EVENT_REGISTER is per session (the
# session must be confirmed and enabled for registration);
# REGISTRATION_LIST is role-only -- browsing the sessions open to
# attendees and seeing your own registrations.

EVENT_REGISTER = "event.register"
EVENT_VIEW_PUBLIC = "event.view_public"  # the attendee's event page: public fields only
REGISTRATION_WITHDRAW = "registration.withdraw"
REGISTRATION_LIST = "registration.list"

# -- venues (Nawaz, Sprint 1: View Venue Catalogue) ---------------------
# Source: "As an Event Coordinator, I want to see venue details so that
# I can find the appropriate venue for the event request." The catalogue
# is read-only in Sprint 1 -- no venue.create/edit/delete actions exist
# yet because no story asks for them; whoever builds venue management
# later should add those the same way, sourced the same way.
#
# Both role-only, same shape as EVENT_LIST/EVENT_CREATE (see that
# section's warning above `rule_event_list` in rules.py) -- a venue
# record has no owner to check a relationship against, so "can this role
# view venues at all" is the whole question. Unlike events there is no
# per-row scoping the caller must additionally apply: the catalogue is
# shared inventory, not scoped to who is asking, so VENUE_VIEW/VENUE_LIST
# passing really does mean "show them the record", full stop.

VENUE_VIEW = "venue.view"
VENUE_LIST = "venue.list"

# -- venue calendar (Nawaz, Sprint 2: View Venue Availability Calendar,
# IS-11) ------------------------------------------------------------
# Source: "As a Venue Staff member, I want to view a calendar of a
# venue's availability so that I can see what is already committed
# before deciding on a new booking request." AC: "Can only view
# calendars for venues the user's role permits" -- the AC doesn't name
# any role beyond Venue Staff, but the story is purely a read over the
# same venue record VENUE_VIEW already gates, and Event Coordinators
# already see this same data in a cruder form today (the venues.status
# flag on VenueDetailView) -- denying them the real calendar while
# granting the crude flag would be a regression, not a stricter read of
# the AC. A separate action (not reusing VENUE_VIEW) because the two
# could plausibly diverge later (e.g. if a story ever wants the
# catalogue visible to a role the calendar shouldn't be) -- flagged in
# docs/open-questions.md, same as rule_venue_list's own venue_staff
# inference above.

VENUE_CALENDAR_VIEW = "venue.calendar_view"

# -- venue bookings (Josiah, Sprint 2: Venue Booking Request / Approval) --
# Source: "As an Event Coordinator, I want to submit a request to book a
# venue for an event" (create) and "As a Venue Staff member, I want to
# review pending venue booking requests and approve or reject them"
# (approve/reject). Role split per rule_venue_list's own comment above,
# which already anticipated this: event_coordinator requests,
# venue_staff decides -- both inferred, not literal story text, flagged
# in docs/open-questions.md same as that comment already is.

VENUE_BOOKING_CREATE = "venue_booking.create"
VENUE_BOOKING_VIEW = "venue_booking.view"
VENUE_BOOKING_LIST = "venue_booking.list"
VENUE_BOOKING_APPROVE = "venue_booking.approve"
VENUE_BOOKING_REJECT = "venue_booking.reject"

# -- equipment (Nawaz, Sprint 2: IS-18 Check Equipment Availability) --------
# Source: "As a Technical Support Staff, I want to check whether sufficient
# equipment is available for a requested date and time so that I can
# confirm or flag equipment requests." Four read-only actions; none of
# them changes anything (accepting/rejecting a request is a different
# story).
#
#   equipment.list / equipment.view -- AC: "When viewing an equipment
#       record, the Technical Support Staff can view when the equipment is
#       occupied along with the event that it is reserved for".
#   equipment_request.list / equipment_request.view -- AC: "Can select an
#       equipment request and view the required date and time" and
#       "Submitted equipment request is viewable later".
#   equipment_request.check_availability -- the story itself.
EQUIPMENT_LIST = "equipment.list"
EQUIPMENT_VIEW = "equipment.view"
EQUIPMENT_REQUEST_LIST = "equipment_request.list"
EQUIPMENT_REQUEST_VIEW = "equipment_request.view"
EQUIPMENT_REQUEST_CHECK_AVAILABILITY = "equipment_request.check_availability"
