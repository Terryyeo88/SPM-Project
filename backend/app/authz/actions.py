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
(GET /me needs no policy check at all; see app/me/routes.py). Editing
your own profile does have one: PROFILE_EDIT_OWN (IS-68), below.
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
# Source: Week 7 change #5 / Week 9 clarification -- the Event
# Coordinator Lead assigns and reassigns, so they need the list of Event
# Coordinators to choose from (the Lead dashboard's pickers). Role-only:
# it lists names/emails of staff, not anything tied to a particular event.

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
# was read-only in Sprint 1; IS-61 added venue.create/edit/delete below.
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

# -- venue management (IS-61: CRUD in Venue Catalogue) -----------------------
# Source: "As a Venue staff, I want to add, edit and delete venues so that I
# can easily manage what venues ConnectSphere currently has." Role-only, like
# VENUE_LIST: a venue has no owner. Three actions, not one "manage", per
# rules.py's "WHY SEPARATE ACTIONS" -- each AC is its own decision.
VENUE_CREATE = "venue.create"
VENUE_EDIT = "venue.edit"
VENUE_DELETE = "venue.delete"

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
# venue_booking.cancel (IS-9): the event's assigned coordinator cancels one
# pending or confirmed booking; the session's other bookings stay as they are.
VENUE_BOOKING_CANCEL = "venue_booking.cancel"

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

# -- record equipment request (IS-17: Record Equipment Request for Event) ---
#   equipment_request.create -- the assigned coordinator, while the event is
#       in "planning" (same gate as venue_booking.create; Aaralyn's IS-9
#       note asks whoever builds this to require planning).
#   equipment_type.list -- the catalogue of kinds of equipment a request can
#       name, which the request form needs and equipment.list (Technical
#       Support only) does not give a coordinator.
EQUIPMENT_REQUEST_CREATE = "equipment_request.create"
# equipment_request.accept (IS-19): Technical Support Staff accept a pending
# request and reserve units for it. Reject is the separate IS-41 action.
EQUIPMENT_REQUEST_ACCEPT = "equipment_request.accept"
# equipment_request.reject (IS-41): Technical Support Staff reject a pending
# request with an explanation the coordinator can read.
EQUIPMENT_REQUEST_REJECT = "equipment_request.reject"
# equipment_change.* (IS-43): the coordinator asks to change the quantity on
# an already-confirmed request line; Technical Support accept or reject it.
EQUIPMENT_CHANGE_CREATE = "equipment_change.create"
EQUIPMENT_CHANGE_LIST = "equipment_change.list"
EQUIPMENT_CHANGE_ACCEPT = "equipment_change.accept"
EQUIPMENT_CHANGE_REJECT = "equipment_change.reject"
EQUIPMENT_TYPE_LIST = "equipment_type.list"

# -- equipment calendar (IS-47: View Equipment Availability Calendar) -------
# Source: IS-47 AC1 "A technical support staff member can open an equipment
# unit and see its reservation calendar" and AC6 "Only technical support
# staff can view the calendar. Anyone else gets the same response an
# unknown unit would give." A separate action from equipment.view, as
# venue.calendar_view is from venue.view: the two answer differently to a
# non-staff caller (404 here, 403 there -- see rule_equipment_calendar_view).
EQUIPMENT_CALENDAR_VIEW = "equipment.calendar_view"

# -- room layouts ----------------------------------------------------------
# Source: room layout types are filled in by Venue Staff, who can add,
# update and delete them (they used to be a fixed enum -- see
# supabase/migrations/20261012000000_room_layouts.sql). Both role-only:
# a layout has no owner, it's shared reference data.
#
#   room_layout.list   -- everyone who fills in or works with an event's
#       layout reads the active list (the organiser's request form, the
#       coordinator's edits and change requests, the Lead, Venue Staff).
#   room_layout.manage -- Venue Staff add, rename, soft-delete, restore and
#       permanently delete layouts, and see soft-deleted ones.
ROOM_LAYOUT_LIST = "room_layout.list"
ROOM_LAYOUT_MANAGE = "room_layout.manage"

# -- safety reviews (Week 7 change #6: Operational Feasibility Check) --------
# Source: "After the venue and technical arrangements have been confirmed,
# the Safety Officer must conduct an Operational Safety Check ... The Safety
# Officer may approve the event, reject the safety arrangement, or request
# changes." Week 9: "It is similar to Venue and technical approval. The
# safety officer role will pick up the event request ... and update the
# status of approval with a comment." Same split as venue bookings: the
# assigned coordinator submits, a Safety Officer decides.
#
#   safety_review.submit           -- the coordinator sends a planning
#       session for its check (resource: the event).
#   safety_review.list / .view     -- the Safety Officer's dashboard and one
#       review. The coordinator sees a session's reviews through
#       GET /events/<id>/safety-reviews, gated by event.view instead.
#   safety_review.approve / .reject / .request_changes -- the three
#       decisions, separate actions for the same reason approve/reject are
#       (see rules.py, "WHY SEPARATE ACTIONS").
SAFETY_REVIEW_SUBMIT = "safety_review.submit"
SAFETY_REVIEW_LIST = "safety_review.list"
SAFETY_REVIEW_VIEW = "safety_review.view"
SAFETY_REVIEW_APPROVE = "safety_review.approve"
SAFETY_REVIEW_REJECT = "safety_review.reject"
SAFETY_REVIEW_REQUEST_CHANGES = "safety_review.request_changes"

# -- notifications (IS-69: Notification System) -------------------------------
# Source: the stories that say a person "is notified" (IS-14 "An approved
# booking should notify the Coordinator", IS-41 "an explanation that's sent
# to the Event Coordinator", Week 7 change #5 "Relevant users should be
# notified when assignments or reassignments occur", ...) -- IS-69 builds
# where those notifications land. Every authenticated role can receive one,
# so none of these is role-gated.
#
#   notification.list          -- your own notifications and unread count
#       (role-free; the query is scoped to the caller -- see the rule).
#   notification.mark_read     -- one notification, recipient only.
#   notification.mark_all_read -- every one of your own (no resource).
NOTIFICATION_LIST = "notification.list"
NOTIFICATION_MARK_READ = "notification.mark_read"
NOTIFICATION_MARK_ALL_READ = "notification.mark_all_read"

# -- profile (IS-68: User contact and preferences) -----------------------------
# Source: IS-68, the Edit Profile wireframe's Phone Number, Organisation and
# Communication Preferences -- a user keeps their own contact details.
#
#   profile.edit_own -- PATCH /me/profile, the caller's own profile. Role-free
#       and resource-free: the route takes no id, so there is no other
#       profile it could be pointed at (see rule_profile_edit_own).
PROFILE_EDIT_OWN = "profile.edit_own"
