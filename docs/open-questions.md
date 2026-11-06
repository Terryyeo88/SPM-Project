# Open questions

Things IS-1 decided and implemented, but that should still get explicit
customer confirmation rather than staying as our best reading of the
stories. Not implementation gaps — each of these has a decision already
made and recorded in `docs/design-decisions.md`; this file is the list of
decisions worth double-checking.

- **event.cancel's status range.** The Cancelled Status story says
  "after approval of the event request". We implemented that as the range
  `approved, planning, confirmed` (excluding `completed`), reasoning that
  the story's own scenario (coordinator can't secure a venue/equipment)
  happens during planning, not at the instant of approval — see
  `docs/design-decisions.md` §event.cancel. Please confirm "after approval"
  was meant as that range and not literally the single status `approved`.

- **"Routed to a view appropriate to their role" (IS-27).** Implemented
  as one Dashboard route for every role after login, whose own content
  (which nav links it shows) adapts by role — see
  `frontend/src/lib/roles.js`'s module docstring for the reasoning. This
  still holds now that Events/Create Event/Event Details are real pages
  (Aaralyn's IS-3/IS-4 work), not placeholders: the dashboard is a
  landing page users are routed to after login, not itself the
  role-specific view — reaching the create-event form or an event's
  detail page is normal in-app navigation from there, no different from
  clicking into Venues once that's built. Please confirm this reading is
  acceptable, or whether separate landing pages per role are expected
  straight after login instead.

- **Which roles reach which sections (IS-27).** `frontend/src/lib/
  roles.js`'s `ROUTE_ACCESS` table (the single source both the dashboard
  nav and the router's role gate read from) allows: Events and Create
  Event to event_organizer/event_coordinator and event_organizer only
  respectively (Event Request Creation is organiser-only per its own
  story); Venues to event_coordinator/venue_staff (quoting the Week 4
  instructions' Venue Catalogue description); an event's own detail page
  to event_coordinator (plus event_organizer, since an organiser can
  view/edit their own event). The coordinator-only Reassign Coordinator
  page was removed in Sprint 3 (only the Lead reassigns -- Week 9). This mapping isn't specified anywhere in the stories — it's
  inferred per-route from which story or authz rule owns that feature.
  attendee and technical_support_staff currently unlock nothing on the
  dashboard (see `docs/traceability.md`'s "Explicitly deferred" —
  nothing built for those roles yet this sprint). Please confirm this
  mapping, especially whether Attendee/Technical Support Staff should
  see something else instead of the current fallback message.

- **Venue "availability" is a manual status, not a real calendar.** The
  View Venue Catalogue story's acceptance criterion ("the availability of
  the venue tells the Event Coordinator when the venue is occupied and
  when it is available") reads like it wants an actual occupied/free
  calendar. That calendar is a separate story (Venue Availability
  Calendar), driven by real bookings — and the booking tables it would
  read from (Venue Booking Request/Approval) are explicitly out of scope
  for Sprint 1. Until those exist, `venues.status` is a single
  manually-set flag (`available` / `occupied` / `maintenance`) per venue,
  not derived from any booking data — see
  `supabase/migrations/20260923000000_venues.sql`'s own comments. Please
  confirm this reading is right, and that a real calendar is expected
  once bookings exist rather than this flag being the intended final
  behaviour.

- **Venue Staff granted the same catalogue access as Event Coordinator.**
  The View Venue Catalogue story is written only for the Event
  Coordinator role. We additionally granted `venue_staff` the same
  `venue.view`/`venue.list` access (see `rule_venue_list` in
  `app/authz/rules.py`), reasoning that Venue Staff need to see the same
  venue details when they later approve or reject bookings against these
  records (Venue Booking Approval story). This is our own inference, not
  a line from the story text — please confirm Venue Staff should have
  this access.

- **~~Three orphan columns on `events`: who owns them?~~ Resolved: now in
  use by multi-session event requests.** `shared_event_id` links the
  sessions of one event request. Each session is its own `events` row, and
  the id is generated server-side in `app.events.event_service` when the
  request is first created. `registration_start_datetime` and
  `registration_end_datetime` hold each session's registration window,
  which is required when `registration_needs` is true. The "ORPHAN" comments
  in `20260927000000_reconcile_events_with_live.sql` are out of date. They
  were left as is because that migration has already been applied.

- **Venue Staff granted blanket access to every venue's bookings (no
  per-venue-staff-assignment table).** The Venue Booking Approval story
  says "As a Venue Staff member, I want to review pending venue booking
  requests and approve or reject them" — it doesn't say whether a Venue
  Staff member is tied to specific venues or sees every venue's queue.
  No table links a Venue Staff member to the venue(s) they cover, so
  `rule_venue_booking_list`/`rule_venue_booking_approve`/`rule_venue_
  booking_reject` (`app/authz/rules.py`) and
  `app.venues.booking_service.list_bookings` are role-only: any
  `venue_staff` sees and can decide every venue's pending bookings, same
  inference already made for `venue.view`/`venue.list` above. Please
  confirm this is acceptable, or whether Venue Staff should be scoped to
  specific venues (which would need a new assignment table, out of scope
  for this sprint).

- **Resolved 2026-10-15: the coordinator starts planning explicitly (Start
  Planning), and venue requests require `planning`.** Original question:
  **The `approved → planning` transition is a side effect of requesting a
  venue, not its own feature.** The Event Status Management "Planning
  Status" story implies a Coordinator explicitly moves an event to
  `planning` before searching for a venue/equipment, but nothing in this
  codebase transitions an event TO `planning` (that sub-story is
  unassigned). `app.venues.booking_service.create_booking_request`
  performs that transition itself, narrowly, as a side effect of the
  FIRST venue booking request against an `approved` event — see
  `docs/design-decisions.md` §approved→planning for the full reasoning.
  Please confirm this reading (starting a venue search IS what moves an
  event to planning) rather than expecting a separate, explicit
  "Start Planning" action.

- **A cancelled event's CONFIRMED venue booking is never released.**
  `venue_booking_status` has three values — `pending`, `confirmed`,
  `rejected` — no `cancelled`. The Cancelled Status story (now built on
  `main`) lets a coordinator cancel an event from `approved`, `planning`
  OR `confirmed`, which means an event with an already-`confirmed` venue
  booking can be cancelled while that booking still holds the venue.
  Nothing today moves the booking off `confirmed` when that happens, so
  the venue stays blocked for a period nobody is using it for any more.
  Raised in code review (2026-10-05) and logged here rather than decided
  unilaterally, since the right fix affects other work reading booking
  status. Options on the table for Thursday, not yet chosen between:
    1. Add `cancelled` to `venue_booking_status` and release the booking
       as a side effect of the event's `* → cancelled` transition — same
       pattern as `create_booking_request`'s own `approved → planning`
       side effect above.
    2. Reuse `rejected` with a system-generated reason — no schema
       change, but `rejected` then means two different things (Venue
       Staff declined it / the event it belonged to was cancelled),
       which muddies `get_booking`'s `rejection` field for anyone
       reading it later.
    3. Leave the booking row `confirmed` and treat the event's own
       `cancelled` status as the authoritative signal instead — cheapest,
       but `confirmed` then stops reliably meaning "this venue is held"
       without also checking the event it belongs to.
  No option is implemented yet — this is a modelling decision to make,
  not a bug to silently work around.

- **Test-suite network gap: JWKS is still fetched over the wire.** The
  unit-test guard (`tests/conftest.py`) blocks the *database* but not the
  *network*. A unit test that sends a real bearer token without the
  `signing_key` fixture makes `app.auth.jwt` fetch the signing keys from
  `SUPABASE_URL/auth/v1/.well-known/jwks.json` for real. It's read-only
  against a public endpoint, so the risk is low. But it makes the suite
  slower and flaky offline or behind a firewall, and the failure looks like
  a network or auth error rather than "this test forgot its fixture". The
  fix would be the same shape as the database guard: an autouse fixture
  that makes `app.auth.jwt._http_get_json` raise a named error unless a
  test installs a key. Not done yet.

- **IS-39: "Organizer is notified of cancellation and reason" — blocked on
  notifications.** The cancel route stores the reason and returns it, and
  the organiser can read it via `GET /events/<id>/status-history`, but
  nothing *notifies* them. No notification system exists (the only hook is
  `coordinator_service._notify_coordinator_assigned`, a `print()`
  placeholder). This half of IS-39 depends on the Notification System
  story. It was deliberately not built here.

- **Confirmed Status story: field-locking is NOT built.** `POST
  /events/<id>/confirm` exists only so IS-38 (confirmed → completed) is
  reachable end to end. The story also says "once confirmed, information
  fields should not be changed unless there is a change that was
  permitted". That is not implemented, and "a change that was permitted" is
  undefined. It needs its own ticket and a definition of which changes are
  permitted.

- **IS-36: venue/equipment requests are tied to planning (updated
  2026-11-06).** When this was first written there was no venue-request
  route and no equipment, so the original "status gates venue/equipment
  search" couldn't be built. Both exist now, and the team reworded the ACs
  to be about requests:
  - *AC1, "planning" only from "approved"*: met (`rule_event_start_planning`).
  - *AC2 and AC4, requests only while in planning; requesting otherwise is
    blocked*: met. `rule_venue_booking_create` and
    `rule_equipment_request_create` refuse (403) unless the event is in
    `planning`, whatever page or tool sends the request.
  - *AC3, planning unlocks the request actions*: met. "Request Venue
    Booking" and "Request Equipment" are offered on the event page only in
    `planning`.

  Browsing the venue list (`/venues`) and the equipment calendar is not
  gated. They aren't tied to any one event (a coordinator usually has events
  in several statuses at once, so there's no single status to check), and
  Venue Staff and Technical Support use them too.

  Small difference, not an AC gap: the equipment request page hides its form
  outside planning, while the venue request page
  (`/events/<id>/request-venue-booking`), if opened directly by URL, still
  shows its form and only refuses on submit. Hiding it would match the two;
  please say if that's wanted.

- **Should reassignment also be refused for `cancelled` / `rejected`
  events?** IS-38 made reassignment refuse `completed` events ("completed
  events are read-only going forward"). No story says the same for
  `cancelled` or `rejected`, so those still allow reassignment. Reassigning
  the coordinator of a cancelled event seems pointless. For a rejected
  event it may be legitimate before resubmission. Please confirm.

- **Resubmission doesn't check that the organiser changed anything.** The
  story says a rejected request "can be re-submitted for review *after the
  Organizer makes changes*". We don't enforce the "after changes" part.
  Doing so would mean diffing against the last submitted version, which no
  acceptance criterion asks for. An organiser can resubmit a rejected
  request unchanged.

- **`event_status_log` RLS (for the RLS-tightening work, not IS-36/38/39).**
  Its policy `"authenticated write status log"` lets *any* authenticated
  user insert audit rows directly through PostgREST with the anon key,
  bypassing Flask. That means anyone can forge history. Its two `create
  policy` statements also have no `drop policy if exists` guard, so
  `20260929000000_event_status_log.sql` fails if re-run, unlike the other
  migrations. Both belong to the RLS pass.

## Week 7 change #5 — Event Coordinator Lead

- **Notifications are not built.** The change asks that "relevant users
  should be notified when assignments or reassignments occur". There is
  still no notification system. Assignment and reassignment both call
  `coordinator_service._notify_coordinator_assigned`, which only logs a
  line, so plugging the real notification in there covers the Lead's
  assign and reassign too. Until then, don't count change #5 as complete.

- **"Active events under their supervision" read as every event.** The
  brief has no coordinator teams, so we read it as: the Lead sees every
  submitted event (any status except `draft`). Drafts stay private to
  their organiser because they haven't been submitted to anyone. If Leads
  are meant to supervise only some coordinators, a coordinator-to-Lead
  link is needed.

- **A resubmitted request keeps its coordinator.** Change #5 is about
  *newly* submitted requests. A rejected request that the organiser
  resubmits still goes straight back to the coordinator who rejected it
  (`under_review`), not into the Lead's queue. The Lead can reassign it if
  needed.

- **The Lead can't approve, reject or edit.** Nothing in change #5 gives
  the Lead the coordinator's review actions, so their event pages are
  read-only apart from assign and reassign.

- **Automatic assignment code is kept but no longer used on submit.**
  `assign_initial_coordinator` still picks a coordinator by workload when
  called without `coordinator_id`. Nothing in the app does that now. It
  could become a "suggest a coordinator" option for the Lead, or be
  removed.

## Attendee Registration

- **"Required registration information" read as a fixed set.** No source
  says what it is, or that organisers design their own forms. We ask for
  email, phone and preferred contact method (email or phone), all required,
  plus optional notes. Email prefills from the profile. Profiles don't have
  phone or a contact preference yet (the briefing's "User Profile
  Management" mentions both, but no story covers it); if one is added, the
  form prefills them too. Confirm whether organisers need custom questions.

- **Capacity is `expected_attendance`.** It is the organiser's planning
  estimate. If it is lowered after people register, existing confirmed
  registrations stay confirmed; only new registrations are affected.

- **A freed place goes straight to the next person on the waiting list.**
  Week 2 says "eligible attendees are notified when a slot opens up to
  apply", which could mean they're offered the place rather than given it.
  We move them up automatically, and since IS-22 they're notified that
  their registration is now confirmed. Confirm.

- **Not built yet:** editing a registration after submitting it, and
  organiser/coordinator views of who registered. (Attendee notifications:
  IS-22.)

- **Organiser "discretion" and manual closing (IS-20 AC6, AC8) --
  justified by the clarifications.** Week 4: "At the moment closure is
  based on Organiser discretion and manually close the registration. **The
  team may propose other better approach.**" Our proposal: the organiser
  sets each session's registration window (opens / closes) when creating
  the request, and that window is what opens and closes registration --
  closing early means moving the close time. Week 2 frames the discretion
  as over the *conditions*, not over individual attendees: "Waiting list
  operates on a first-come, first-served priority ... **Organisers have
  discretion over registration/withdrawal conditions.**" Organisers set
  those conditions (registration needed or not, the window, the session's
  expected attendance as its capacity); places are then first-come,
  first-served with a waiting list, as stated. There is no hand-picking of
  attendees. Please confirm this proposal is acceptable.

- **No confirmed events exist the normal way yet.** Confirming needs venue
  and equipment work that isn't built, so the seed creates a confirmed
  "Registration Demo" request directly, without status history.


## Venue booking conflicts (IS-16) and equipment calendar (IS-47) — still blocked (5 Oct)

- **IS-16 waits on PR #18 (IS-14, Josiah).** `venue_bookings` is not on
  main and not on the live database. It exists only in PR #18, which is
  open and has merge conflicts. IS-16 is not built until #18 merges, so we
  don't write a second version of Josiah's table.

- **Resolved (1dc8dfb, 5 Oct): PR #18's migration timestamp was already
  used on main.** PR #18 added `20261004000000_venue_bookings.sql`. Main
  already had `20261004000000_coordinator_lead_role.sql`. Supabase
  identifies migrations by that number, so two files sharing it would clash
  on `db reset`. Git doesn't flag this because the file names differ.
  Commit 1dc8dfb renamed the file to `20261005100000_venue_bookings.sql`.

- **What IS-16 will build on once #18 merges.** PR #18 already stores the
  occupied period (`booking_start`/`booking_end`, including setup and
  turnaround). It also checks in the app for an overlapping confirmed
  booking before it confirms one. IS-16 adds a btree_gist exclusion
  constraint on confirmed rows, which removes the race in that
  check-then-write, plus the overlap query that shows Venue Staff which
  bookings clash. One open point: #18's `venue_booking_status` has no
  `cancelled` value, so a cancelled booking can only show up as `rejected`
  for now. Either way it stops blocking, because only confirmed rows are
  covered by the constraint.

- **IS-47's data.**
  - **Resolved: per unit, not per type.** `20261008000000_equipment.sql`
    (IS-18) tracks equipment at unit level, following IS-18's AC. Its
    `equipment_reservations` table names one physical unit per row. That
    migration also created the inventory and reservation tables this item
    said were missing.
  - **Built anyway (IS-47, 16 Oct), on these readings -- please confirm:**
    the calendar is per unit and shows booked/free (a reserved day names
    the event). It is visible to Technical Support Staff only. It reads
    reservations, which `supabase/seed.sql` provides for demos. See "View
    Equipment Availability Calendar (IS-47)" below.
  - **Still open, for Justin (PO):** which story creates the reservations
    (nothing in the app writes them yet), and whether coordinators should
    see equipment calendars too.

## Booking conflicts (IS-16)

- **A CI check would have caught a direct status write structurally.**
  PR #18 wrote `events.status` directly in `booking_service`, bypassing
  `transition()`. It was only caught because someone read the service
  layer during review. A CI step that fails when
  `.update({"status"` appears on `events` outside
  `app/events/transitions.py` would catch it every time. It needs care:
  `venue_bookings` and `registrations` legitimately update their own
  `status`, so it can't be a bare grep. Recorded, not built.

- **Should the requesting coordinator see the names of clashing events?**
  `GET /venues/bookings/<id>/conflicts` reuses `VENUE_BOOKING_VIEW`, so the
  coordinator who requested a booking sees the same clash list as Venue
  Staff, including the other event's name. That helps them pick another
  slot, but it shows them another organiser's event. If it should be Venue
  Staff only, it needs its own action and rule.

- **The UI doesn't show the clash list yet.** The route exists. Showing it
  on `VenueBookingReviewView.vue` is a frontend change in Josiah's view.

## Venue Availability Calendar (IS-11, Nawaz, 7 Oct)

- **"Tentatively held" vs "confirmed" is derived, not a new booking
  status.** The Sep 9 planning call resolved this: a venue booking is
  "tentatively held" once Venue Staff approve it, then becomes
  "confirmed" once the EVENT itself reaches `confirmed` status.
  `calendar_service.get_venue_calendar` computes this live, by joining
  `venue_bookings.status = 'confirmed'` against `events.status`, rather
  than adding a fourth value to `venue_booking_status`. If that reading
  of the transcript is wrong, the fix is in one place (the `state`
  derivation in `calendar_service.py`), not a schema change.

- **"Blocked" periods got a new table (`venue_blocks`), not a reuse of
  the old `venues.status` flag.** That flag has no date range and no
  reason text, and was already documented in Sprint 1 as a placeholder
  "until [booking tables] exist." This migration only lets the calendar
  READ blocks -- creating one is still "Venue Becomes Unavailable
  (blocking)", an explicitly separate, unassigned story (see
  `20261005100000_venue_bookings.sql`'s and `booking_service.py`'s own
  docstrings). Until that story is built, rows in `venue_blocks` only
  come from `seed.py` -- there is no in-app way for Venue Staff to block
  a venue yet, even though the wireframe draws that flow.

- **Block reasons are a closed enum, not free text.** The AC's example
  list ("maintenance, renovation, internal activity") and the
  wireframe's own dropdown both suggest a fixed set
  (`venue_block_reason`: maintenance / renovation / safety_issue /
  internal_activity / other). Worth confirming with Justin before
  "Venue Becomes Unavailable" is built against it, same as any other
  assumed closed set in this schema.

- **Event Coordinators can view the calendar, not just Venue Staff.**
  The AC's user story only names "As a Venue Staff member... so that I
  can see what is already committed before deciding on a new booking
  request," but Coordinators already see a cruder version of the same
  data today (the Sprint 1 `venues.status` flag on the venue detail
  page) -- denying them the real calendar would be a regression, not a
  stricter reading. Same role pair as `VENUE_VIEW`/`VENUE_LIST`, flagged
  the same way those were in Sprint 1.

- **Resolved (6 Nov): operating hours are now marked on the calendar.**
  Previously only a text note. The time outside a venue's hours is now
  shown as unavailable (day and week views list the closed periods; the
  month grid shows the hours on every day) -- see "Operating hours
  (IS-11 AC5)" below.

## Venue Search and Suitability Checking (IS-12 / IS-13, Nawaz, 7 Oct)

- **Both stories live inside the booking-request flow
  (`RequestVenueBookingView.vue`), not as a separate search page.** IS-12's
  user story talks about shortlisting candidates generically, but the one
  place a Coordinator is actually choosing a venue for a specific event is
  this screen, so that's where filtering (IS-12) and the suitability check
  (IS-13) were built. If the team wants a standalone "browse/search all
  venues" page independent of any one event, that's a different screen to
  add later -- this doesn't block it, `lib/venueSearch.js`'s `filterVenues`
  is already a plain, reusable function.

- **IS-13 got its own `checkSuitabilityForEvent` function, not a reuse of
  Josiah's `checkSuitability`.** That one (used by Venue Staff's Booking
  Review screen) silently OMITS a check when the event hasn't recorded
  that requirement -- its own tests pin that down. IS-13's AC explicitly
  wants the opposite ("the check reports which requirements were not
  assessed"), so changing the shared function would have broken Josiah's
  screen for a requirement it was never asked to meet. Two functions,
  not one, is deliberate here.

- **"Facility arrangements" are part of accessibility needs -- effectively
  met (IS-3 AC4, IS-13 AC1/AC3).** Week 2: "Accessibility needs refer to
  wheelchair access, special physical seating, or **mobility/facility
  arrangements**." So the facility arrangements an organiser records go in
  the request's accessibility needs, and IS-13 checks those against the
  venue's accessibility provisions (flags what's missing, by name --
  `venueSuitability.test.js`, accessibility cases). What stays "not
  assessed" is the separate *Facilities* row: the general facilities a
  venue lists (stage, projector screen, ...) have no matching "required
  facilities" field on events, and nothing in the clarifications asks for
  one. That row is an honest use of the AC's own "requirements that have
  not yet been recorded" clause; if a future story adds such a field, the
  check should start reading it.

- **Empty accessibility_needs is treated as "not recorded," not "none
  needed."** The schema can't tell the two apart (both are just an empty
  array), so `checkSuitabilityForEvent` reports "not assessed" either way.
  If the team later wants event creation to distinguish "I checked and
  need nothing extra" from "I haven't filled this in," that's a schema
  change this check should then read.

