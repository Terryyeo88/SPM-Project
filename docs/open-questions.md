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
  instructions' Venue Catalogue description); Reassign Coordinator and
  an event's own detail page to event_coordinator (plus event_organizer
  for the detail page, since an organiser can view/edit their own
  event). This mapping isn't specified anywhere in the stories — it's
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

- **The `approved → planning` transition is a side effect of requesting a
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

- **PR #18's migration timestamp is already used on main.** PR #18 adds
  `20261004000000_venue_bookings.sql`. Main already has
  `20261004000000_coordinator_lead_role.sql`. Supabase identifies migrations
  by that number, so two files sharing it will clash on `db reset`. Git
  won't flag this because the file names differ. The PR's file needs a new,
  later timestamp before it merges.

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

- **IS-47 has no data to read.** There are no `equipment` or
  `equipment_reservations` tables in migrations or on the live database.
  Equipment exists only as a free-form `events.equipment_needed` jsonb list.
  Question for Justin (PO): which story creates the equipment inventory and
  reservations, and what should the calendar show (per item or per type,
  quantity or just booked/free, which roles can see it)? IS-47 needs those
  answers before it can be built.

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
  on `VenueBookingReviewView.vue` is a frontend change in Josiah's view.
