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

- **IS-36: "status gates venue/equipment search" could not be gated.** No
  route requests a venue *for an event*. The venue catalogue is read-only
  and per-venue, so there's nothing event-scoped to put a status check on,
  and equipment doesn't exist at all. Once the Venue Booking Request story
  adds a request-a-venue-for-this-event route, its rule should require
  status `planning`.

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
  With no notifications yet, we move them up automatically. Confirm.

- **Not built yet:** notifications (Notification story), editing a
  registration after submitting it, and organiser/coordinator views of who
  registered.

- **Organiser "discretion" and manual closing.** Week 4 says organisers have
  discretion over registration and close it manually. Here the window the
  organiser sets per session is what opens and closes registration; closing
  early would be moving the close time. Organisers can't yet edit a
  confirmed event (field-locking for confirmed events isn't built either).

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

- **Operating hours are stored but not yet rendered hour-by-hour.**
  `venues.operating_hours_start/end` exist and are returned by the API,
  and the calendar page shows them as a text note, but nothing yet
  visually marks out-of-hours time within a day/week view (AC:
  "periods outside the venue's operating hours are shown as
  unavailable"). The wireframe itself doesn't show this either -- its
  month grid has no hour axis to mark. A real hour-level day/week grid
  is a reasonable follow-up, not done here.

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

- **Facilities can never actually be assessed for IS-13.** The AC says to
  check "required facilities recorded for the event," but no story has
  ever added a required-facilities field to `events` -- only
  `equipment_needed`, which is a different (Technical Support Staff)
  concept. Every suitability check currently reports Facilities as
  "not assessed," which is an honest use of the AC's own "requirements
  that have not yet been recorded" clause, not a shortcut -- but if a
  future story adds a real venue-facilities-required field to events,
  this check should start reading it.

- **Empty accessibility_needs is treated as "not recorded," not "none
  needed."** The schema can't tell the two apart (both are just an empty
  array), so `checkSuitabilityForEvent` reports "not assessed" either way.
  If the team later wants event creation to distinguish "I checked and
  need nothing extra" from "I haven't filled this in," that's a schema
  change this check should then read.

- **"Retired or withdrawn" venues don't exist as a concept.** IS-12's AC
  says they should be excluded from results. `venues.status` only has
  available/occupied/maintenance -- nothing means retired. Nothing is
  silently excluded because nothing can be retired yet; flagged rather
  than assumed irrelevant.

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

- **Cancelling a venue booking doesn't change the event's status.** A
  confirmed event that loses its only confirmed venue stays confirmed. A
  change to the event's details sends it back to planning (AC10); should
  cancelling a confirmed booking of a confirmed event do the same?

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

- **Calendar range is a day off in UTC+8 -- the venue calendar is
  affected now.** `lib/calendar.js::toISODate` uses `toISOString()`, so
  local midnight in Singapore becomes the previous UTC date. The venue
  calendar's November query is `2026-10-31..2026-11-29`. The backend
  (`CalendarRange.overlaps`) compares the UTC times PostgREST returns
  against those days, so on the venue calendar:
  - a booking on the last day of the month after 08:00 SGT is missing
    from the month view;
  - in the day view, a booking after 08:00 on the chosen day is missing,
    and the previous day's late bookings are shown instead.

  Fixing only the dates moves the gap to the first day's 00:00-08:00. The
  equipment calendar works around it by asking for a day more on each side
  (`widenRange`). The real fix is in the shared code: interpret calendar
  days as Singapore days on the backend, and send local dates from the
  frontend. That changes the venue calendar, so it needs Nawaz's sign-off.

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
  - **The page asks for one day more than the month on each side**
    (`widenRange`), to work around the UTC+8 range defect above.
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
- **The comment is required to reject or request changes, optional to
  approve.** Week 9 says the officer updates the status "with a comment";
  read as "a comment where one is needed to act on".
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
  queue (IS-18); no notification is sent (no notification system exists yet).
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
- **No notification.** `_notify_request_decision` is a no-op placeholder
  like the venue one; the Notification System story is not built.
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
  which is still a print placeholder. No notification system exists yet;
  wiring it up is a one-line change when one does.
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
- **Notification** uses the same `_notify_request_decision` placeholder as
  accept/reject ("change accepted" / "change rejected"). The coordinator sees
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