- **~~"Retired or withdrawn" venues don't exist as a concept.~~ Resolved
  by IS-61 (effectively met).** IS-12 AC6 says retired or withdrawn venues
  must not appear in results. When this note was written nothing could
  retire a venue; since IS-61, withdrawing a venue from the catalogue
  deletes it, so it can't appear in search results or be booked
  (`test_venue_catalogue_crud.py::test_ac3_a_deleted_venue_is_gone_from_the_catalogue`,
  `::test_a_deleted_venue_cannot_be_requested`). There is still no
  separate "retired but kept" status; say if one is wanted.

## Request for Event Change (IS-21, 8 Oct)

- **An approved timing change still doesn't MOVE the venue booking -- but
  the coordinator is now stopped and told first.** `app/events/change_impact.py`
  checks each pending change against the arrangements already made (venue
  booking: period, capacity, layout, accessibility; registrations; equipment;
  technical support), and approval is refused (409
  `change_impact_unacknowledged`) until the coordinator acknowledges every
  affected area. What they acknowledged is stored in
  `event_change_requests.acknowledged_impacts`. `booking_start/end` stay snapshotted (by
  design, 20261005100000_venue_bookings.sql), so re-booking is the
  coordinator's follow-up. Still open: should approval also release the
  booking automatically and send the session back to planning? The
  coordinator's own availability for the new dates is not checked either.
  Please confirm the stance itself: a significant change WARNS and needs
  acknowledging, but isn't blocked, since a requirement change is often
  exactly why arrangements must be redone. Since IS-9 the coordinator's own
  edits go through the same check.

- **Technical support can only be flagged "check manually"** (equipment
  requests are now checked for real -- see IS-9 below).
  No equipment-allocation or technical-support-assignment tables exist, so
  `change_impact` can't tell whether anything was actually arranged -- it
  raises a "check" (never a "conflict") whenever a post-approval change
  touches timing, equipment or layout on a session that needs equipment.
  When those stories add real records, these two checks should read them.

- **Lowering expected_attendance below the number already registered.**
  Same question Attendee Registration already raised for edits: existing
  registrations stay confirmed. A change request doesn't make it worse,
  but it does make it reachable on a confirmed event.

- **A pending change on an event that is then cancelled or completed stays
  pending.** rule_event_review_change refuses review outside
  submitted..confirmed, so nobody can decide it. It does no harm (it can
  never be applied), but the history shows it as "Awaiting review"
  forever. Could be auto-rejected by the cancel/complete transitions.

- **"Permitted changes" read as: every field the organiser could fill in
  when creating the request** (`EVENT_FIELDS`), never status, coordinator
  or ids. If the customer means a narrower list for confirmed events, it is
  one set in `change_request_service.py` to narrow.

- **No notifications.** The coordinator isn't told a change was requested,
  and the organiser isn't told it was decided -- both see it on the event
  page. Depends on the Notification System story, like IS-39.

- **The Confirmed Status story's "unless there is a change that was
  permitted"** (the field-locking item above) is now read as: a change the
  assigned coordinator makes or approves. The ORGANISER never edits a
  confirmed event directly (rule_event_edit: draft/rejected only) -- they
  file a change request. The assigned coordinator can edit it directly (see
  the edit-window item below). Please confirm this is what "permitted"
  means.

The calls below were made because the IS-21 story didn't say. Each is
written up in docs/design-decisions.md; please confirm or correct:

- **When a change can be requested: submitted through confirmed.** Not
  draft or rejected (the organiser edits those directly and resubmits), not
  completed (IS-38: read-only) or cancelled. Includes `submitted` before a
  coordinator is assigned -- the request waits until one is.

- **Who reviews: only the assigned coordinator.** The Event Coordinator
  Lead can see change requests (they oversee every submitted request) but
  can't approve or reject them. Should the Lead be able to, e.g. when
  nobody is assigned yet?

- **One pending change request per session at a time.** A second is
  refused until the first is decided, so two requests are never reviewed
  against details the other is about to change. Enforced by the app and by
  a unique index.

- **A change to the name, description or purpose applies to every
  session** of the request (they're shared fields), even though the request
  was filed on one session. Every other field changes only that session.

- **The coordinator's edit window was widened** from under review /
  planning to every status except completed and cancelled ("the event
  coordinator should be able to edit the event details when they want
  to"). This changes existing IS-31 / Event Information Management
  behaviour in rule_event_edit -- needs the rule owner's sign-off.

- **"Requested" vs "changed" in the history is decided by who made the
  entry.** event_logs has no kind column (the live schema), so an entry by
  the request's organiser shows as "Change requested by", anything else as
  "Changed by". Someone who is both the organiser and the assigned
  coordinator counts as "changed". A kind column would make this explicit.

- **The history doesn't say which session an entry is about.** event_logs
  links to the whole request (shared_event_id) only, per the live schema,
  so on a multi-session request two entries about different sessions look
  alike. Adding a nullable event_id back would let the page label them.

## Equipment Availability Checking (IS-18, Nawaz, 8 Oct)

- **Unit level, per the AC.** The story's Note says aggregate or unit level
  is acceptable and the team should propose one; the updated AC then adds
  "Track equipment based on unit level." Built as unit level: one
  `equipment_units` row per physical item, identified by an `asset_tag`, with no
  stored quantity anywhere (availability is always a count of units). This
  is also what the later "Specific equipment IDs are listed alongside the
  quantity" Reservation criterion needs. If the customer meant aggregate
  after all, the `equipment_units` table would collapse into a quantity on
  `equipment_types` and the occupancy view would lose its per-unit detail.

- **The schema for requests and reservations had to be created here.**
  None of it existed. `equipment_requests` / `equipment_request_items` are
  the shape the "Record Equipment Request for Event" story needs, and
  `equipment_reservations` is the shape "Accept an equipment request and
  reserve stock" needs, so those stories can write to them without
  changing the tables. **Neither story is built.** There is no way in the
  app yet to create a request, accept or reject one, update a reserved
  quantity, or release equipment when an event is cancelled. Until the
  first two land, requests and reservations only exist as seed data
  (`seed_equipment_demo` in `backend/seed.py`), and the cancellation story
  also needs a hook in the event cancel path.

- **`events.equipment_needed` is left alone and is not the request.** It
  is a free-form jsonb list on the event row from event creation, with no
  status, requester or technical-requirements text. The new request tables
  are a separate record. Whether creating an event's equipment list should
  also create an `equipment_requests` row (so a coordinator doesn't enter
  it twice) is for the Record Equipment Request story to decide.

- **A unit `status` (available / maintenance / retired) was added, which no
  AC names.** Without it a unit under repair would be counted as lendable
  and the check would over-promise. Only `available` units count.
  Occupancy itself is still derived from reservations, not stored on the
  unit. Rename or drop the values if the team has a different idea of
  out-of-service.

- **"Confirmed event requests" is read as "has a reservation row."** A
  reservation row only exists once a request has been accepted, so any
  reservation on an overlapping period reduces availability. The check
  does not also re-test the owning request's status: a reservation for a
  non-confirmed request would be an inconsistency, and the safe reading is
  that the unit is physically spoken for.

- **The request's own reservations are excluded from its check.** Opening
  an already-confirmed request would otherwise show it competing with
  itself.

- **Overlap is half-open.** A unit returned at 14:00 is available for a
  request starting at 14:00, matching the venue booking overlap rule and
  the database constraint. No setup or turnaround buffer is added to an
  equipment period (venues get one from the venue's own configuration;
  nothing in the equipment stories mentions one).

- **A request's period is snapshotted** from the session's preferred
  date/time when the request is created, rather than read from the event
  each time, so a later edit to the event cannot silently change what a
  submitted request or a reservation meant. When the Record story is
  built it should compute `needed_start`/`needed_end` the way
  `booking_service._event_window` does (Singapore time, missing end time
  = end of day). The seed data uses its own dates, not the demo events'.

- **Access.** Equipment records, the availability check and occupancy are
  Technical Support Staff only. The occupancy view lists other events'
  names, which no other role has a reason to see. The requesting
  coordinator can fetch their own request through the API ("viewable
  later"), but there is no coordinator screen for it yet. That screen
  belongs with the Record story.

- **The database exclusion constraint on reservations was not run against
  a real Postgres.** The migration was syntax-checked and the application
  logic is covered by unit tests, but no database was reachable while
  building it. Apply it to a dev database (`supabase db reset`) and run
  `python seed.py` before relying on it. The integration-test suite has no
  equipment tests, for the same reason.

- **The units table is called `equipment_units`, not `equipment`.** The live
  database already contains an enum type named `public.equipment` that no
  migration in this repo creates (found when the first version of this
  migration failed with "type equipment already exists"). A table cannot
  share a name with a type in the same schema, so the table was renamed
  rather than touching a type whose users are unknown. Worth finding out
  who made that enum and whether anything uses it.


## View Reserved Equipment (Justin, 14 Oct)

Each of these has its reasoning in `docs/design-decisions.md` §View Reserved
Equipment; listed here for confirmation.

- **The quantity shown is the number of units actually reserved, not the
  number asked for.** The AC says "confirmed equipment reservations display
  quantity per item"; read as "how many units are held", counted from
  `equipment_reservations` rows. The quantity *requested* is still shown
  in the request table. They only differ if a request is confirmed with
  fewer units than asked for, which the (unbuilt) accept story would have
  to allow. Please confirm.

- **"Released" is derived from the event being cancelled, not stored.**
  `equipment_requests.status` stays `confirmed` on a cancelled event; the
  page shows "Released" because the event is `cancelled`. No enum value
  was added. If a stored status is wanted (e.g. for the Technical Support
  Staff's request list), the release-on-cancel story would add it.

- **Only the assigned coordinator sees the section.** The AC names the
  Coordinator, so it is rendered in the coordinator's view of the event
  page only, like Venue Booking. The API itself is gated on `event.view`
  (same as `GET /events/<id>/venue-bookings`), so the event's organiser
  and the coordinator lead could read it through the API; the frontend
  just doesn't show it to them. Please confirm the organiser shouldn't
  also see what's allocated to their event.

- **Depends on conventions the accept story must follow.** One
  reservation row per unit; the request becomes `confirmed` when its rows
  are written; reservation times copy the request's. Whoever builds
  "Accept an equipment request" should confirm these.

## Release Equipment on Cancel (Justin, 14 Oct)

Reasoning in `docs/design-decisions.md` §Release Equipment on Cancel.

- **Release deletes the reservation rows.** No history of which exact units
  were held is kept after a cancel (the cancel itself is in
  `event_status_log`). Please confirm nobody needs that record -- e.g. the
  Technical Support Staff seeing "PRJ-001 was booked for X, then released".

- **Not atomic with the status change.** If the release fails after the
  event is already `cancelled`, the route returns an error but the event
  stays cancelled with its units still reserved, and cancel can't be
  retried (cancelled -> cancelled isn't allowed). Rare (the database would
  have to fail between two writes), but there is no repair path in the app
  yet; someone would delete the rows by hand. A database trigger on
  events.status would close this; not done to keep the logic in Python
  like the rest of the codebase.

- **Only the cancel route releases.** If another way to reach `cancelled`
  is added later, it must call `release_event_equipment` too.

- **A Cancel Event button was added to the coordinator's review page.**
  IS-39 built `POST /events/<id>/cancel` but no UI called it, so this story
  added one to "Your Decision" in `CoordinatorEventReview.vue`: shown to
  the assigned coordinator while the session is approved / planning /
  confirmed (same window as `rule_event_cancel`), with a required reason,
  same pattern as Reject. It cancels **this session only**, like the
  route; cancelling every session of a request at once was not built.
  Please confirm that's acceptable, and IS-39's owner should OK the
  button living there.

## Reassignment is Lead-only (Justin, 14 Oct)

Driven by the Week 9 clarification (reassignment "is now manually assigned
by the lead"); reasoning in `docs/design-decisions.md` §Reassignment is
Lead-only. Judgement calls made while applying it, for confirmation:

- **Coordinators can no longer see the list of other coordinators**
  (`GET /events/coordinators` is Lead-only). It only existed for their
  Reassign dropdown. If a coordinator should still be able to look up
  colleagues (e.g. to suggest a hand-over to the Lead), this needs to
  come back.

- **Assumed: a coordinator raises a hand-over with the Lead offline.**
  Week 4 had coordinators agree hand-overs offline between themselves;
  Week 9 moved the reassignment itself to the Lead. We assume the
  conversation stays offline (now with the Lead), and the Lead records
  the outcome in the system -- consistent with "cross-department
  communications can be assumed to happen offline" (Week 2). So there is
  no in-system "request reassignment" for coordinators; if one is wanted,
  that's a new story.

- **The Sprint 1 story "Coordinator needs reassignment" is superseded**,
  not deleted: its other criteria (one coordinator at a time, the new one
  takes over, the previous one is unassigned) still hold for the Lead's
  reassignment. Please confirm the backlog marks it accordingly.

- **IS-7's "the previous coordinator retains view access but cannot
  edit" is superseded, not built.** With the Lead doing every
  reassignment, access follows the current assignment
  (`rule_event_view` checks the current `coordinator_id` only): once an
  event is moved to another coordinator, the previous one can no longer
  open it at all -- the same 404 as any event that isn't theirs
  (`test_authz_policy.py::test_coordinator_reassigned_away_loses_view_of_the_event`).
  Hand-over context lives with the event itself (status history, event
  logs, the clarification thread), which the new coordinator sees in
  full. If the customer wants the previous coordinator to keep read-only
  access, that needs a record of past assignments (there is none today)
  and a change to `rule_event_view` -- a new story. Please confirm.

## Update Event Information During Planning (IS-9, 15 Oct)

The calls below were made because the story didn't say. Each is written up
in docs/design-decisions.md; please confirm or correct:

- **"Venue requirements" read as the room layout.** Accessibility needs are
  listed as their own field in the story, so changing them is recorded as
  ordinary. They are still checked against a booked venue, and the
  coordinator must acknowledge a conflict before saving.

- **"Planning stage" read as every status before completed/cancelled**
  (under review, approved, planning, confirmed) -- the coordinator's
  existing edit window. Should editing be narrower, e.g. approved/planning
  only?

- **The review step appears for every significant change, even when no
  arrangement is affected** (it then says so). Acknowledgement is only
  required when something is affected.

- **Confirmed -> planning happens on ANY change, including an ordinary one**
  (a typo in the description), as the criterion says. It also happens when
  an approved change request alters a confirmed event, and when a renamed
  shared detail reaches a confirmed sibling session. Is that intended for
  ordinary changes?

- **The coordinator's name/description/purpose change now reaches every
  open session of the request.** Previously it changed only the session it
  was made on.

- **The Lead gets a 403 with a reason instead of a 404** when trying to
  edit, since they can view the event.

- **Migration `20261015000000_event_logs_significance.sql` must be applied
  before deploying** -- the backend writes `event_logs.significance`, and
  PostgREST refuses inserts naming a missing column.

- **No notification** to the organiser or to Venue/Technical Support Staff
  when a significant change affects their arrangements; depends on the
  Notification System story.

### Added 19 Oct (AC3 and AC9 completed)

- **Edit window vs the team's note on the story.** The note reads: the
  coordinator edits from under review to confirmed; the organiser edits
  only a draft. `rule_event_edit` is wider on both sides: the organiser can
  also edit a **rejected** session (the resubmit flow depends on it), and
  the coordinator can edit in any status except completed/cancelled
  (including draft/submitted/rejected, and safety_review). Left as is --
  should either branch be narrowed?

- **Touched-but-unbroken arrangements are shown, not acknowledged.** Only a
  conflict needs the "I've reviewed these" tick. Should every touched
  arrangement need it before a significant change saves?

- ~~**Cancelling a venue booking doesn't change the event's status.** A
  confirmed event that loses its only confirmed venue stays confirmed. A
  change to the event's details sends it back to planning (AC10); should
  cancelling a confirmed booking of a confirmed event do the same?~~
  **Resolved 2026-10-26: yes.** Cancelling any venue booking (pending or
  confirmed) of a confirmed event sends the event back to planning; other
  statuses are unchanged. See `docs/design-decisions.md` §IS-9 "Cancelling
  a booking of a confirmed event reverts it to planning".

- **The current coordinator cancels, not the requester.** After the Lead
  reassigns an event, the new coordinator can cancel the old coordinator's
  bookings. Viewing a single booking (`rule_venue_booking_view`, IS-14) is
  still requester-only, so the new coordinator can cancel a booking whose
  page they can't open. Should view follow the current coordinator too?
  (IS-14's rule -- Josiah's call.)

- **"Request a venue" is hidden while a booking is pending or confirmed --
  in the page only.** `POST /events/<id>/venue-bookings` still accepts a
  second booking for the session. Enforce it in the backend too?

- **Change History: older entries have no session.** Entries written before
  `event_logs.event_id` existed are labelled only when the request has a
  single session; on a multi-session request they show no session badge.

- **"All sessions" means an applied shared-detail change.** A coordinator's
  name/description/purpose-only change reaches every open session, so it is
  labelled "All sessions"; completed/cancelled sessions it skipped are not
  called out. An organiser's request is labelled with its own session.

- **Migrations `20261019300000_venue_booking_cancel.sql` and
  `20261019400000_event_logs_session.sql` must be applied before
  deploying.** The backend writes `event_logs.event_id` on every logged
  change; PostgREST refuses an insert naming a missing column, so edits and
  change requests fail until it exists.

## Shared calendar extraction (16 Oct)

- **Test gap: no venue calendar test pins the overlap boundary.** In a hand
  mutation test, each `<` in `app.shared.calendar.spans_overlap` was flipped
  to `<=`, one at a time. All 20 tests in `test_calendar_service.py`,
  `test_venue_calendar_routes.py` and `test_authz_venue_calendar.py` still
  passed: none of their entries starts or ends exactly on a range edge.
  Only the new `test_shared_calendar.py` caught the mutants. Should the
  IS-11 tests gain a boundary case (Nawaz's call, as they are the venue
  calendar's specification)?

- **Calendar colours vs the event-status palette.** The venue calendar's
  state colours (tentatively held `#1f5fae`, confirmed `#2f6b3f`, blocked
  `#a33f3f`) match none of the event-status palette IS-9 spread to the
  dashboards (e.g. confirmed is `#0f6e6a` there). The extraction kept the
  calendar's colours so nothing visibly changed. Should calendars adopt the
  palette (Nawaz / Aaralyn), and should that palette become one shared file
  instead of four copies?

## View Equipment Availability Calendar (IS-47, 16 Oct)

- **Should Event Coordinators see equipment calendars too?** (for Justin)
  It is built for Technical Support Staff only, matching
  `equipment.list` / `equipment.view`. The venue calendar also admits
  coordinators. If yes, it is a one-line change: one more `_has_role` in
  `rules.py::rule_equipment_calendar_view`, plus the role in
  `ROUTE_ACCESS` `equipment-calendar`.

- **No "pending" state on the calendar.** A pending `equipment_request`
  names a type and a quantity, not a unit; a unit is allocated only when
  its `equipment_reservations` row is created. There is nothing to place on
  one unit's calendar. The venue calendar leaves pending bookings out for
  the same reason. Showing pending demand would need a per-type view, a
  different screen.

- **No under-maintenance periods on the calendar.** There is no equipment
  equivalent of `venue_blocks`: `equipment_units.status` is one current
  value with no dates. The status is shown as a pill; maintenance windows
  would need a new table.

- **No location.** IS-47's AC2 and the wireframe show the unit's
  location, but `equipment_units` has no location column, and the ticket
  ruled out schema changes. AC2 is met except for location. Should units
  get a location (free text, or a venue reference)?

- ~~**Calendar range is a day off in UTC+8 -- the venue calendar is
  affected now.**~~ **Fixed by IS-74 (Terry, 6 Nov), pending Nawaz's sign-off
  on the venue calendar behaviour.** `lib/calendar.js::toISODate` now returns
  the local date, `app/shared/calendar.py::CalendarRange.overlaps` converts
  entries to Singapore time, and `widenRange` is deleted. See "Calendar days
  are Singapore days (IS-74)" in `docs/design-decisions.md`. The defect was:
  `toISODate` used `toISOString()`, so local midnight in Singapore became the
  previous UTC date. The venue calendar's November query was
  `2026-10-31..2026-11-29`, and the backend compared the UTC times PostgREST
  returns against those days, so on the venue calendar:
  - a booking on the last day of the month after 08:00 SGT was missing
    from the month view;
  - in the day view, a booking after 08:00 on the chosen day was missing,
    and the previous day's late bookings were shown instead.

  Fixing only the dates would have moved the gap to the first day's
  00:00-08:00, which is why the backend had to change too.

- **Mutation test result.** Each `<` in `spans_overlap` (the comparison
  the equipment calendar filters with) was flipped to `<=` in turn, and
  both mutants were killed by the new boundary tests. One finding: the
  range ends at `time.max` (23:59:59.999999), not at the next midnight. A
  reservation starting at the next midnight is excluded under both the
  original and the mutant, so that test alone would NOT have caught
  `a_start <= b_end`. The test that does starts at 23:59:59.999999 exactly
  (`test_reservation_starting_at_the_ranges_last_instant_is_excluded`). No
  gap remains for this path.

- **Waiting on Nawaz: the link from the equipment detail page.** It is
  the only change to an IS-18 file (`EquipmentDetailView.vue`), in its own
  commit marked `[PENDING NAWAZ'S SIGN-OFF]`. Drop that commit if he says
  no; the calendar is then reached by URL only.

- **Please confirm these calls IS-47 made where the ticket was silent**
  (reasoning in docs/design-decisions.md, "View Equipment Availability
  Calendar (IS-47)"):
  - **Status pill wording.** It uses the inventory's existing labels
    ("In service" / "Under maintenance" / "Retired"), not the wireframe's
    "Operational / Maintenance / Retired", so a status reads the same on
    every equipment page.
  - **Reserved days are green,** the venue calendar's "confirmed"
    colours, and an event with no name shows as "Reserved".
  - **A "Today" button** sits beside previous/next, as on the venue
    calendar. The wireframe shows only previous/next.
  - **A multi-day reservation is marked on every day it covers, with its
    end exclusive:** one ending at midnight does not mark the next day.
  - ~~**The page asks for one day more than the month on each side**
    (`widenRange`), to work around the UTC+8 range defect above.~~ Removed by
    IS-74: the page now asks for exactly the month.
  - **The calendar route is its own blueprint**
    (`app/equipment/calendar_routes.py`), so IS-18's `routes.py` is
    untouched.

## Safety review status (Week 7 #6, Justin, 18 Oct)

- ~~**`safety_review` exists, but nothing moves an event into it yet.**~~
  **Resolved by the Safety Officer story (19 Oct, below):** the coordinator
  submits a session into `safety_review`, and `planning -> confirmed` is
  removed.

- ~~**Status lists that will need `safety_review`.**~~ **Resolved by the
  Safety Officer story:** `_CANCELLABLE_STATUSES`, `CHANGE_REQUEST_STATUSES`
  (backend and `changeRequests.js`), `ARRANGED_STATUSES`,
  `IMPACT_CHECKED_STATUSES` and `CoordinatorEventReview.vue::canCancel` all
  include it now.

- **Please confirm: no separate `preparation` status.** Week 7 says the
  event "cannot proceed to preparation until the Safety Officer has
  approved it". We read preparation as the work Venue and Technical
  Support Staff do while the event is confirmed (Week 2: progress is
  updated "prior to and during event delivery"), not a status of its own.
  A status between safety review and confirmed would hold registration
  closed until setup was finished, since registration needs `confirmed`.

- **Rejected and changes requested both go back to planning.** Week 7
  lists three outcomes (approve, reject, request changes). Week 9 says a
  failed safety approval "will send the event back to planning phase", so
  both non-approvals use `safety_review -> planning`, and the comment says
  what to fix. Please confirm a rejection shouldn't end the event instead.

## Safety Officer (Week 7 #6, Justin, 19 Oct)

Decisions made where Week 7 and Week 9 were silent (reasoning in
`docs/design-decisions.md`, "Safety Officer"). Please confirm:

- **Every Safety Officer sees and may decide every review.** No assignment
  or "claim" step: Week 9's "pick up the event request" is read as opening
  it from the shared queue, the way every Venue Staff member sees every
  booking.
- **When a session can be submitted:** at least one confirmed venue
  booking, and no venue booking or equipment request still pending.
  Equipment is optional (a session may need none, and equipment requests
  can't be created in the app yet). Rejected bookings/requests don't block.
- **A comment is required for every decision, approving included**
  (IS-59 AC3). Week 9 says the officer updates the status "with a comment".
  It was first built optional for approvals and made required on
  2026-11-06 to match the AC: rejecting or requesting changes, the comment
  says what to fix; approving, it records what was checked.
- **The coordinator confirms an approved session** ("Confirm Event"); safety
  approval doesn't confirm it automatically. Week 9: "The co-ordinator will
  decide on the subsequent action." Confirming is refused (400) unless the
  latest safety review is approved.
- **One review per session, not per request** (each session has its own
  venue, capacity, layout and status). The dashboard still shows one card
  per request, with its sessions inside.
- **Reject and request changes behave the same** (both back to planning, the
  comment saying what to fix) -- unchanged from the safety_review status
  story above; still worth confirming.

Known gaps, not built:

- **Editing a session during its safety check doesn't reset the check.**
  While a session is in `safety_review` (pending or approved), the
  coordinator can still edit it (`rule_event_edit`), and the review stands.
  Changes AFTER confirmation already send it back to planning (IS-9), which
  then needs a new check. Options: block edits while in `safety_review`, or
  send the session back to planning on a significant edit.
- **A pending review of a cancelled session stays `pending` in the table.**
  It's hidden from the dashboard and can't be decided (the service checks
  the session is still in `safety_review`); nothing marks it closed.
- **Notifications** (officer told of a submission, coordinator told of a
  decision): placeholders only (`safety_service._notify_safety_review`), like
  every other notification.
- **Emergency access, equipment placement, crowd movement and venue
  restrictions** aren't recorded anywhere; the review page lists them as
  the officer's own checks (Week 9: the officer doesn't input, only
  approves).
- **No seeded demo session ready for a safety check.** `seed.sql`/`seed.py`
  add the Safety Officer account (`safety1@example.com`); to demo the flow,
  take a planning session, get its venue booking confirmed, then submit it.
- **Submit and decide are two writes each, not one transaction** (review
  row + status change), the same trade-off as `transitions.transition()`'s
  history insert. Each handles a failure between the two -- see
  `app/safety/safety_service.py`.

## Venue Settings, Venue Becomes Unavailable, Tentative Hold Expiry (Week 7 #1/#2/#4, Josiah, 19 Oct)

Decisions made where the customer-changes doc and Aaralyn's agreed
tentative-hold flow were silent (reasoning in `docs/design-decisions.md`,
"Venue Settings, Venue Becomes Unavailable, Tentative Hold Expiry").
Please confirm:

- **`tentative_hold_minutes` defaults to 1440 (24 hours), guessed.** Same
  posture as `setup_minutes`/`turnaround_minutes`'s own guessed default of
  30 when those were added (IS-14) -- no story or doc gives a number.
- **A pending request reviewed against a venue's now-stale settings is a
  soft edge, not a fixed one.** If Venue Staff edit a venue's
  `setup_minutes`/`turnaround_minutes`/`tentative_hold_minutes` while a
  request for that venue is still pending, the pending request's eventual
  confirmation will snapshot the NEW settings (confirm-time is when the
  snapshot happens), even though the coordinator requested it under the old
  ones. This is a genuine gap, not covered by the snapshot-immutability
  proof (which only covers ALREADY-confirmed bookings). We judged it
  acceptable: settings changes should be rare, and the alternative
  (snapshotting at request time instead of confirm time) would mean a
  rejected-then-resubmitted request could carry stale settings forward
  indefinitely. Please confirm this is the right trade-off.
- **Editing or removing a venue block is out of scope.** The new
  `venue_blocks` RLS policy is INSERT-only; once created, a block cannot be
  shortened, extended or withdrawn through the app. No story asked for
  this, and it wasn't invented.
- **Hold expiry is eventually-consistent, not point-in-time** (see
  design-decisions.md's "lazy, read-triggered" write-up) -- a venue does
  not free itself up the instant its hold's clock runs out; it frees up
  the next time any call site reads it. No story asked for second-
  granularity expiry, so this was judged acceptable rather than building
  scheduler infrastructure the rest of the codebase has no other use for.
- **The Venue-Becomes-Unavailable story's "Multiple Venues for One Event"
  sibling (Week 7 #3) has no corresponding Jira card** -- confirmed a real
  gap, out of scope this sprint. The release mechanism was written
  plural-safe so it costs nothing extra to pick up later.
- **Venue blocking vs. a confirm racing at the exact same instant is an
  app-level check only**, not a database-level guard the way IS-16's
  exclusion constraint is (see design-decisions.md). Judged acceptable: two
  different staff actions landing in the same instant is far rarer than
  IS-16's two-routine-confirms race.

Known gaps, not built:

- **Notifications** (coordinator told a booking was released, whatever the
  trigger): a `print()` placeholder only
  (`block_service._notify_coordinator_venue_blocked`), the same converged
  pattern as every other `_notify_*` stub in this codebase. No real
  notification infrastructure exists anywhere to build on.
- **No seeded demo data for a tentatively-held, about-to-expire booking.**
  To demo expiry, confirm a booking, then either wait out its hold or
  adjust `confirmed_at`/`hold_minutes` directly in the database.

## Record Equipment Request for Event (IS-17, Nawaz, 19 Oct)

Source: IS-17's AC (specify an event and one or more items; quantity per
item; free-text technical requirements per item; blocked when a quantity is
missing or zero; viewable later; created as Pending and visible to Technical
Support), plus Aaralyn's IS-9 note ("whoever builds that feature should
require planning too"). No new migration: `equipment_requests` and
`equipment_request_items` already exist (IS-18).

- **Planning only.** `rule_equipment_request_create` is a mirror of
  `rule_venue_booking_create`: the event's assigned coordinator, and the
  event must be in `planning`. A stranger gets the same 404 as a missing
  event. This is our reading of Aaralyn's note, not something a story
  states; relaxing it is one line in the rule.
- **The coordinator does not enter dates.** The request is for one session
  (the `events` row), so `needed_start`/`needed_end` are that session's own
  window, snapshotted the same way a venue booking snapshots its period
  (`booking_service._event_window`: Singapore time, missing end time = end
  of day). The form shows them but does not ask for them. If a coordinator
  later needs equipment for only part of a session, the request would need
  its own period fields.
- **No setup/turnaround buffer.** A venue booking pads the session with the
  venue's setup and turnaround minutes. Equipment has no such per-type
  figure in the schema, so the request is exactly the session's window.
- **One line per type.** Matches `unique(request_id, equipment_type_id)`. A
  repeated type is rejected with a message rather than merged, so the
  coordinator sees it. Quantity must be a whole number of at least 1;
  technical requirements are optional and capped at 2000 characters (our
  limit, the column is unbounded `text`).
- **Several requests per session are allowed.** "Request more equipment"
  adds another request rather than editing the first. Editing or cancelling
  a pending request is not in this story and is not built.
- **Writes are two inserts, not a transaction.** The request row, then its
  lines. If the lines fail, the request row is deleted again so Technical
  Support is not left a request that asks for nothing. Not tested against a
  real database (the project's integration tests need a local Supabase,
  which was not available when this was written).
- **Coordinators can now read the equipment catalogue** (`GET
  /equipment/types`, kinds only, not units) because the form needs it and
  `equipment.list` is Technical Support only. Types are not sensitive.
- **Nothing is reserved.** A new request is Pending with no reservation rows
  (IS-19, Accept, writes those). Technical Support already sees it in their
  queue (IS-18); since IS-26 they are also told when one is submitted.
- **The create-event form's `equipment_needed` list is unchanged** and does
  not create a request. Still open: whether it should.

## Accept an Equipment Request and Reserve Stock (IS-19, Nawaz, 19 Oct)

Source: the Reservation story's first AC ("Accepting a request changes its
status to confirmed", "Available quantity for that equipment is reduced by
the reserved amount, scoped to the event's date and time", "Only requests in
a pending status can be accepted"). No new migration. Implements the three
conventions Justin's View Reserved Equipment section documents
("Conventions this relies on", `docs/design-decisions.md`).

- **One reservation row per unit.** A request for 2 projectors writes 2 rows,
  each naming a unit. The request becomes `confirmed` only after those rows
  are written, and each row copies the request's `needed_start`/`needed_end`.
- **The available quantity is not stored.** It still falls out of counting
  reservation rows (IS-18's check, the IS-47 calendar and the exclusion
  constraint all read the same rows), so there is no counter to keep in step.
- **Accepted whole or not at all.** If any line is short, nothing is
  reserved and the error says which type and by how much. A partial accept
  (give them 1 of the 2 projectors) is not built; the Technical Support
  user's other option is to reject, which is IS-41.
- **Which units a request gets.** Lowest asset tag first, so it is
  predictable. Nothing lets Technical Support pick specific units; if that
  is wanted it is a change to this story, not a new one.
- **Only while the event is in `planning`.** `rule_equipment_request_accept`
  refuses a request whose event is cancelled, approved, in safety review or
  later. The safety-review submit already requires no pending equipment
  request, so a pending request on an event past planning is a leftover
  (e.g. the event was cancelled), and accepting it would take stock for
  nothing. This is our reading, not a story rule.
- **Two ways it can lose a race, both handled.** Two people accepting the
  same request: the status update is conditioned on `pending`, the loser's
  units are deleted again and it gets "no longer pending". Two different
  requests going for the same unit: the exclusion constraint refuses the
  second insert and nothing is half-reserved. Neither has been exercised
  against a real database (no local Supabase was available).
- **No transaction.** The REST client gives none, so a crash between
  writing the reservations and flipping the status could leave reservations
  on a request that is still `pending`. Re-accepting it would then fail on
  the exclusion constraint (its own units are already held), so a leftover
  like that needs its reservation rows deleted by hand. Not guarded beyond
  the clean-up above.
- **Notification.** Written after this story, by IS-69: the session's
  coordinator is told of the decision through `_notify_request_decision`.
- **Reject, warn on shortfall, and quantity changes** are IS-41 and IS-43,
  not here.

## Get Warned and Reject When Requested Quantity Exceeds Availability (IS-41, Nawaz, 19 Oct)

- **Needs a migration, unlike IS-17 and IS-19.** `equipment_requests` had a
  `rejected` status but nowhere to keep the explanation the story requires.
  `20261019100000_equipment_request_rejection.sql` adds `rejection_reason`,
  `decided_by`, `decided_at`, plus a CHECK that a rejected request has a
  non-blank reason and no other request has one (added `NOT VALID`, so it
  only applies to new and updated rows). Each request is decided once, so
  the reason lives on the request rather than in a status-log table; if a
  later story reopens rejected requests, that is when to add a log table.
  Must be applied in the Supabase SQL Editor before the reject button works.
- **"Warned" is the existing availability check.** IS-18 already shows
  requested vs available per line and flags shortfalls. IS-41 adds the
  suggestion to reject (shown only when something is short) and keeps Accept
  disabled in that case, which IS-19 already did.
- **Rejecting is allowed even when stock is fine.** The story's trigger is a
  shortfall, but Technical Support may have other reasons (equipment needed
  elsewhere, unclear requirements), so the only requirement is a reason. If
  the team wants reject limited to shortfalls, it is one extra check in
  `rule_equipment_request_reject`.
- **No event-status check on reject.** Accept requires the event to be in
  `planning`; reject does not, so a pending request left on a cancelled
  event can be cleared. Rejecting takes no stock, so there is nothing to
  protect.
- **"Sent to the Event Coordinator"** is the stored reason shown in the
  coordinator's Equipment Booking section, plus `_notify_request_decision`,
  which since IS-69 writes an in-app notification to the session's
  coordinator.
- **Accepting does not write `decided_by`/`decided_at`.** IS-19 predates the
  columns and a confirmed request already shows its reservation rows.
  Say if the team wants those filled for accepts too.

## Update Quantity on an Existing Equipment Reservation (IS-43, Nawaz, 19 Oct)

- **Needs a migration.** `20261019200000_equipment_change_requests.sql` adds
  `equipment_change_requests`: one row per ask, against one line of a request
  (`request_item_id`), with `old_quantity`, `new_quantity`, a status
  (pending/accepted/rejected), `rejection_reason`, `decided_by`, `decided_at`.
  A partial unique index allows only one pending ask per line. Must be applied
  in the Supabase SQL Editor before any of this works.
- **The ask is stored and does not touch the confirmed request.** The story
  has the coordinator "request" a change and Technical Staff accept or reject
  it, so the ask needs a record Technical Support can review. Until it is
  accepted the request's quantity and reservations are exactly as they were,
  the same "goes through review first" stance Justin's Event Change Request
  story takes for event details.
- **"Triggers a recalculation" is computed whenever the ask is read.** Nothing
  is stored: each pending ask comes back with a fresh `check` (units that could
  cover the request vs the quantity asked for), the same way IS-18's check is
  fresh. That number includes the units the request already holds, because the
  availability check leaves a request's own reservations out of "held by
  others". A decrease is always accommodated.
- **Accepting an increase** reserves the extra units, lowest free asset tag
  first, copying the request's period. **Accepting a decrease** releases the
  surplus units, highest asset tags first. Technical Support cannot choose
  which units; say if the team wants that.
- **Whole-line quantity changes only.** Changing the date/time or adding a new
  type is not covered by this story; for a new type the coordinator uses
  "Request more equipment" (IS-17). A change to the date/time would follow the
  event's own change flow.
- **Allowed while the event is `planning`, `safety_review` or `confirmed`.**
  Accept requires the event to still be in one of those; a cancelled,
  completed or rejected event's change can only be rejected (to clear it).
  A pending request cannot have a change asked for: Technical Support decide
  it as it stands.
- **Only the coordinator who raised the request can ask.** Same as who can
  view it. If the assigned coordinator can differ from the requester, this
  needs widening.
- **No transaction.** Accept writes the extra reservations, claims the ask
  (conditioned on still pending), then updates the line, and undoes the earlier
  steps if a later one fails. The exclusion constraint is the backstop if
  another request takes a unit meanwhile. The real-database behaviour is
  untested.
- **Notification** uses the same `_notify_request_decision` hook as
  accept/reject ("change accepted" / "change rejected"), which since IS-69
  tells the session's coordinator; since IS-26 Technical Support are told when
  a change is asked for. The coordinator sees
  the outcome, and a rejection's reason, under the request on the event page.
- **The coordinator's page does not refresh itself** when Technical Support
  decide; they see the new quantity and allocated units after reloading.


## Venue Categories (IS-60, 23 Oct)

Reasoning for each item is in docs/design-decisions.md, "Venue Categories
(IS-60)".

- **Venue categories are the room layouts.** The story's "type of venues"
  is implemented as the existing room layouts (theatre, classroom, ...)
  rather than a separate category list. Please confirm a category isn't
  meant to be something else, such as a venue type like "auditorium" or
  "lab" independent of seating layout.
- **Rejected events are not "ongoing".** AC5 says ongoing events are those
  "not completed or cancelled". We also exclude rejected sessions, so a
  rejected session never blocks permanently deleting a category. Please
  confirm this departure from the AC's wording is acceptable.
- **Drafts and rejected sessions lose a disabled category.** It is cleared
  from them when it is disabled, when they are rejected while it is
  disabled, and when it is permanently deleted; the organiser's form says
  why it is empty. Other submitted events keep it. Please confirm.
- **Restoring a category doesn't put it back** on the drafts and rejected
  sessions it was cleared from; their organisers pick again. Please
  confirm, or say if a restore should give it back to sessions that
  haven't chosen another one yet.
- **Clearing a rejected session's layout isn't in its change history.**
  Nobody edits the event: it is the database reacting to Venue Staff
  disabling or deleting the category. Please confirm, or say if it should
  be logged (attributed to Venue Staff or to "system").
- **"Disabling" is the soft delete, and can be undone.** AC3/AC4's
  "disable" is the existing soft delete, which Venue Staff can also
  restore; the story doesn't mention restoring. Please confirm.
- **Category names are unique regardless of case.** "Theatre" and
  "theatre" can't both exist. Please confirm.

## CRUD in Venue Catalogue (IS-61, 23 Oct)

Reasoning for each item is in docs/design-decisions.md, "CRUD in Venue
Catalogue (IS-61)".

- **Pending bookings are released too, not just confirmed ones.** Please
  confirm "events that have booked the venue" includes requests still
  waiting on Venue Staff.
- **Confirmed sessions go back to planning** when they lose their venue
  (as IS-9 does when a confirmed event's details change), so the coordinator
  can book again. Please confirm.
- **A session under a safety check also goes back to planning**, and its
  pending safety review is closed as "changes requested" by the Venue Staff
  member who deleted the venue. Please confirm, or say how the Safety
  Officer should be involved.
- **The alert is on the event page only.** No email or push notification
  exists in the app yet. Please confirm that is enough for now.
- **Facilities and accessibility provisions are fixed lists** (the ones
  event requests choose from), so Venue Staff pick rather than type them.
  Please confirm, or say if Venue Staff need to add new kinds.
- **Edits don't re-check existing bookings.** Lowering capacity or removing
  a layout or accessibility provision from a venue leaves its bookings as
  they are. Please confirm.
- **Resolved (6 Nov, Aaralyn): Venue Staff can set operating hours.** They
  are now on the add and edit form, optional, as one daily window -- see
  "Operating hours (IS-11 AC5)" below.
- **New venues are always "available".** The form has no status field, so
  a venue is added as available and an edit never changes its status.
  Please confirm, or say if Venue Staff need to set it (e.g. a venue added
  while still under maintenance).
- **"Ongoing events" (AC4) means not completed, cancelled or rejected** --
  the same reading as IS-60. Only those events' bookings are released when
  a venue is deleted; finished and rejected events keep their record.
  Please confirm rejected events shouldn't lose their booking too.

Revised 3 Nov (Aaralyn): deleting a venue now removes its record in one
step (`20261103000000_venue_hard_delete.sql`; see design-decisions.md,
"Revised 3 Nov").

- **Only the venue's name is kept on past records**, as text on each
  booking (`venue_bookings.venue_name`), not its location, capacity or
  other details. Please confirm the name is enough when reviewing a past
  event, or say which other details need keeping.
- **The name is kept per booking, not per event.** An event can have
  several venue bookings, so each booking keeps the name of the venue it
  was for. Please confirm.
- **A delete can't be undone, and there is no list of deleted venues.**
  The earlier soft delete and its "Deleted" tab are gone, along with any
  venues that were already soft-deleted (their bookings keep the name).
  Please confirm Venue Staff don't need to see or restore deleted venues.

## Notification System (IS-69, 27 Oct)

- **The acceptance criteria are our reading.** IS-69's ticket text isn't in
  the repo, so `docs/traceability.md` maps working criteria (stored per
  user; own list, newest first, with an unread count; mark one or all read;
  never anyone else's; a failure never undoes the action). Please confirm
  or replace them with the ticket's own.
- **In-app only; email and SMS are deferred (IS-69 AC2) -- justified by
  the clarifications.** Week 2 (Justin): "The notification delivery
  channel is up to your implementation (**can be in-app or external**)."
  In-app is our channel. No mail or SMS provider exists, so the email/SMS
  preferences users set (registration form, profile -- IS-68/IS-75) are
  stored but don't send anything yet. AC2's "delivered according to the
  user's communication preferences" is therefore only half met: the
  preferences are recorded and kept, ready for when an external channel
  is added. Proposed AC2 rewording: "notifications are delivered in-app;
  users' email/SMS preferences are recorded for a later external
  channel." Please confirm.
- **Decisions go to the session's current coordinator**, not whoever made
  the request, since a reassigned session's new coordinator is the one who
  acts. Please confirm.
- **Nobody is told about their own action.** A coordinator cancelling their
  own venue booking gets no notification, and Venue Staff aren't told
  either. Please confirm, or say whether Venue Staff should be.
- **A safety submission goes to every Safety Officer.** There's no
  assignment step, so each gets their own copy. Please confirm.
- **A failed notification is logged, not retried.** The action it was about
  still succeeds. Please confirm that's acceptable, or whether some
  notifications must be guaranteed (which needs a retry or outbox).
- **No reminder notifications.** Nothing is sent on a schedule (e.g. before
  an event starts). That needs a scheduler, which has no owner or ticket.
  Please confirm reminders are out of scope.
- **Still not notified** (no hook existed; the owning stories can now add
  one `notify(...)` call each): the organiser on cancellation (IS-39, see
  above; done in IS-23), the coordinator on a new change request (done in
  IS-24), and attendees promoted off a waiting list (done in IS-22). Please confirm which are needed.

## User contact and preferences (IS-68, 30 Oct)

- **Justin: is this what you meant?** Your Attendee Registration code
  already answers how the profile relates to registrations, so this asks
  you to confirm, not to decide. IS-68 adds `phone`, `organisation`,
  `notify_email` and `notify_sms` to profiles and to `GET /me`, which turns
  on two pieces of your code as written:
  1. `prefillFromProfile` (`frontend/src/lib/registrations.js`): a new
     registration's phone, organisation and notification choices now
     *start from* the profile. The attendee can still change them per
     registration, and each registration stores its own.
  2. `_db_profile_organisation` (`registration_service.py`): ticking
     "include organisation" now copies the profile's organisation in.

  So the profile preference is the default for new registrations: it
  doesn't override them, and it isn't kept separate. With nothing saved
  (every existing user), the form is exactly as before; that is tested.
  Please confirm that's what you meant, or say if the preference should
  instead stay separate or override.
- **Nothing reads the communication preferences except that prefill.**
  Notifications are in-app only (IS-69), so a profile's email/SMS
  preference sends nothing until email or SMS delivery has an owner and a
  ticket. Please confirm that's acceptable for now.
- **`GET /me` has no `@require` decorator** (`backend/app/me/routes.py`).
  It relies on authentication alone, and that hasn't changed. It now also
  returns the caller's phone, organisation and preferences, still only
  their own. Noticed during IS-68, and deliberately not fixed here, since
  it predates this ticket. Please decide whether it should get a
  `profile.view_own` action like every other route.
- **Any signed-in user can read every profile's phone directly.** The
  existing "authenticated read profiles" RLS policy lets any authenticated
  user select every profile row through the publishable key, so it now
  covers the new columns too. Flask itself only ever returns your own.
  Narrowing the policy (to `id = auth.uid()`, or column privileges) changes
  what other features may read about people, so it wasn't done here.
  Pinned by a test so it can't change unnoticed. Please decide whether to
  narrow it, and who owns that.
- **Phone is optional on the profile.** The wireframe marks only
  Organisation as optional. Making phone required would stop existing users
  saving an organisation or a preference without also giving a phone. A
  registration still requires one. Please confirm.
- **Both preferences may be false on the profile.** A registration still
  needs at least one; the register form then asks. Please confirm.
- **Unmatched URLs answer 500, not 404, app-wide.** The catch-all
  `@app.errorhandler(Exception)` in `app/__init__.py` also catches
  werkzeug's NotFound and MethodNotAllowed. Found while testing that
  `/me/profile/<id>` doesn't exist. This predates IS-68 and wasn't
  changed. It refuses the request either way, but the status is wrong.
- **The wireframe isn't in the repo.** The fields come from the ticket and
  from `RegistrationForm.vue`'s comment on the same Edit Profile screen.
  This also answers the Attendee Registration entry above ("Profiles don't
  have phone or a contact preference yet").

### Answered by Justin (31 Oct) -- built as IS-75 (fix/IS-75-profile-contact-rules)

- **Prefill and organisation copy: confirmed as intended.** The profile is
  the starting value for a new registration; the attendee can still change
  it, and each registration keeps its own copy. Changing the profile later
  doesn't change registrations already made.
- **Phone is optional, and +65 followed by 8 digits when given.** Stored as
  `+6591234567`; the profile page shows `+65` as a fixed prefix.
- **Both preferences off is NOT allowed.** Email is on by default and at
  least one must stay on (supersedes "Both preferences may be false").
- **SMS needs a phone number.** The SMS box is disabled until a phone is
  typed; saving SMS with no phone (or clearing the phone while SMS is on)
  is refused with a message.
- **Organisation is read-only.** Week 4 clarifications: organisers and
  organisations are set up outside the system, so users don't type their
  own. Shown on the profile, refused by `PATCH /me/profile`, still copied
  into registrations.
- **Communication preferences sending nothing yet: accepted for now.**
- Still open: `GET /me` without `@require`, the profiles read policy, and
  unmatched URLs answering 500.


## Notification (Attendees) (IS-22, Justin, 1 Nov)

Jira ticket IS-22. Committed and merged as IS-76 by mistake (branch
`feat/IS-76-attendee-notifications`, PR #56); the history is left as is.

Decided and built; worth confirming with the customer:

- **Details changes are told when the session is confirmed again, not at
  each edit.** The story says "when relevant event details are changed".
  A change to a confirmed session sends it back to planning, and the
  change isn't final until venue, equipment and the Safety Officer have
  signed off again, so attendees hear once, at reconfirmation. If it's
  cancelled instead, they hear only about the cancellation. Confirm that
  no early "this event is being updated" notice is wanted.
- **"Relevant" is the name, the session's date and time, and its venue.**
  Equipment, description, attendance and the rest don't notify attendees.
- **The cancellation notice gives no reason and no link.** The reason is
  internal planning information, and a cancelled session's attendee page
  can't be opened any more.
- **In-app only.** The email/SMS preferences collected at registration and
  on the profile (IS-68) are stored but not used to send anything yet.
  Allowed by Week 2: the delivery channel "can be in-app or external"
  (see Notification System, IS-69).

## Withdrawal of Equipment Booking (IS-66, Nawaz, Sprint 4)

Reasoning is in `design-decisions.md` ("Cancel an Equipment Request"). Please
confirm:

- **Needs a migration.** `20261102000000_equipment_request_cancel.sql` adds
  `cancelled` to `equipment_request_status`. Apply it in the Supabase SQL
  Editor before the Cancel button works. It follows the latest on main
  `20261031000000`; check no open branch picked `20261102000000`.
- **IS-66 is the story for this.** Its one criterion is "Allow for deletion
  of equipment booking request when it is pending and once it has been
  accepted". That is what this builds, for both pending and confirmed
  requests. Please confirm the next point.
- **"Deletion" is built as cancelling, not deleting the row.** The request
  moves to `cancelled` and stays in the event's history (and in Technical
  Support's Cancelled tab); a confirmed request's reserved units are really
  deleted, so they are free at once. If the team wants the request row itself
  gone, that is a hard delete (it would also remove the request's items and
  quantity-change history) and a one-line change in `cancel_request`.
- **A pending request can be cancelled too**, not just a confirmed one.
- **No reason is asked for.** Say if the team wants one, as IS-9 does for
  venue bookings.
- **Cancelling is final.** The coordinator asks again with "Request more
  equipment" rather than reopening the old request, so the history shows
  both. Technical Support see cancelled requests under a new Cancelled tab.
- **Technical Support are told** (IS-26) when a request is cancelled, whether
  pending or confirmed, so a queue item does not vanish unexplained. The
  coordinator is not told of their own action.
- **Cancelling the whole event** is unchanged: Release Equipment on Cancel
  (Justin) still releases everything.

## Integration tests for the equipment workflow (Nawaz)

- **Written but not run.** `test_equipment_workflow_integration.py` was written
  without access to a local Supabase (no Docker where it was written), so it has only been
  collected and skipped, never executed. Its first run may turn up mistakes in the tests
  themselves rather than in the code. Please run it against a local stack
  (`npx supabase start && npx supabase db reset`, export the local keys, `pytest -m
  integration tests/test_equipment_workflow_integration.py`) and report any failure. The
  Definition of Done item "integration tests ... pass against a local Supabase" stays
  open until someone has.
- It needs the three equipment migrations applied (`20261019100000`, `20261019200000`,
  `20261102000000`); `db reset` applies them with the rest.

## Receive Technical Support Notifications (IS-26, Nawaz, Sprint 4)

Reasoning is in `design-decisions.md` ("Receive Technical Support
Notifications"). Please confirm:

- **Every Technical Support Staff member is told.** Nothing assigns staff to
  a request or event, so "the relevant Technical Support Staff" is the role.
  If the team wants assignment, that is a new story and these hooks would
  take a recipient list.
- **"Equipment becomes unavailable" is NOT built.** The criterion says "when
  the equipment becomes unavailable". Nothing in the app changes a unit's
  status: `equipment_units.status` (available / maintenance / retired) is only
  set in the database or the seed, and the calendar notes there is "no dated
  unavailability for equipment". With no action to hook, a notification would
  have nothing to fire from. When a story adds a way to take a unit out of
  service (or to dated unavailability), the hook is one call to
  `technical_support_event_news`-style code: find the live requests holding
  that unit and tell Technical Support. **Justified by Week 4:**
  "Technical Support Staff maintain equipment status. **Maintenance
  workflow is not core at the moment.**" Taking a unit out of service is
  that maintenance workflow, so this criterion waits for it. Please
  confirm that belongs to a later story.
- **Rescheduling is only news if equipment is arranged.** A change to the
  date or time of a session with no `pending` or `confirmed` request tells
  nobody. A change to the equipment list or room layout is told too (with
  different wording). Please confirm that reading of "affects those
  arrangements".
- **A reschedule does not move the request.** The request's `needed_start`
  and `needed_end` are still the old window (IS-17 snapshots them), so
  Technical Support are told to check, and the coordinator has to withdraw
  (IS-66) and ask again. `change_impact` already tells the coordinator the
  request "will not move automatically". Whether the request should follow
  the event is a separate story.
- **Event cancelled is told only if a request was live.** A pending request
  stays `pending` on a cancelled event (Release Equipment on Cancel frees
  confirmed units only), so the notification tells Technical Support to clear
  it.
- **The notification links to the session's first live request.** There can
  be several; the event page is not open to Technical Support.
- **Not notified here:** a request accepted or rejected by Technical Support
  (the coordinator is told, IS-69; the decider is not), and the other
  roles' notification stories (IS-23, IS-24, IS-25).

## Notification (Event Organizer) (IS-23, Nawaz, Sprint 4)

Reasoning is in `design-decisions.md` ("Notification (Event Organizer)").
Please confirm:

- **~~"Clarification or amendment" is NOT built.~~ Resolved: built as the
  clarification thread** (`app/events/clarification_service.py`; see
  `design-decisions.md` "Clarification thread"). The organizer is now
  notified when the coordinator sends a clarification request. Original
  note, kept for the record: The criterion says "Given an
  Event Coordinator requests clarification or amendment, when the request is
  made, then the Event Organizer receives a notification". There is no such
  request in the app: the coordinator can approve or reject (rejection needs a
  reason, which the organizer is now told about), and `event_service.py`
  already notes that replying to coordinator feedback "depends on a
  clarification/feedback record that doesn't exist". With nothing to hook, a
  notification has nothing to fire from. A rejection is the nearest thing and
  is covered. Please confirm a clarification step is a separate story, or say
  whether rejecting-with-a-reason is meant to be it.
- **The organizer is not told when their own change request is decided.**
  IS-21 lets the organizer ask for a change and the coordinator approve or
  reject it with a comment; that is not in IS-23's list, so nothing is sent.
  It reads like it should be. Say if it is wanted (one more hook in
  `change_request_service`).
- **Several sessions mean several "confirmed" and "cancelled"
  notifications.** Approve and reject are one per request; confirm and cancel
  are per session. Say if the organizer would rather have one.
- **Not told:** a session moving to planning or completed, and the
  coordinator being assigned (the Lead's step; the organizer sees the status
  move to under review).

## Notification (Event Coordinator) (IS-24, Nawaz, Sprint 4)

Reasoning is in `design-decisions.md` ("Notification (Event Coordinator)").
Please confirm:

- **"Incomplete arrangements ... require attention" is NOT built.** The last
  criterion asks for a notification when an upcoming assigned event still has
  outstanding arrangements. That is a reminder: nothing in the app runs on a
  schedule (IS-69 listed reminders as out of scope), and "incomplete" is not
  defined (no venue booking? no equipment request? both?). It needs a
  scheduler and a definition. Please confirm it is a separate story, or give
  the definition and where a scheduled job may run.
- **An ordinary change request is not notified**, only a significant one, as
  the criterion says. Say if the coordinator should hear about every request.
- **"Change the booking" is read as a venue block.** If Venue Staff are meant
  to be able to move a booking some other way, that way does not exist yet.
- **An expired tentative hold is not notified (IS-24 AC7, NOT built).**
  Jira's IS-24 lists it ("Event Coordinator should be informed before or
  when the tentatively held venue for an event expires"), but the system
  releases an expired hold silently (`release_expired_hold`). Telling the
  coordinator "before" it expires needs a scheduled job, like the
  reminders above; telling them "when" it expires could hook into
  `release_expired_hold`. Not built yet -- please confirm whether it's
  wanted for this release.

## Notification (Venue Staff) (IS-25, Nawaz, Sprint 4)

Reasoning is in `design-decisions.md` ("Notification (Venue Staff)"). Please
confirm:

- **Every Venue Staff member is told.** Nothing assigns staff to a venue or a
  booking. If the team wants assignment (or a venue manager), that is a new
  story and these hooks would take a recipient list.
- **"A change that affects the venue" is attendance, room layout and
  accessibility needs.** That is the list the coordinator is already warned
  about (`change_impact`). Facility needs, which a venue is also chosen for,
  are not a field a coordinator can change on the session today. Say if
  another field should be on the list.
- **Only a session with a pending or confirmed booking is news.** A change or
  cancellation of a session with no booking (or a rejected one) tells nobody.
- **A booking the coordinator cancels, or a block that releases it, is not
  told to Venue Staff.** The first is Venue Staff's own queue losing an item
  the criterion does not list; the second is Venue Staff's own action.
  Say if Venue Staff should hear when a coordinator withdraws a request.
- **A reschedule does not move the booking.** The booking keeps its old
  window (the booking snapshots it); Venue Staff are told to check, and the
  coordinator has to cancel and ask again. Whether it should follow the event
  is a separate story.

## Overwrite Venue Booking (Josiah, 3 Nov)

Decisions made where the AC was silent or (per design-decisions.md) read
narrowly on purpose. Please confirm:

- **AC2 needed no new code.** "Set status of a venue to under maintenance,
  with dates/timings and a reason" is read as describing the existing
  venue-blocking mechanism (`venue_blocks`, `reason='maintenance'`), not a
  demand to also flip `venues.status`. If the story's author actually meant
  a literal status flip in addition to blocking, that's new scope.
- ~~**The revert-to-planning scope is `confirmed` only, not also
  `safety_review`**~~ **Resolved, 3 Nov: the team decided NOT to waste a
  Safety Officer's time reviewing a session whose venue was just
  overwritten.** The route now reverts from `safety_review` too (same scope
  as `delete_venue`, withdrawing the pending review first) -- see
  `docs/design-decisions.md`. `cancel_booking` (IS-9) was deliberately left
  unchanged, still `confirmed`-only, so the same question is open there too:
  should a coordinator's own cancellation also revert a `safety_review`
  session, for the same reason? Not changed here since it wasn't part of
  this story -- worth a team decision of its own.
- **No stronger relationship check than "any venue_staff, any confirmed
  booking."** Like booking approve/reject, there's no per-venue-staff
  assignment table, so any Venue Staff member can overwrite any confirmed
  booking, not just ones for venues they "own" (no such ownership concept
  exists anywhere in this codebase).
- **The Jira board had this story marked "Done" with nothing built.**
  Flagged separately to the team; not something this entry can fix.

## Clarification thread (Event Review and Approval, Justin, 4 Nov)

Built; reasoning in `docs/design-decisions.md` ("Clarification thread").
Interpretive calls the story text didn't settle -- please confirm:

- **Open only while "under review".** The story says "Given that an event
  request is under review" and Week 4 puts clarification inside review, so
  no new messages can be sent once the request is approved or rejected
  (the thread stays readable). Changes after approval go through Request
  Change. Say if the conversation should stay open later (e.g. until
  completed/cancelled) -- a one-line change to the two posting rules.
- **The organiser can only reply, never start a thread.** They already
  have Request Change for anything they want changed. Confirm they don't
  need to open a conversation of their own.
- **The Event Coordinator Lead can't see the thread.** Only the owning
  organiser and the current assigned coordinator. A coordinator the
  request was reassigned away from loses access; the new one sees the
  whole history. Say if the Lead should be able to read it.
- **One thread per event request, not per session.** Every session of a
  request shares the conversation, matching how approve/reject decide the
  whole request.
- **1000-character limit per message.** Not in the story; chosen as a
  sensible cap. Say if a different limit is wanted.

## Completed Status -- coordinator UI (IS-38, Aaralyn, 5 Nov)

The backend for IS-38 (`rule_event_complete`, `POST /events/<id>/complete`,
the `(confirmed, completed)` edge, read-only rules) shipped in Sprint 2.
This adds the coordinator's "Mark as Completed" button so the story can
actually be used. Reasoning in `docs/design-decisions.md` ("Completed
Status -- coordinator UI"). Please confirm:

- **"After it has taken place" is not enforced.** The story says the
  coordinator marks an event completed "after it has taken place", but
  neither AC says it, and the backend accepts any confirmed session,
  including one dated next year. We kept that behaviour (the button
  appears as soon as a session is confirmed, and the confirmation prompt
  tells the coordinator to only do this once it has taken place) rather
  than changing the merged route. If completion should be refused until
  the session's end date/time has passed, that's a small rule/route change
  plus the matching UI gate. Note the e2e golden path completes a
  far-future session, so it would need a past-dated fixture instead.
- **Per session, not per request.** "Mark as Completed" completes the
  session being viewed, the same as Cancel Event and the route itself.
  Approve / Reject / Start Planning act on the whole request. Sessions of
  one request happen on different days, so completing each as it finishes
  seemed right. Say if one click should complete every confirmed session
  of the request.
- **No reason is asked for and nobody is notified.** The story asks for
  neither. The status change is still recorded with its actor in the
  event's status history. Say if the organiser or attendees should be
  notified.

## HTTP error status codes (IS-73, Terry, 2026-11-06)

- **Anonymous callers can tell real routes from unknown ones.** Flask matches
  the URL before the auth hook runs, and the hook skips a request that matched
  no route, so without a token a real protected route gives 401, an unknown path
  gives 404, and a wrong method gives 405 with an `Allow` header. This isn't new:
  before IS-73 the same probe gave 401 against 500. IS-73 leaves the hook alone.
  Closing the gap means requiring a token on unmatched requests in
  `app/auth/context.py`, so anonymous callers get 401 everywhere but `@public`
  routes, at the cost of a token check and database reads on every authenticated
  404. Say if that's wanted; it would be its own change.
  `test_anonymous_caller_gets_the_same_404_as_an_authenticated_one` pins today's
  behaviour and would need updating.

## Operating hours (IS-11 AC5, Nawaz, 6 Nov)

Agreed with Aaralyn (product owner) on 6 Nov: hours are optional, one window
per venue that is the same every day; a new booking request outside them is
refused; existing bookings stay as they are when the hours change; done
under IS-11. These are the calls made beyond that:

- **The whole booked period must fit, setup and turnaround included.**
  Staff are at the venue during setup and turnaround too. Asked on 6 Nov,
  not yet answered; built this way. If only the event's own times should
  count, `_check_operating_hours` is given the session window instead.
- **A multi-day session is outside the hours.** The booked period must fit
  inside one window, so a session from 1 Nov 09:00 to 2 Nov 17:00 is
  refused at a venue with set hours (a venue with no set hours still takes it). Please
  confirm, or say if a multi-day session should be read as "these hours on
  each day".
- **A closing time of 23:59 is "open until midnight" on the calendar**, so
  no one-minute "closed" entry is shown. A booking still has to end by
  23:59, because the booking check compares the exact time.
- **Resolved (6 Nov, Aaralyn): overnight windows are allowed.** A closing
  time earlier than the opening time closes the next day, so 20:00-01:00 and
  08:00-00:00 ("until midnight") can be entered, and a booking may run past
  midnight inside such a window. Opening and closing can't be the same time
  (leave both empty for no set hours). The calendar shows the daytime gap
  (01:00-20:00) as closed.
- **An older pending request outside new hours can still be approved.**
  "Existing bookings stay the same" is read as covering requests made
  before the hours changed, not only confirmed ones; only a new request is
  checked.
- **The coordinator's suitability check doesn't warn about hours yet.** A
  request outside the hours is refused with the venue's hours and the
  booked period in the message, but the venue cards on the request page
  (IS-13) don't flag it before submitting. A reasonable follow-up.
- **The database doesn't check the order of the two times.** It already
  refuses half a window (`venues_operating_hours_consistent`); closing after
  opening is checked by the backend and the form only, so no migration was
  needed.

