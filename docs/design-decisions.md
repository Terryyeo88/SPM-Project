# Design decisions

Short entries for choices made on IS-1 (User Authorisation and Authentication)
that aren't obvious from the code alone. One paragraph each, written to defend
out loud, not as a changelog.

## Flask is the authoritative authorisation layer; RLS is defence-in-depth only

This was a fixed architecture decision going into the project, not one made
mid-ticket, but it's the premise everything else here stands on, so it's
worth stating with its reasoning. Supabase gives you two places to enforce
access control: Postgres RLS policies, and whatever the backend checks
before it ever issues a query. We chose the backend (this module,
`app.authz`) as the real decision-maker, and left RLS on every table as a
permissive Sprint-1 placeholder (`auth.role() = 'authenticated'`, nothing
row-scoped) — see the comments in `supabase/migrations/20260911120000_init_
users_events.sql`. Why not make RLS the real mechanism instead: RLS policies
are SQL predicates evaluated per-row by Postgres, with no access to things
like "is this action currently permitted given the event's status" without
duplicating that logic in SQL, separately from the Python logic that also
needs it for non-DB decisions (e.g. `EVENT_CREATE`, which has no row to
evaluate a policy against at all). Keeping one authoritative place — this
module, tested the way `app/authz/rules.py` is tested — avoids two
implementations of the same rules silently drifting apart. Flask uses the
service role key precisely so it can bypass RLS and be that one place; RLS
stays on as a safety net in case a future bug ever lets an unintended client
query Postgres directly.

## Supabase client construction is lazy, not eager at import time

`app/extensions.py`'s `supabase` object used to build the real client (and
validate `SUPABASE_URL`/`SUPABASE_SERVICE_ROLE_KEY` are set) the moment the
module was imported — which meant importing ANYTHING that touched it, even
transitively, required real credentials to even load, let alone run. That
directly blocks Phase 6's CI requirement: unit tests must import the whole
app with zero secrets configured. Fixed by making `supabase` a thin proxy
(`_LazySupabaseClient`) that builds the real client on first actual use
(`.table(...)`, `.auth`, etc.), not on import or construction. Validation
still happens, still fails fast, still names the missing variable — just at
the moment something would have genuinely needed credentials, not before.
This is also why `/health` can return 200 with no `.env` at all: importing
the app factory never forces that validation to run.

## Roles are looked up per request, not embedded as JWT claims

Supabase supports a Custom Access Token Hook that can stamp extra claims
(like roles) directly into the JWT at sign-in, so the backend could read
roles off the token itself instead of querying `user_roles` on every
request. Chose the per-request DB lookup instead, for one concrete reason:
roles can change between sign-in and the token's expiry (a coordinator could
be granted `event_organizer` mid-session), and a claim baked into the token
at sign-in time doesn't see that change until the user re-authenticates —
the access token's own lifetime becomes a window where the system enforces
stale permissions. A per-request lookup is always current. The cost is
explicitly paid for, not ignored: `app/auth/context.py`'s before_request
hook does exactly ONE query for profile+roles per request (a joined
`profiles` + `user_roles` select, not N+1), the same "one query, not one per
policy check" constraint the idle-timeout check also follows.

## Idle timeout: server-side tracking, not short-lived tokens

The acceptance criterion is "given a user session, when it's been idle beyond
a defined timeout, the user is logged out and must re-authenticate." Two
designs were on the table: (a) track last-activity server-side, keyed by the
access token's `session_id` claim, and reject once too much real time has
passed since the last authenticated request; or (b) lean on short
access-token lifetimes plus refresh-token rotation, with the frontend simply
stopping its refresh calls once it decides the user is idle. (b) was rejected
because the backend has no way to enforce it independently of the frontend —
"stop refreshing" is a client-side decision, and a modified or buggy client
could keep refreshing forever, silently defeating the control. For something
that's explicitly a security acceptance criterion, a control the client can
ignore isn't a control. (a) means the backend decides, on every request,
using its own record of real elapsed time — it can't be bypassed by anything
the frontend does or doesn't do. The frontend is still free to add its own
inactivity detection on top, as UX polish (faster, friendlier logout, less
wasted refresh traffic), but that's optional and doesn't change what actually
enforces the timeout.

## 403 vs 404: decided by relationship, not by caller judgement

Phase 2 ruled that a 403 and a 404 must be indistinguishable to a caller who
isn't entitled to know a resource exists, without saying exactly how that
gets decided case by case. The rule landed on in Phase 4: every authorisation
rule checks the caller's *relationship* to the resource before anything
else. No relationship at all (not your event, not the event you're assigned
to coordinate) means you aren't entitled to know it exists, full stop — 404.
A relationship that exists, blocked by some other condition (wrong status,
wrong coordinator-of-record, event already past the stage where this action
applies) means you already legitimately know the resource is there — 403
leaks nothing a 404 would have hidden, and is the more honest answer. This
is encoded once, inside each rule in `app/authz/rules.py`, as a `Decision`
(`ALLOW` / `DENY_NOT_FOUND` / `DENY_FORBIDDEN`) — not left to whoever calls
`authorise()` to decide per call site. The alternative (a caller-side
judgement call) is how the same action ends up 403 in one route and 404 in
another for what's actually the same underlying reason. Two categories fall
outside that relationship test because there's no resource to have a
relationship with at all: an unregistered/unknown action (a wiring bug, not
an access decision — always 403, loudly, so the gap doesn't get mistaken for
a real denial) and role-only actions like creating or listing events (always
403 when denied — there's nothing to hide, only permission to withhold).

## Field-level visibility is deliberately NOT part of can()

"An attendee sees no internal planning information" sounds like an
authorisation rule, but it isn't one: `can()` answers exactly one kind of
question — may this user perform this action on this resource, yes or no —
and "which fields of an event are in the response body" isn't that kind of
question, it's a serialisation decision. Bolting it on would mean either
`can()` starts returning something richer than a boolean (breaking every
other caller's mental model of what it does) or rules.py starts knowing
about response shapes (breaking the purity that makes rules testable with
no Flask/DB at all — see `app/authz/rules.py`'s docstring). Decided to defer
this entirely rather than half-build a `visible_fields()` helper now: no
event route or serialiser exists yet to call it, and "internal planning
information" isn't tied to specific named columns anywhere in the schema or
a quoted story — building the helper now means guessing at a field list
that whoever actually writes the serialiser will have to redo anyway once
they know what the response needs to contain. Whoever builds the event
routes should add their own serialisation-layer mechanism then, informed by
the real response shape, not by a guess made here.

## event.cancel covers approved, planning, AND confirmed

The Cancelled Status story says a coordinator "can change status to
cancelled after approval of the event request", and the literal wording
names only "approved". Decided that the cancellable set is nonetheless
`approved, planning, confirmed` — not narrowed to the single word "approved"
— because the same story is explicitly about a coordinator who cannot secure
a venue or equipment, and that failure mode happens during planning, not at
the instant approval is granted. Reading "after approval" as the single
status `approved` would make the story's own scenario impossible to
implement: a coordinator who discovers the venue fell through a week into
planning would have no way to cancel. Reading it instead as "anywhere in
the post-approval lifecycle, up to but not including completion" makes the
story implementable and matches the migration's own ordering (`approved ->
planning -> confirmed -> completed`). `completed` stays excluded — cancelling
a finished event answers a different question than this story asks.
Recorded here as a decision, not an inference: `docs/open-questions.md` has
a line asking the customer to confirm "after approval" was meant as a range,
not as a request to re-derive the set from scratch.

## Coordinator edit window is one action, two role-dependent status windows

`event.edit` was originally organiser-only, gated to `draft` — which meant
no rule anywhere let a coordinator edit anything, contradicting the Event
Information Management story (coordinator updates event information during
planning). Two ways to close that: add a second action (e.g.
`event.update_planning`), or extend `rule_event_edit` with a second,
independently-gated branch for the coordinator. Chose the second: it's the
same verb (change the event's own fields) on the same resource, just with a
different role and a different status window, and a second action would
only move the real complexity into "why are there two actions for editing
one resource" instead of removing it. The coordinator's window was first
`planning` only, a direct match to the Event Information Management story's
wording ("during planning"). It was widened to `under_review` and `planning`
for IS-31 Submit event request, whose acceptance criteria say that once a
request is submitted "only the Event Coordinator is allowed to edit the
event request". With `planning` alone, nobody could correct a request
while it was under review. For IS-21 (2026-10-08) the team widened it again:
the coordinator "should be able to edit the event details when they want
to", so it is now every status except `completed` (IS-38: read-only going
forward) and `cancelled`. The organiser's side didn't change: after
submission they ask for changes through a change request. One real bug came out of building
this: the first version of the rule returned on whichever relationship
(organiser or coordinator) it found FIRST, regardless of that branch's own
status outcome — which would wrongly deny a user who happens to be both the
organiser and the assigned coordinator of the same event (the schema allows
`organizer_id == coordinator_id`) if the first-checked branch's status
window failed, even when the second branch's would have allowed it. Fixed
by checking both branches before deciding, exactly the failure mode the
multi-role union principle exists to prevent. Regression test:
`test_multi_role_union_on_same_event_for_edit`.

## JWT verification tolerates 10 seconds of clock skew on `iat`

Found in Phase 5, live, the hard way: `verify_token` intermittently rejected
genuinely valid tokens from the real project with `ImmatureSignatureError`
("the token is not yet valid (iat)"). PyJWT checks `iat` isn't in the future
using this machine's local clock, with zero tolerance by default — so any
moment where ordinary clock drift between this machine and Supabase's auth
server put a token's `iat` a few seconds "ahead" of local time caused an
otherwise perfectly valid, freshly-issued token to fail. Reproduced directly:
the same live sign-in call, repeated in a tight loop with no code changes,
failed roughly 1 in 2 times before the fix and 0 in 15 after it. Fixed with
`leeway=10` seconds on the `jwt.decode()` call in `app/auth/jwt.py` — standard
practice for exactly this class of skew, and it does not weaken `exp`
enforcement, which is a separate check. This was never visible to the unit
tests in `test_auth_jwt.py` because they sign tokens with Python's own
`time.time()` at verification time, so there's no skew to trigger — only
`test_jwt_integration.py`, calling the real Supabase auth server, could ever
have found it.

## Live schema was the source of truth when reconciling migrations

By Sprint 2 the live `events` table and the migration files disagreed on six
columns (see `supabase/migrations/20260927000000_reconcile_events_with_live.sql`
for the list). They had drifted because changes were applied in the
dashboard first and the migration files were never written. There were two
ways to close the gap: change the files to match the database, or roll the
database back to match the files. We changed the files, for these reasons:

- **The running code already depends on the live shape.**
  `app/events/event_service.py` writes jsonb lists into
  `accessibility_needs`, a real boolean into `registration_needs`, and a
  jsonb object into `equipment_needed`. `CreateEventView`/`EventDetailsView`
  read those shapes back. Rolling the database back to `text` columns with
  no `equipment_needed` would break event creation on the live system to
  satisfy files that nothing had ever run successfully against.
- **Live rows hold data in those shapes.** A rollback would mean converting
  or discarding real data (jsonb to text loses structure, and
  `equipment_needed` would be dropped outright). Reconciling the files
  destroys nothing.
- **The files were the thing that was wrong.** A migration history exists
  to reproduce the real database. When the two disagree and the database is
  the one users and code are relying on, the history is what's out of date.

The reconciliation migration is therefore written to be a no-op against
live. It uses `add column if not exists`, and each type change is guarded by
an `information_schema` check. Against an empty or stale database it
converts old `text` values with explicit `using` clauses, and it fails
loudly rather than silently nulling a `registration_needs` value it can't
read as a boolean. It drops nothing. That includes the three orphan columns
(`shared_event_id`, `registration_start_datetime`,
`registration_end_datetime`). No code on any branch references them and
every live row is NULL, but removing a column someone may be about to use is
a decision for its owner, not a side effect of a parity fix. They're listed
in `docs/open-questions.md` pending ownership.

The underlying cause, dashboard-first changes, is addressed by a process
rule (README, "Apply migrations"), not by this migration. Without the rule,
the same drift will come back.

### Verified by `supabase db reset` (2026-09-27)

The reconciliation was first checked only by a programmatic diff (replaying
the migration files in a parser and comparing the result to PostgREST's
OpenAPI view of live). That diff couldn't execute SQL, so the following
were then verified against a real local Postgres 17 (`npx supabase db
reset`, CLI 2.118.0):

- **Every migration applies in order from empty with no errors.** This was
  the first time the reconcile file's `do` block, `information_schema`
  guards and `using` clauses had executed anywhere.
- **The migration really does nothing on a second run.** Re-running it against the migrated
  database emitted only "already exists, skipping" notices. The `events`
  table was not rewritten (same `relfilenode`), row hashes were unchanged,
  and a full `pg_dump --schema-only` of `public` was identical before and
  after.
- **Conversions behave as intended on real rows:**
  - `accessibility_needs`: a JSON list becomes a jsonb array; a non-JSON
    string becomes a jsonb string (nothing lost); empty or whitespace-only
    text becomes SQL NULL.
  - `registration_needs`: `true`/`false`/`yes`/` YES `/`0`/`off` convert
    via Postgres's own cast; empty text and NULL become NULL.
  - An unreadable `registration_needs` value (`maybe`) stops the migration
    with an error. Because a migration file runs as one transaction,
    nothing is left half-converted: both columns stay `text` and no rows
    change.
- **All 20 integration tests pass** against the reset database. They rely
  only on `supabase/seed.sql`, not on anything specific to the shared
  project.

### Re-verified by `supabase db reset` (2026-10-16)

`npx supabase db reset` from empty succeeded on 2026-10-16 with all 17
migrations (through `20261015000000_event_logs_significance.sql`) and
`supabase/seed.sql`.

`seed.sql` now also seeds equipment requests and reservations: three
confirmed requests, for the Annual Tech Symposium and both Community
Workshop sessions. Each reservation is worked out from its parent event's
own dates and times (the Symposium's from the evening before its start
date; each Workshop session's an hour either side of its times). They
therefore track their event on any reset date. Because the Workshop
sessions are dated relative to the day of the reset, the reservations may
fall in different calendar months. This was checked with a second reset,
with the session offsets moved 76 days forward to simulate a later reset:
every reservation still landed on its event's day, and
`equipment_reservations_no_unit_overlap` still held.

Not verified: parity of the non-PostgREST objects (the function, triggers,
indexes, RLS policies and constraints) *against live*. The local side was
catalogued, but live's catalog needs a direct Postgres connection
(`DATABASE_URL`), which wasn't configured. Until that comparison is done,
"reproducible" means the files build a working schema, not that the result
matches live exactly in every object PostgREST can't see.

## Tests cannot reach a database they shouldn't: unit tests none, integration tests only a local one

**What happened.** During the IS-36/38/39 work, Justin's approve/reject
logic moved onto `app.events.transitions`. His `test_event_decisions.py`
fixture replaced `event_service`'s Supabase client with a fake, but the
writes now went through `transitions`' client, which the fixture didn't
cover. The root `.env` is loaded whenever the app is imported, so those
"unit" tests sent real requests to the **shared live project**. They were
rejected only because the test's event id, `"event-1"`, isn't a valid UUID.
Nothing was written (verified read-only afterwards), but that was luck.
The same thing happens to any unit test whose fakes miss a single database
call. It was found while retargeting that fixture.

**Why unit tests must be unable to reach any database.** A unit test that
can quietly reach a real database is dangerous whichever way it goes.
- It can write to shared data that teammates are demoing from.
- It can pass for the wrong reason. Proven: a unit test calling `/health/db`
  with no fakes got a real 200 from the live project and passed.
- It can fail confusingly on a machine without credentials, or behind a
  firewall, with a network error that doesn't say what's wrong.

"Unit tests don't touch the database" was already the stated intent (the
conftest docstring said so). Nothing enforced it.

**What the guard does.** `tests/conftest.py::_forbid_database_in_unit_tests`
is an autouse fixture, so it applies to every test and nobody can forget to
opt in. For any test *not* marked `integration`, it replaces
`app.extensions._LazySupabaseClient._get_client` (the single path every use
of the shared `supabase` client goes through) with one that raises
`UnitTestDatabaseAccessError: This unit test tried to reach the database:
<test id> ...`.
- **Why patch the class, not blank `SUPABASE_URL` or rebind the module
  variable.** Every app module holds a reference to the same client
  instance, taken at import time, so rebinding `app.extensions.supabase`
  would reach none of them. Blanking the URL doesn't help once the client
  is cached, which it is after any integration test in the same run. The
  `signing_key` fixture also sets a fake URL on purpose, so a missed fake
  would produce a vague DNS error rather than a clear message. The
  class-level patch works whether or not the client is cached: this was
  verified in a combined run where integration tests had already built it.
- **Why a `BaseException` and not an `Exception`.** App code has broad
  `except Exception` handlers (`/health/db` returns 503, and `create_app`
  turns any Exception into a 500). A normal exception could be swallowed
  there, and the test would pass anyway. A `BaseException` passes through
  both and fails the test by name.
- Tests that substitute their own fake for a module's `supabase` are
  unaffected. Only a call that reaches the real client trips the guard.
- Integration tests are exempt from this guard. The second half below
  governs them.

**Second half: integration tests refuse a non-local database by default.**
The unit-test guard left one path open. The integration-test skip only
fired when credentials were *absent*, and the root `.env` supplies them. So
a teammate typing a bare `pytest` ran all the integration tests (creating
and deleting users, events and audit rows) against the shared project the
team demos from. Now `tests/conftest.py` decides, at collection time,
whether integration tests may run:
- **No credentials** (CI): skipped, with a message on how to run them locally.
- **`SUPABASE_URL` is local:** they run, with no opt-in needed.
- **Anything else:** **skipped, not failed.** Someone running the whole
  suite hasn't done anything wrong. The message names the host and says
  exactly how to run against local instead.
- **Deliberate exception:**
  `INTEGRATION_TESTS_WRITE_TO_REMOTE_SUPABASE=yes-write-test-data-to-the-shared-project`
  (exact value, so `=1` or `=true` is refused and the message says so).
  It's long and explicit, so it can't be set by accident and it reads
  plainly in a shell history.

**How "local" is detected: the URL's host.** A URL counts as local only if
the host is `localhost` or a loopback IP literal (127.0.0.0/8, `::1`), which
is what `npx supabase status` reports. We match the host because that is
exactly where requests, and therefore writes, will go. The one alternative
the CLI offers is its well-known local demo keys (JWT issuer
`supabase-demo`), and it's less reliable. A key says who signed it, not
where requests are sent, so a local key paired with a live URL still writes
to live. The CLI's newer `sb_secret_…` keys aren't JWTs at all. Hostnames
are not DNS-resolved, and anything we can't parse counts as non-local, so
lookalikes such as `127.0.0.1.nip.io` or `localhost.example.com` fail
safe. pytest's header line states the decision on every run.

Together, the two halves make the rule: **unit tests cannot reach any
database, and integration tests cannot reach a non-local one without
someone saying so out loud.**

## Venue Booking Request / Approval (Josiah, Sprint 2, 2026-10-04)

### A booking is keyed to one event SESSION, not the whole multi-session request

`venue_bookings.event_id` references one row of `public.events` directly —
not `shared_event_id`, the id every session of one request shares. Room
layout, expected attendance and accessibility needs are already modelled as
per-session fields (`event_service.py`'s `SESSION_FIELDS`), and a venue has
to suit one session's actual requirements, not some combination across every
session of the request. A two-session conference where session one needs a
200-seat theatre and session two needs a 20-person boardroom has to be able
to book two different venues — keying to `shared_event_id` would make that
unrepresentable.

### `approved → planning` is a side effect of requesting a venue, not a separate feature

> **Superseded (2026-10-15).** The coordinator now moves an event to
> planning themselves with **Start Planning** (`POST
> /events/<id>/start-planning`, a button under "Your Decision" on an
> approved session). `rule_venue_booking_create` accepts `planning` only, and
> `create_booking_request` no longer changes the event's status. This keeps
> the "Planning Status" story's order (planning first, then search for a
> venue) and lines up with IS-9, where arrangements are checked from
> planning on. The reasoning below is kept for history.

The written Event Status Management "Planning Status" story requires an
event to already be in `planning` before a venue/equipment search starts —
but nothing in this codebase transitions any event TO `planning`; that's a
separate, unassigned sub-story, and `app.events.event_service` only ever
writes `draft`/`submitted`/`under_review`/`approved`/`rejected`. Blocking
this entire story on someone else shipping that transition first would make
it unimplementable this sprint. Instead, `rule_venue_booking_create` accepts
`approved` OR `planning`, and `booking_service.create_booking_request`
performs the narrow `approved → planning` UPDATE itself, as a documented side
effect of the FIRST venue booking request against an `approved` event —
directly matching the story's own framing ("the Coordinator has to change
the status to 'planning' before... searching for a venue"). The UPDATE is
conditioned on `.eq("status", "approved")`, same race-proofing idiom as
`event_service._decide`, so two booking requests fired for sibling sessions
at once can't both attempt it, and a no-op when the event is already
`planning` is expected, not an error. Flagged in `docs/open-questions.md` for
whoever eventually owns the Planning Status sub-story to confirm.

### Setup/turnaround buffers: per-venue columns, snapshotted onto the booking at creation

The customer's wireframe shows a per-venue "Standard Turnaround" field on the
venue's own profile, not a single global constant — so `setup_minutes`/
`turnaround_minutes` are columns on `venues` (default 30), not an env var.
Each `venue_bookings` row copies the venue's buffer values at the moment the
request is created (`booking_service.create_booking_request`), rather than
re-reading the venue row every time the booking's padded span matters. A
venue's buffers can change after bookings against it already exist (new
venue management policy, a correction); without the snapshot, that change
would retroactively shift the blocked period of a booking that was already
decided — possibly uncancelling a conflict a Venue Staff member already
confirmed didn't exist. The booking is a record of what was true when it was
requested, not a live reference to the venue's current configuration.

### Conflict guard at approval: narrow, confirmed-vs-confirmed only — not the full Conflict Detection story

`booking_service._confirmed_overlap_exists` blocks confirming a booking only
if the SAME venue already has another `confirmed` booking whose padded
`[booking_start, booking_end)` span overlaps. This is the literal reading of
Approval AC1 ("the venue is marked unavailable for that period"), and
nothing more: no pending-vs-pending conflict flagging, no recalculation when
a confirmed booking is later cancelled (no cancellation path exists yet).
That broader behaviour belongs to the separate, unassigned Booking Conflict
Detection story — building it here would mean guessing at a story nobody
assigned this sprint, and risking a shape that story's real owner would have
to unwind. The same check is also surfaced read-only on `get_booking`'s
`conflict` field, computed before any decision is made, so Venue Staff see
the same warning a confirm attempt would hit, in time to decide not to
bother trying.

### Rejection reason lives in the audit log, not on the booking row — both read paths join it in

Mirroring `event_status_log`'s shape (not `coordinator_assignment_log`'s —
see the migration's own comment), `reject_booking` records its reason on
`venue_booking_status_log`, never on `venue_bookings` itself: the booking
row is current state, the log is history, and a reason is inherently a
history fact ("why was THIS decision made"), not current state. Approval
AC2 ("the Coordinator can view it") means `get_booking` and
`list_bookings_for_event` both have to join it back in for a rejected
booking — `booking_service._attach_rejection_reasons` is a direct port of
`event_service._attach_rejections`' own query shape (latest rejection only,
since a booking could in principle be rejected, superseded by a fresh
request, and rejected again).

### Why `list_bookings` embeds `events(name)`/`venues(name)` but the per-event list doesn't

`list_bookings` is Venue Staff's queue — it spans every venue and every
event at once, so a bare `event_id`/`venue_id` per row is useless for
recognising which request is which; it embeds the related row's `name` via
a PostgREST relationship select, same idiom as `_attach_rejections`' own
`profiles(name)` embed. `list_bookings_for_event`, by contrast, is always
called with one already-known event in view (the event details page's own
Venue Booking section) — the caller already has that event's name, so
embedding it a second time would be redundant.

## Status transitions: one guarded path, edges as data

Every change to `events.status` goes through
`app/events/transitions.py::transition()`. Four decisions shape it.

**The edge set is data, not branching.** `ALLOWED` is a frozenset of
`(from, to)` pairs, each paired in `_EDGE_SOURCES` with the story sentence
it comes from. An illegal transition is a *missing entry*, not a *missing
`if`*. "What can a planning event become?" is answered by reading one
table, a new lifecycle step is a one-line, reviewable diff, and a test can
assert the whole set in one comparison
(`test_edge_set_is_exactly_the_sourced_edges`). With branching logic, the
same question means reading every code path that writes a status. Before
this change there were four such paths, and only one of them checked
anything.

**The expected status is in the WHERE clause, not checked by a read and
then a write.** The update is `UPDATE events SET status = :to WHERE id = :id
AND status = :from`, and the row count is checked afterwards. Postgres
evaluates that WHERE against the row's current committed value while
holding the row lock. Two requests racing from the same status therefore
cannot both match: exactly one updates a row and the other updates zero,
which becomes a 409 `status_conflict`. A read-then-write cannot give this
guarantee. The read and the write are separate moments, so a change
between them is silently overwritten, and the value the old code wrote
back could even revert someone else's change (the old `under_review`
write did exactly that). Proven against real Postgres: 10 simultaneous
`approved → planning` attempts give 1 winner and 9 conflicts. With the
status filter removed, the same race gives 10 "winners" and 10 history
rows for one real change. We never retry a conflict automatically. A retry
would re-apply a decision the user made about a state that no longer
exists.

**Authorisation and the state machine are separate.** `@require` answers
"may *this user* do this to *this event*" (relationship and role, giving a
403 or 404). `transition()` answers "is this *edge* legal at all, and is the
event still where we think it is" (giving a 409 or 400). Each is a pure
function of different inputs: rules of `(user, event)`, edges of `(from,
to, reason)`. So each is tested without building the other's fixtures.
Merged, every state-machine test would need users and every authz test
would need edges. The status precondition therefore appears twice: in the
rule, which decides the 403, and in `ALLOWED`, which decides legality. This
is deliberate, and the route passes `expected_from=event.status` so the
write is conditional on exactly the state authz approved.

**Reasons live in `event_status_log`, not on `events`.** IS-39's
cancellation reason and the Approved/Rejected story's rejection reason are
the same thing: metadata about a *transition*, not a property of the
event. An event can be rejected, fixed and resubmitted, then rejected
again. A `rejection_reason` or `cancellation_reason` column would keep
only the last one and lose the record the Week 4 clarification asks us to
keep. The same table also serves the Activity History and Change History
core features (who changed what, when, and why). **Do not add
`cancellation_reason`, `rejection_reason` or similar columns to
`events`.** Write a transition with a reason, and read it back from
`event_status_log` (`GET /events/<id>/status-history`). The table is
Justin's `20260929000000_event_status_log.sql`. We reused it rather than
creating a second history table.

**Known non-atomic pair.** The status update and the history insert are two
PostgREST requests, not one transaction. If the insert fails after the
update succeeds, the event has moved with no audit row, the caller sees a
500, and a retry gets a 409. We accept this for now. The fix, if it's ever
needed, is a single Postgres function (RPC) that does both statements in
one transaction. We are not building an outbox or anything two-phase.

## `event_status_log.changed_by` stays nullable (a trade-off we chose not to take)

We considered making `changed_by` NOT NULL, so that an unattributed audit
row would be impossible, and decided against it. A genuinely
system-initiated transition in future (a scheduled job marking past events
completed, say) would have no honest actor. Forcing a value would mean
inventing a "system" user or recording a lie. The convention instead is:
**NULL means "no human actor", and nothing in the current design produces
one.** Every transition we build records a real person. Auto-assignment's
`submitted → under_review` (and a resubmission's return to review) is
attributed to the organiser whose submit request triggered it, because that
request caused it. `assign_initial_coordinator(event_id, actor=None)` keeps
`actor` optional only for backward compatibility: the submit path always
passes it, so a NULL row means a caller outside that path. So in practice there
are no NULL rows. If one ever appears, it is either a deliberate
system transition or a bug. The schema is left exactly as Justin wrote it.

## Attendee Registration: one database call decides confirmed or waitlisted

Registering is "count the session's confirmed registrations, then insert as
confirmed or waitlisted". Done as two requests from Python, two attendees
racing for the last place can both see it free and both be confirmed. So
the decision and the insert are one Postgres function,
`public.register_attendee`, which locks the session's events row
(`SELECT ... FOR UPDATE`) first: registrations for the same session queue
behind each other and each sees the count the previous one left. Checked
against Postgres 16 with 20 simultaneous registrations for a session with
capacity 5: exactly 5 confirmed, 15 waitlisted.

The function also re-checks "confirmed and enabled" and the registration
window, using the database clock, so neither can be bypassed. It returns an
outcome (`registered`, `not_open`, `not_started`, `closed`,
`already_registered`, `not_found`) instead of raising, and the service maps
each to a message an attendee can act on.

Other decisions, from the story and the Week 2/4 clarifications:

- **Per session.** `registration_needs` and the registration window are
  already per session, so an attendee registers for a session.
- **Capacity = the session's `expected_attendance`.** No new field. `NULL`
  means no limit.
- **Every session has a waiting list,** first come, first served ("waiting
  list supported"). Position = order of `registered_at`.
- **Registration information follows the Edit Profile wireframe:** full
  name and organisation (shown read-only, from the profile), email and phone
  (required, editable), "Email notifications" / "SMS notifications" (either
  or both, at least one), and optional notes. The attendee can't change their
  name or organisation here, only choose whether their organisation is
  included. The form prefills from the profile: name and email today, and
  phone, organisation and notification choices automatically once a profile
  story adds `phone`, `organisation`, `notify_email` / `notify_sms` to
  `GET /me` (`prefillFromProfile` in `frontend/src/lib/registrations.js`; the
  backend reads the organisation from the profile row). What's stored is
  what the attendee submitted for that registration, so editing a profile
  later doesn't rewrite past registrations.
- **Withdrawing moves the next person up.** `public.withdraw_registration`
  deletes the registration and, if it held a confirmed place, confirms the
  first waitlisted attendee (by `registered_at`) in the same call, under the
  same session lock as registering. Checked against Postgres 16: 30
  attendees registering and 5 withdrawing at once on a 5-place session left
  exactly 5 confirmed and 20 waitlisted. Not allowed once the session has
  started.
- **Screens follow the attendee wireframes:** the attendee dashboard
  (search, Registered Events, Waiting List, result cards tagged Open /
  Almost Full / Waitlist Only) and an event page with spots filled and
  Register / Withdraw Registration / Leave Waiting List. The wireframe's
  event image, venue, category and location search are left out: events
  have none of those yet.
- **Attendees only see public fields** of a session (name, description,
  dates and times, registration window, places left) -- the briefing: "an
  Attendee should not be able to view internal planning information".
- **`registrations` has RLS on and no policies.** Nothing can read or write
  it through the anon/authenticated keys; only the backend's service role.


## View Events Without Registration (Justin, 2026-10-24)

The briefing makes registration optional per event ("Where enabled",
"Where registration is required"), so attendees should also be able to see
confirmed events they can simply turn up to.

- **One list, no filter.** `GET /registrations/open` now returns every
  upcoming confirmed session, with or without registration, each carrying
  `registration_needs`. The dashboard shows them together, each labelled
  "Registration required" or "No registration required".
- **"Public to attendees" is now just "confirmed"** for viewing
  (`rule_event_view_public`). Registering still needs confirmed *and*
  `registration_needs = true`. An attendee registering for a confirmed
  session without registration gets a 403, not a 404, because they can
  already see it exists.
- **No places for sessions without registration.** `capacity`,
  `places_left` and the counts are null/0 for them, and they aren't
  counted, so the page shows no spots bar, Register button or registration
  period.
- **No bookmarks and no notifications** for these events. Bookmarking isn't
  a customer requirement. If it's added, decide whether bookmarked events
  should notify, since the Attendee Notification story only notifies
  registered or waitlisted attendees.


## View Event Venue (Justin, 2026-10-24)

- **Confirmed bookings only, every one of them.** Each session in
  `GET /registrations/open` and `GET /registrations/sessions/<id>` carries
  `venues: [{name, location}]` from its confirmed `venue_bookings`. An event
  can use several venues (Week 7 #3), so all are listed (by name, each venue
  once). Pending, rejected and cancelled bookings never appear.
- **Name and location only.** Booking status, requester and notes stay
  internal (briefing 8b).
- **A permanently deleted venue** keeps its name on the booking (IS-61), so
  the name still shows, without a location.
- **No venue yet** shows as "Venue to be confirmed".
- **No searching by venue.** The briefing's general Search and Filtering
  lists venue as an example criterion, but no story asks for it.


## Booking conflicts (IS-16, Terry, Sprint 2, 2026-10-05)

Stacked on Venue Booking Request / Approval (PR #18). Josiah's table and
code are unchanged; IS-16 adds one migration, one reporting module and one
route.

### Prevention is a database guarantee; reporting is a query. Two mechanisms on purpose

IS-16 asks for two different things, and no single mechanism does both.

- **Prevent** two confirmed bookings of one venue from overlapping. This is
  the exclusion constraint `venue_bookings_no_confirmed_overlap`
  (`20261006000000_venue_booking_no_overlap.sql`). An application check
  can't guarantee it: `confirm_booking` reads ("any confirmed overlap?") and
  `_decide_booking` writes in a separate statement, so two Venue Staff
  confirming two overlapping pending bookings at the same moment both read
  "no" and both write. The constraint is checked inside the write.
  Postgres evaluates exclusion constraints on UPDATE as well as INSERT, so
  the pending → confirmed UPDATE is the moment the row enters the
  constraint's scope and is checked.
- **Report** which confirmed bookings a request clashes with, so Venue
  Staff can see why. That's `app.venues.booking_conflicts`, exposed as
  `GET /venues/bookings/<id>/conflicts`. A constraint can't do this. It
  only fails a write, it names nothing useful to a person, and it can't be
  asked "what would this clash with?" before anyone tries to confirm.

They're kept separate so that neither has to do the other's job badly. A
query alone has the race. Treating the constraint as a report would mean
attempting a confirm just to find out, and parsing a Postgres error for
the answer.

Josiah's `_confirmed_overlap_exists` stays as it is. It gives the friendly
message before a confirm and the read-only `conflict` flag on
`get_booking`.

### The report reuses Josiah's predicate rather than adding a second one

`_confirmed_overlap_exists` already answers "is there a clash", but it
stops at the first match. The only missing piece was "which ones", so
`confirmed_clashes` uses the same `_BLOCKING_STATUSES` and the same
`_spans_overlap` and collects every match. The list and the `conflict` flag
therefore can't disagree. The constraint uses the same definition:
`'[)'` ranges match `_spans_overlap`'s `a_start < b_end and b_start <
a_end`, so a booking ending at 14:00 doesn't clash with one starting at
14:00. `test_booking_conflicts_integration.py` checks that the report and
the constraint agree at those boundaries.

The query lives in a service module like every other read, not in a SQL
view or function. That keeps the migration to the guarantee alone, and the
filtering logic is unit-testable without a database. The route has its own
blueprint, so IS-16 edits none of IS-14's files.

### Turnaround comes for free

The constraint compares `booking_start`/`booking_end`, which Josiah's code
already pads with the venue's setup and turnaround minutes. A clash in the
turnaround window is a clash, with no extra rule.

### A released booking frees its period without extra handling

The constraint has `WHERE (status = 'confirmed')`, the same scope as
`_BLOCKING_STATUSES`. A row takes part only while it's confirmed. Any
change away from `confirmed` removes it from the constraint's scope, and
the period is free for the next confirm. That covers `rejected` today, and
whatever a cancelled event's booking becomes later. #18 has no `cancelled`
booking status (asked on the PR), but the answer doesn't change this:
whichever status is chosen, the booking stops blocking as long as it isn't
`confirmed`. `test_releasing_a_confirmed_booking_frees_its_period` shows
it against real Postgres. Nothing yet moves a booking out of `confirmed`
when its event is cancelled; that's the cancellation path, not IS-16.

### Under true concurrency the loser sees 23P01 or 40P01

When two conflicting confirms race, exactly one wins, every time (30 of 30
measured races). The loser is usually refused with `23P01`
(exclusion_violation). But if both UPDATEs reach the constraint check
before either commits, each waits for the other, and Postgres' deadlock
detector aborts one with `40P01` (deadlock_detected): 5 of the 30. Either
way the outcome is identical: one confirmed row, one refused. Anything that
turns the refusal into a user-facing message has to recognise both codes.

## Request for Event Change (IS-21, Sprint 2, 2026-10-08)

### Change requests live in `event_change_requests`, keyed to the request AND the session

Each change request is one `event_change_requests` row with `shared_event_id` (the
whole multi-session request) and `event_id` (the session it changes).
`shared_event_id` is what lets the event page list every change for the
request in one query; `event_id` is the real foreign key (events'
`shared_event_id` isn't unique, so nothing can reference it) and is what
authz checks against, since coordinators are assigned per session. A
legacy event with no `shared_event_id` uses its own id, the "group of
one" convention event_service already follows.

The requested values are stored here, NOT on `events`, until the assigned
coordinator approves. That is the whole of AC5: the organiser's edit
window (`rule_event_edit`) was never widened, so the only path from a
change request to the event goes through `rule_event_review_change`.

### Who may request a change, when, and who reviews it

`rule_event_request_change`: the owning organiser, from `submitted` through
`confirmed` -- the AC's "an event that has been submitted". Draft and
rejected are excluded because the organiser already edits those directly
(`rule_event_edit`), so a change request there would only be a detour
around their own form; completed (IS-38: read-only) and cancelled are
excluded because nothing is left to change. `submitted` is included even
before a coordinator is assigned: the request is recorded and simply waits.

`rule_event_review_change`: only the assigned coordinator ("the assigned
Event Coordinator can view and review"), in the same status window. The
Lead can see change requests through `event.view` but can't decide them;
anyone else who can see the event gets a 403, an outsider a 404 -- the
usual relationship-first rule. Flagged in docs/open-questions.md for
confirmation, including whether the Lead should be able to review.

### A change is validated like an edit, twice

The requested fields are merged onto the session's current details and
run through `validate_event_payload(for_submission=True)` -- the same rules
as creating or editing, so a change can't produce an event that couldn't
have been submitted. Only fields whose value actually differs are
recorded (plus knock-on changes validation makes, e.g. turning
registration off clears its window), with a `previous_values` snapshot so
the coordinator reviews a before/after.

Approval re-validates against the session as it is THEN: the coordinator
may have edited it, or a requested date may have passed. A change that no
longer validates is refused and stays pending for the coordinator to
reject.

### One pending change per session; decisions are conditional writes

A partial unique index allows one `pending` row per session, so two
changes can't each be reviewed against details the other is about to
alter. Approve/reject claim the row with `UPDATE ... WHERE status =
'pending'` (the transitions.py pattern), and the event is written only
after the claim succeeds, so a double click or a reject racing an approve
can never apply a change that was rejected. Claim and event write are two
PostgREST calls, not one transaction -- the same documented trade-off as
the status history row.

### Shared details apply to every session

Name, description and purpose are shared by every session of a request, so
an approved change to one of them is written to all the organiser's
sessions with that `shared_event_id`. Every other field is per session.

### Significant changes are gated on acknowledging their impact, not blocked

Before approval the coordinator sees which arrangements a change disturbs
(`app/events/change_impact.py`), and the approve call must name every
affected area in `acknowledge_impacts`, or it is refused with 409. Areas,
not a plain `true`: the check is re-run at approval, so an impact that
appeared after the page loaded (a new registration, a booking just
confirmed) is refused rather than waved through. The accepted impacts are
saved in `event_change_requests.acknowledged_impacts` for the audit trail.

It warns rather than blocks because a requirement change is often exactly
why arrangements must be redone -- refusing it would push the organiser to
cancel and re-create the event. It also deliberately writes nothing to
bookings or registrations; following up is the coordinator's call.
"conflict" means checked against real rows; "check" means the area has no
records yet (equipment, technical support), so the coordinator confirms by
hand.

### Change requests and event logs are two tables

`event_change_requests` is what the organiser ASKED for, plus the
coordinator's review: linked to the request (`shared_event_id`) and the
session that needs to change (`event_id`). `event_logs` is the audit trail
of what actually CHANGED: `event_log_id`, `shared_event_id`, `changes`
(`{field: {from, to}}`), `changed_by` and `changed_at` -- linked to the
request only, not to a session or a change request (the team's live
schema). One entry per change: approving a shared detail writes every
session but is logged once. Entries come in two kinds, told apart by who
made them, since the live table has no kind column:

- **requested**, by the request's organiser, who can only ask: submitting
  a change request, or fixing a rejected session before resubmitting it.
- **changed**, by the coordinator, whose edits take effect: a direct edit,
  or approving a change request (`changed_by` is the coordinator).

The history therefore reads "Change requested by <organiser>", then (if
approved) "Changed by <coordinator>". Someone who is both the organiser
and the assigned coordinator of the same event counts as changed. Drafts
aren't logged, and status changes stay in `event_status_log`. The log is
insert-only (RLS), and the event page shows it as "Change History" with
each person's name (`profiles` through `changed_by`).

The live tables were adjusted in the dashboard after the first draft of
the migration; `20261009000000_event_change_requests_and_logs.sql` was
rewritten to match them (live is the source of truth, as in
§"Live schema was the source of truth when reconciling migrations"),
plus two agreed fixes it also applies to live: `event_logs.change_request_id`
renamed to `event_log_id` (it is the entry's own id, not a link), and
`event_change_requests.reviewed_at` restored (so a rejection records when
it was decided).


## View Reserved Equipment (Justin, Sprint 3, 2026-10-14)

### Equipment Booking section on the coordinator's event page

`GET /events/<id>/equipment-requests` (gated on `event.view`, same split as
`GET /events/<id>/venue-bookings`: one event's own history, not the
cross-event queue) returns every equipment request for the session,
newest first. `components/EquipmentBookingStatus.vue` shows it below Venue
Booking, in the assigned coordinator's view only: a table of what was
requested, the total quantity, when it is needed and its status, then --
for confirmed requests -- the allocated units grouped by equipment type
(A-Z), each with its asset tags.

### Conventions this relies on from "Accept an equipment request"

That story (not yet built) is what writes `equipment_reservations`. This
section assumes, as `seed_equipment_demo` and the IS-18 availability check
already do:

- one reservation row per physical unit (reserving 3 projectors = 3 rows);
  the quantity shown is the number of rows held, not the number asked for;
- the request's `status` becomes `confirmed` when its reservation rows are
  written, and only confirmed requests' units are shown;
- `reserved_start`/`reserved_end` are the request's `needed_start`/`needed_end`.

### "Released" is derived, not stored

A confirmed request on a cancelled event shows as **Released** and lists no
units. `equipment_requests.status` has no `released` value and none was
added: the event's own `cancelled` status already says it, and releasing
the units themselves (deleting the reservation rows) is the separate
"release equipment on cancel" story.

## Release Equipment on Cancel (Justin, Sprint 3, 2026-10-14)

### Release = delete the event's reservation rows

`app/equipment/reservation_release.py::release_event_equipment` deletes
every `equipment_reservations` row belonging to the event's requests. The
`equipment_requests` and `equipment_request_items` rows are kept, so the
event page still shows what was asked for (as "Released").

Deleting, rather than keeping the rows with a `released_at` flag, because
everything that decides whether a unit is free already counts reservation
rows and nothing else: IS-18's `check_availability`, `get_equipment`'s
occupancy, and the `equipment_reservations_no_unit_overlap` exclusion
constraint. Once the rows are gone all three see the units as free, with
no change to IS-18's code or the migration. A flag would have needed a
migration, changes to both IS-18 functions, and a partial exclusion
constraint. What is lost is a record of exactly which units were held
before the cancel; the cancellation itself (who, when, why) is still in
`event_status_log`.

### Done in the cancel route, after transition()

`POST /events/<id>/cancel` calls `release_event_equipment` right after
`transition(..., "cancelled")` succeeds, so a cancel that is refused (no
reason, wrong status) or loses a race (409) releases nothing. It is not
atomic with the status change -- the same trade-off `transition()` already
makes for its history insert (see that module's docstring). A database
trigger would have been atomic and caught every path to `cancelled`, but
cancel has one path today and the team writes this logic in Python; see
`docs/open-questions.md`.

The release lives in its own module, not `equipment_service.py`, so IS-18's
file is not changed by this story.

## Reassignment is Lead-only (Justin, Sprint 3, 2026-10-14)

Source: Week 9 clarification (Sreya) — "Is the reassignment of coordinators
now handled by Event Coordinator Lead role instead of offline agreement by
coordinators?" — "yes, it is now manually assigned by the lead and no more
system auto-assignment of co-ordinator". Week 9 (Shanise) also confirms the
Lead may reassign after venue and technical arrangements are confirmed.

- **`rule_event_reassign_coordinator` is Lead-only.** Same relationship-first
  shape as `rule_event_assign_coordinator`: the event's coordinator and
  organiser can see the event, so they get 403; anyone else 404. The status
  precondition is unchanged (has a coordinator, not `completed`).
- **`coordinator.list` is Lead-only.** It existed for the coordinator's
  Reassign dropdown; nothing a coordinator does now needs other
  coordinators' names and emails.
- **The route always passes `requested_by=None`** to
  `coordinator_service.reassign_coordinator`, whose "must be the current
  coordinator" check was the Week 4 hand-over rule. The check is left in
  the service (unused by the app) rather than deleted, so its integration
  test still documents it.
- **Removed from the frontend:** the Reassign panel on the coordinator's
  review page, and the coordinator-only `/events/reassign` page (an early
  raw-ID form) with its route and `ROUTE_ACCESS` nav entry. The Lead
  reassigns from the Lead dashboard, which already did.
- This supersedes the Sprint 1 story "Coordinator needs reassignment" —
  recorded in `traceability.md` rather than silently dropped.

## Update Event Information During Planning (IS-9, Sprint 3, 2026-10-15)

### One write path for the coordinator's update: `app/events/event_update.py`

`POST /events/<id>` (event.edit) now goes through `update_event`, which
replaces `event_service.edit_event_request`. In order: validate, work out
what actually changes, assess the impact, check it was acknowledged, write
(conditional on the status @require authorised), log, copy shared details
to the other sessions, revert a confirmed event to planning. A no-op save
writes and logs nothing.

`POST /events/<id>/update-preview` runs the same steps up to the impact and
writes nothing. The page calls it on Save, so the coordinator reviews a
significant or impactful change before committing it, and the save itself
re-checks -- an impact that appeared in between (a new registration, a
booking just confirmed) is a 409 `change_impact_unacknowledged`, the same
gate IS-21 approvals use (`change_impact.check_acknowledged`, moved there
so both paths share it).

### Validation is of the whole session, not the payload

The update is merged onto the session's stored details and validated as a
complete request (`for_submission=True` once it has been submitted), so a
partial update is checked against the fields it didn't send -- an end time
before the stored start time is refused. The old edit path validated only
the payload, so it could store a combination that would never have passed
submission. Validation runs before any write, so a refused update leaves
the event exactly as it was.

### Significant vs ordinary

Significant fields (`event_log.SIGNIFICANT_FIELDS`): the four date/time
fields, `expected_attendance`, `room_layout` (venue requirements) and
`equipment`. Everything else is ordinary. Accessibility needs are listed in
the story as their own field, separate from venue requirements, so they
are ordinary -- but the impact check still runs on them (and on every other
field), so an accessibility change a booked venue can't meet is still shown
and must be acknowledged. Stored in `event_logs.significance` on every new
entry, including the organiser's "requested" entries; entries written
before the column existed are classified from their `changes` on read.

### A change to a confirmed event sends it back to planning

New edge `confirmed -> planning` in `transitions.ALLOWED`, taken only by
`event_update.revert_to_planning` -- there is no button for it. It runs
after any change that actually alters a confirmed session: the coordinator's
update, an approved IS-21 change request, and a shared detail (name,
description, purpose) copied onto a confirmed sibling session. The reason
in `event_status_log` names the fields that changed.

### Shared details reach every open session

Name, description and purpose are shared by a request's sessions. The old
direct edit changed only the session it was made on, so sessions of one
request could disagree about their own name. The coordinator's update now
copies them to the other sessions, as an approved change request already
did -- except completed or cancelled ones, which are read-only. An
organiser fixing a rejected session still changes only that session.

### Refusals say why

`policy.authorise` can attach a reason to a 403 (`_DENIAL_REASONS`); for
event.edit it's `rules.explain_event_edit_denial`: the event is completed or
cancelled, or only the assigned coordinator can update it. The Lead, who
can view every submitted request, now gets that 403 instead of a 404.

### Impacts are checked only from planning on

The coordinator's update is checked against arrangements only while the
event is in planning or confirmed (`event_update.IMPACT_CHECKED_STATUSES`).
Under review or approved, the details are still being settled, so the
coordinator edits freely: nothing to acknowledge and no review step on the
page (the preview says `impacts_checked: false`). Significance is still
recorded either way. Trade-off: a venue booking can already exist while the
event is approved (`rule_venue_booking_create`), and an edit then is not
flagged against it. IS-21 change requests keep the wider
`change_impact.ARRANGED_STATUSES` (from approval on).

### Equipment impacts read the equipment requests

Since `equipment_requests` exists (IS-18), a timing or equipment change on a
session with a pending or confirmed request is a "conflict" naming the
request's period. Without a request it stays a "check manually", as before.
Technical support is still "check manually" -- there are no assignment
records yet.

### AC3 completed: every arrangement a change touches, conflict or not (2026-10-19)

The preview only listed an arrangement when the change broke it (`impacts`),
so a significant change that touched a venue booking, an equipment request
or registrations without breaking them read "nothing is affected". The AC
asks for "which already-made arrangements it touches", so the preview now
also returns `arrangements` (`change_impact.touched_arrangements`): every
pending/confirmed venue booking, pending/confirmed equipment request and the
session's registrations that depend on a changed field --

  venue         timing, expected attendance, room layout, accessibility needs
  equipment     timing, equipment
  registration  timing, registration window/needed, expected attendance

The page lists them under "Arrangements this change touches", each marked
"Still fits" or "Conflict". Only conflicts (`impacts`) still need the
acknowledgement tick: requiring it for an arrangement the change doesn't
break would make the coordinator confirm nothing. Same status window as the
impact check (`IMPACT_CHECKED_STATUSES`, planning on); rejected and
cancelled arrangements hold nothing, so they aren't listed.

### AC9 completed: cancelling one venue booking (2026-10-19)

AC9 ("changes or cancellation of one venue arrangement should not
automatically remove the other venue bookings") had no cancel to test --
no booking could be cancelled. Added:

- A `cancelled` booking status (`20261019300000_venue_booking_cancel.sql`),
  not a delete: the booking stays in the session's history. The IS-16
  no-overlap constraint covers `confirmed` rows only, so a cancelled booking
  frees the venue at once; the calendar, conflict and safety checks already
  filter on pending/confirmed.
- `POST /venues/bookings/<id>/cancel` -> `booking_service.cancel_booking`:
  one `UPDATE ... WHERE id = <booking> AND status = <the status authz saw>`,
  so only that row changes and a cancel racing a Venue Staff decision is
  refused, not overwritten (same race-proofing as `_decide_booking`). A
  reason is required; who/when/why go to `venue_booking_status_log`, like
  approve/reject, and the coordinator reads it back as `cancellation`.
- `venue_booking.cancel` (`rule_venue_booking_cancel`): the event's
  **current** assigned coordinator -- not the booking's requester, who may
  have been reassigned away by the Lead -- for a pending/confirmed booking,
  until the event is completed or cancelled (the coordinator's edit
  window). Anyone else 404; a closed booking or event 403 with the reason.
  The loader attaches the event's coordinator_id/status to the booking.
- The event's status is not changed by a cancel (see open-questions.md).
  *Superseded 2026-10-26 -- see below.*
- The page lists every booking of the session with its own Cancel, and
  offers "Request a venue" only while no booking is pending or confirmed
  (frontend only; see open-questions.md).

### Cancelling a booking of a confirmed event reverts it to planning (2026-10-26)

Answers the open question above: a confirmed event whose venue booking is
cancelled goes back to planning, the same as a change to its details
(AC10) -- its venue arrangements changed after confirmation, so it has to
be re-checked (safety review) before it can be confirmed again.

- `booking_service.cancel_booking` cancels the booking first, then
  (`_revert_confirmed_event`) takes the existing `confirmed -> planning`
  edge through `transitions.transition` -- no new edge. The status history
  row is attributed to the coordinator, with the reason "Venue booking
  cancelled after confirmation: <cancel reason>".
- Any cancelled booking counts, pending or confirmed. Events in any other
  status (planning, safety_review, ...) are left as they are; only
  "confirmed" is reverted.
- The transition is conditioned on the event status the route's loader
  (`load_booking_with_event`) authorised against (`expected_from`). If the
  event moved on in between, `TransitionConflictError` is swallowed: there
  is nothing to revert, and the booking cancel -- already written -- still
  stands rather than reporting a 409 for a change that did happen. Like
  every transition, the booking write and the status write are separate
  requests, not one transaction.
- The response carries `event_reverted_to_planning`. `VenueBookingStatus.vue`
  warns in the cancel form when the event is confirmed, and after a revert
  re-fetches the event and emits `updated`, so `EventDetailsView.vue`
  shows the new status.

### Equipment impacts: identical requests reported once (2026-10-19)

The equipment impact wrote its sentences once per request, and they don't
name the request, so two pending requests for the same window produced the
same lines twice. Requests with the same status (and, for timing, the same
window) are now grouped: one sentence each, saying how many it covers ("The
2 pending equipment requests cover ...").

### Venue Staff read a booking's event details through the booking (2026-10-19)

The booking review page fetched `GET /events/<id>`, which `rule_event_view`
refuses to Venue Staff (404), so the page failed for the very role that
decides on bookings -- since IS-14. Rather than widen event.view to Venue
Staff (who would then see every field of every event), `get_booking` embeds
just the session details the review shows and checks suitability against
(`booking_service.BOOKING_EVENT_FIELDS`), as `event` -- the same "only what
the entry needs" embed the venue calendar uses. The page no longer calls
`/events/<id>`.

### Change History names the session; paged (2026-10-19)

`event_logs` was keyed by the request only, so a multi-session request's
history couldn't say which session changed. `event_logs.event_id`
(`20261019400000_event_logs_session.sql`, nullable, ON DELETE SET NULL so the
audit trail outlives a deleted session) is written by all three log writers.
Entries from before the column are backfilled only where the request has a
single session -- the only case that is unambiguous.

`list_event_logs` adds `session`: "Session N" numbered in the order the
session list shows (`_session_sort_key`), within the organiser's own request
(same scope as `apply_shared_details`); "All sessions" for an applied change
to shared details only (name/description/purpose), which reaches every
session; none for a single-session request or an older unlabelled entry. A
request is still about the session it was made for.

Pagination is client-side, 5 per page, newest first, back to page 1 on
reload: a request's history is small and already loaded in one call, so
server paging would add an API shape change for no gain.

## Shared calendar module (refactor, 2026-10-16)

Owner sign-off: Nawaz owns `backend/app/venues/calendar_service.py` and
`frontend/src/views/venues/VenueCalendarView.vue` (IS-11) and gave explicit
sign-off for this refactor (relayed by Terry, 2026-10-16). Not IS-47: it
only moves the venue calendar's domain-neutral parts somewhere the equipment
calendar can reuse them. The IS-11 tests (`test_calendar_service.py`,
`test_venue_calendar_routes.py`, `test_authz_venue_calendar.py`) were the
specification and pass unchanged.

### What was extracted

- **Backend, `backend/app/shared/calendar.py`.** `app/shared/` already held
  the cross-domain error types, so the module sits next to them rather than
  in a new `app/common/` package.
  - `parse_calendar_range(start, end)`: YYYY-MM-DD parsing, the 400 on a
    malformed date or an end before the start (same messages), and the
    whole-day widening, `time.min` on the start day to `time.max` on the end
    day, so `end` is an inclusive day.
  - `spans_overlap(a_start, a_end, b_start, b_end)`: half-open overlap.
  - `CalendarRange.overlaps(entry_start, entry_end)`: the calendar's own
    use of it. It drops the entry's UTC offset and compares wall-clock time
    with the naive range, exactly as the inline check in
    `get_venue_calendar` did.
  - `calendar_envelope(resource_key, resource, range, entries)`: the
    `{<resource_key>: {...}, range: {start, end}, entries: [...]}` shape.
    The key is a parameter, because the venue response's key is `venue`
    and the tests assert it.
- **Frontend.** `frontend/src/lib/calendar.js` holds the date math (range
  per view, the range label, stepping, the backend query with its
  inclusive end day, month cells, list ordering) plus a `useCalendarRange`
  composable. `frontend/src/components/AvailabilityCalendar.vue` is the
  month grid, day/week list and legend. The caller passes the entries, the
  view and range, a state -> `{label, color, background}` map, and an
  `entryLabel(entry)` function.

### What deliberately was not

- **Each domain's queries and states.** `calendar_service` keeps its
  `venue_blocks` / `venue_bookings` queries, the confirmed vs
  tentatively_held mapping, the entry sort, and its own
  `_parse_timestamptz`.
- **The view's header.** Title, view tabs, prev/next/today and the
  operating-hours note stay in `VenueCalendarView.vue`, driven by
  `useCalendarRange`. The component is only what renders entries.
- **The equipment helpers.** `equipment_service._parse_timestamptz` and
  `_spans_overlap` stay where they are (next section).
- **The colours.** The calendar keeps its own three state colours, now
  passed in by the view instead of set in CSS. The ticket asked for IS-9's
  status palette, but that palette is the event-status set (`.status-draft`
  ... `.status-rejected`, from `styles/event-form.css` and copied into the
  two dashboards and `CoordinatorEventReview` by IS-9). None of its colours
  match the calendar's, and the rendering had to stay identical, so Terry
  chose identical rendering. The palette question is in
  docs/open-questions.md.

### Equipment helpers compared: not unified

The two pairs differ, so both stay:

| | venue calendar | `equipment_service` |
|---|---|---|
| timestamp parsing | `"Z"` -> `+00:00`; a value with no offset stays naive | same, but a value with no offset is read as UTC |
| overlap | offsets dropped; wall-clock time compared with a naive day range | aware datetimes compared as instants |
| boundary | strict `<` both sides (half-open) | strict `<` both sides (half-open) |

The boundary rule is the same, but timezone and null-offset handling are
not. Folding equipment onto the calendar's version would change which
reservations count as overlapping a request that crosses an offset. The
bare predicate `a_start < b_end and b_start < a_end` is textually the same
in both (and in `booking_service._spans_overlap`). Merging only that line
is left for IS-47 to decide once it knows how its calendar should treat
offsets.

### Verified identical

- **Backend.** The full suite passes apart from one integration test that
  fails identically on unmodified `origin/main` (unrelated:
  `test_event_change_requests_integration.py`, IS-9's confirmed -> planning
  revert).
- **Frontend.** The venue calendar's rendered HTML was captured before and
  after the change in month, week and day views, after next/previous, and
  after Today, all with entries in every state. It is identical once
  scoped-style hashes and the new inline colour styles are ignored, and
  those inline colours equal the old CSS values.

### Coverage is not a test of the boundary

`spans_overlap` in `app/shared/calendar.py` reached 100% line and branch
coverage from the IS-11 venue calendar tests alone. In a hand mutation
test, each of its two `<` comparisons was changed to `<=`, one mutant at a
time. All 20 IS-11 tests passed against both mutants, so the IS-11 suite
killed 0 of 2. Only the new `test_shared_calendar.py`, which has entries
ending exactly on a range edge, caught them. Coverage showed that every
line ran, not that any test would notice the half-open boundary changing.
This is why the team treats a hand mutation test as a Definition of Done
item rather than relying on a coverage number. The gap in the IS-11 tests
themselves is in docs/open-questions.md.

## View Equipment Availability Calendar (IS-47, Sprint 3, 2026-10-16)

Built on the shared calendar pieces from PR #32. Backend:
`app/equipment/calendar_service.py` and `GET /equipment/<id>/calendar`.
Frontend: `EquipmentCalendarView.vue` on `AvailabilityCalendar` and
`lib/calendar.js`. No schema change. Built to the ticket's own
requirements, then checked against `docs/definition-of-done.md` (added in
the same PR) before it was committed.

### Not editing IS-18's files

`app/equipment/routes.py` and `EquipmentDetailView.vue` are Nawaz's (IS-18).
The DoD asks for the owner's sign-off before a change to them lands, so:

- **The route has its own blueprint**, `app/equipment/calendar_routes.py`,
  rather than being added to `routes.py`. This is the same pattern IS-16
  used (`app/venues/conflict_routes.py`) to avoid editing IS-14's file.
- **The "View reservation calendar" link** on `EquipmentDetailView.vue` is
  the one change to an IS-18 file. It is a separate commit marked
  `[PENDING NAWAZ'S SIGN-OFF]`, the model the DoD names, so it can be
  dropped if he says no. Without it the calendar works but is reached by
  URL only.

### Who can see it, and why everyone else gets a 404

`equipment.calendar_view` is Technical Support Staff only. That is the same
role as `equipment.list` / `equipment.view`, not the venue calendar's
coordinator + venue staff pair. Every other role gets `DENY_NOT_FOUND`, a
404, where `equipment.view` gives a 403:

- **Why 404.** AC6 asks that anyone else get "the same response an unknown
  unit would give". The calendar also names every event the unit is
  reserved for and when. Per docs/authz-usage.md, a caller with no
  relationship to the resource is not told it exists.
- **Identical body, not just status.** The route's loader (`load_unit`)
  re-raises a missing unit as `NotFoundError("Resource not found.")`, the
  message `authorise()` uses. A hidden unit and an unknown one therefore
  get byte-identical responses, and a route test compares the two.
- **Coordinators.** Whether they should also see equipment calendars is
  open for Justin (docs/open-questions.md); saying yes is one more
  `_has_role` line in the rule.

### Two overlap tests in the equipment package

- **The calendar** (`calendar_service.py`) filters with
  `app.shared.calendar.CalendarRange.overlaps`, the venue calendar's test.
  It drops each timestamp's offset and compares wall-clock time with whole
  days.
- **The availability check** (`equipment_service.check_availability`)
  keeps its own `_spans_overlap` over timezone-aware instants, with
  `_parse_timestamptz` reading an offset-less value as UTC. It compares two
  booked periods, and comparing instants is right for that.

PR #32 kept these apart because their semantics differ. The calendar uses
the shared one, so the two calendars agree with each other. Both are
half-open with strict `<`.

### Data and range

- **One query.** `@require`'s loader fetches the unit once with
  `equipment_service.get_equipment`, which already joins each reservation
  through its request item and request to the event's name. The loaded
  unit is passed to the calendar service, which filters its occupancy. There
  is no second query and no second round trip.
- **The page asks for a day more than the month on each side**
  (`widenRange`). The shared `rangeQuery` sends UTC dates, and the backend
  compares stored UTC times against whole days. Asking for exactly the
  month in Singapore misses the month's last day after 08:00, and fixing
  only the dates would instead miss the first day before 08:00. The extra
  day each side covers both, and `monthCells` places entries by local day
  and draws only this month's days. The venue calendar has the same defect
  and does not use this yet (docs/open-questions.md).
- **Multi-day reservations** are marked on every day they cover through a
  `spanDays` option on the shared `monthCells`. It is off by default, so the
  venue calendar renders exactly as before (re-checked against PR #32's
  characterisation capture). The end is exclusive: a reservation ending at
  midnight does not mark the next day.

### What the calendar shows vs what the wireframe draws

| Wireframe | Built |
|---|---|
| Title: asset tag; subtitle: type; status pill | Yes. The pill reuses the inventory's labels (`unitStatusLabel`: "In service", "Under maintenance", "Retired") and colours, rather than the wireframe's "Operational / Maintenance / Retired", so one status reads the same on every equipment page |
| Equipment Profile: asset tag, type, notes, location | Asset tag, type, notes. **No location**: `equipment_units` has no such column |
| Reservation Calendar: month grid, previous/next | Yes, plus a "Today" button as on the venue calendar |
| Reserved days marked with the event's name | Yes, every day the reservation covers; "Reserved" when the event has no name |
| Pending state | Not built: a pending request names a type and a quantity, not a unit |
| Under-maintenance periods | Not built: no dated maintenance data. The current status is the pill |
| Back link to the equipment list | Yes. The unit's detail page also links to the calendar |

## Safety review status (Week 7 #6, Justin, 2026-10-18)

**One new status, `safety_review`, between `planning` and `confirmed`.**
Week 7 #6: "After the venue and technical arrangements have been
confirmed, the Safety Officer must conduct an Operational Safety Check
before the event can proceed to preparation." Week 4 already said every
arrangement must be approved before confirmation; the safety check is one
more arrangement, so it sits just before `confirmed`.

**Edges, each sourced in `transitions._EDGE_SOURCES`:**

- `planning -> safety_review`: arrangements approved, sent for the check.
- `safety_review -> confirmed`: approved. Week 9: the Safety Officer
  records the decision with a comment and "the co-ordinator will decide on
  the subsequent action", so the coordinator confirms.
- `safety_review -> planning`: rejected or changes requested. Week 9: "if
  the safety approval failed, then it will send the event back to planning
  phase."
- `safety_review -> cancelled`: same "cancel after approval" rule as the
  other pre-completion statuses.

**`planning -> confirmed` was kept for now** (removing it before the Safety
Officer actions existed would have left no way to confirm an event).
*Superseded 2026-10-19: the Safety Officer story removed it -- see "Safety
Officer" below.*

**No `preparation` status.** Registration requires `confirmed`, and
attendees need lead time; setup happens just before the event. A
`preparation` status before `confirmed` would keep registration closed
until setup was done. Preparation is what staff do while the event is
confirmed (Week 2, "prior to and during event delivery").

**AC2 of the status story says "event session", not "event request".**
Each session of a multi-session request is its own `events` row with its
own status: a coordinator can approve one session and reject another, and
Week 9 gives each session its own venue request. One request can
therefore show several statuses at once ("2 approved, 1 rejected"), which
is intended.

**Where it's shown:** `statusLabel` already turns `safety_review` into
"Safety Review", so only the status palettes got a new
`.status-safety_review` colour. The coordinator dashboard files it under
In Planning (still before confirmation), and both "active" lists
(`coordinator_service.ACTIVE_STATUSES`, `leadDashboard.ACTIVE_STATUSES`)
include it: a coordinator with an event in safety review is still busy on
that date, and the Lead still sees it as active.

## Safety Officer (Week 7 #6, Justin, 2026-10-19)

**The flow, per event session.** The coordinator submits a planning session
for its safety check (planning -> safety_review, a pending
`safety_reviews` row). Any Safety Officer approves, rejects or requests
changes. Reject / request changes send the session back to planning with
the comment as the status-history reason; the coordinator fixes it and
submits again, which is a new row (Week 4: resubmissions are new, for
audit). Approve leaves it in safety_review, and the coordinator confirms it
(safety_review -> confirmed), which the confirm route allows only when the
latest review is approved. `planning -> confirmed` is gone from
`transitions.ALLOWED`, so nothing skips the check.

**A table of reviews, not fields on the event.** One row per submission
keeps every decision and comment (the officer's "Checked" tab, the
coordinator's history, audit), and copies the venue-booking pattern the
team already knows: request -> pending -> decided, with who/when/why. The
event row's status is still only ever written by `transitions.transition()`.

**Per session.** Everything checked is per session: its venue (Week 9:
"separate venue requests for each session"), capacity, layout, equipment
and status. The dashboard groups sessions into request cards, as the
coordinator dashboard does, so the officer still sees each request together.

**Race guards.** A partial unique index allows one *pending* review per
session, so two submits can't both create one (the service turns the
23505 into "already waiting"). A decision updates the review only while
it's still pending, so two decisions can't both land. If a submit's status
change fails after the review is written, the review is deleted again. If
a decision's status change finds the session already moved on (cancelled),
the decision still stands. A pending review of a session that left
safety_review is hidden from the dashboard and can't be decided. All four
guards were mutation-tested by hand.

**Authorisation.** Six actions: `safety_review.submit` (assigned
coordinator, from planning), `.list` (role-only, Safety Officer, with the
service re-checking the role), `.view` (any Safety Officer; anyone else
404), and `.approve` / `.reject` / `.request_changes` (any Safety Officer,
review still pending; anyone else 404). The coordinator reads a session's
reviews through `GET /events/<id>/safety-reviews`, gated by `event.view`,
so they need no access to the officer's view. Whether arrangements are
ready, and whether the latest review is approved, are database facts, so
they're checked in `app.safety` rather than in the pure rules.

**What the officer sees.** `GET /safety-reviews/<id>` returns the session,
its confirmed venue booking(s) with the venue record, its equipment
requests and its earlier reviews. The page reuses `checkSuitability`
(capacity, layout, accessibility) from the Venue Staff booking review.
Emergency access, equipment placement, crowd movement and venue
restrictions aren't recorded, so they're listed as the officer's own checks.

**safety_review joins the status windows.** Cancel, change requests, and
the IS-9 / IS-21 impact checks now include it: it sits between planning and
confirmed, with arrangements already made.


## Venue Categories (IS-60, Sprint 3, 2026-10-23)

Story: "As a Venue staff, I want to record what type of venues are available
so that I can properly categorize the venues." Most of what it asks for was
already on `main` as the room layouts feature (`room_layouts` table,
`/room-layouts` routes, `RoomLayoutsView.vue`). IS-60 adds the acceptance
tests (`test_ac1_*` ... `test_ac5_*` in `test_room_layouts.py` and
`test_room_layouts_integration.py`) and one migration,
`20261023000000_rejected_sessions_release_room_layouts.sql`, for how
rejected sessions are treated. The calls below are flagged in
docs/open-questions.md.

### Venue categories are the room layouts

The story doesn't define a category. Room layouts (theatre, classroom,
banquet, ...) are already the list of venue types that Venue Staff maintain:

- venues list the layouts they support;
- event requests pick one;
- Venue Staff add, rename and delete them.

The story's five criteria (create, edit, disable, delete only once disabled,
delete only once no ongoing event uses it) match that feature's lifecycle
one for one. A separate `venue_categories` table would be a second list of
the same thing, which Venue Staff would have to keep in step. So IS-60 is
met by room layouts, with no new table. The UI still says "Room Layouts".

### "Disabling" is the soft delete, and it can be undone

AC3's "disabling" and AC4's "disabled first" are the soft delete:
`is_active = false`, through `DELETE /room-layouts/<id>`. A disabled layout:

- is no longer offered on event forms;
- can't be chosen for a new or changed session;
- is still listed for Venue Staff, under "Deleted";
- can be restored (`POST /room-layouts/<id>/restore`).

The story doesn't mention restoring. It's kept because disabling is
otherwise a one-way step taken while events still depend on the layout.

### "Ongoing" means not completed, cancelled or rejected

AC5 defines ongoing events as those "not completed or cancelled". Read
literally, a rejected event counts as ongoing. A rejected session no
organiser ever resubmits would then block the permanent delete indefinitely.

A rejected session is back with its organiser to fix and resubmit, the same
position as a draft, so it isn't ongoing either. Permanent delete is refused
only while an event that is not completed, cancelled or rejected uses the
layout. Drafts never hold one up: disabling clears the layout from them (next
section). This departs from the AC's literal wording, so it's the first item
under IS-60 in open-questions.md.

### Drafts and rejected sessions lose a disabled layout; other events keep it

AC3 lets a category be disabled while ongoing events use it. Those events
(submitted through confirmed) keep their layout: their request was made, and
is being planned, with it. A session still being written or fixed is
different. Submitting needs an active layout, so the organiser would be
refused at submit time anyway. The database clears the layout from them
straight away:

1. **When the layout is disabled:** every draft and rejected session using it
   (`room_layout_soft_deleted`).
2. **When a session is rejected while its layout is disabled:** that session
   (`events_release_disabled_layout_on_reject`). Without this, a session under
   review when the layout was disabled would come back to its organiser still
   holding it.
3. **When the layout is permanently deleted:** any rejected session still
   holding it, e.g. one written straight to the table
   (`before_room_layout_delete`).

Restoring the layout doesn't put it back on those sessions: by then the
organiser may already have picked another.

### Telling the organiser why the layout is empty

`events.room_layout_removed` keeps the name of a layout cleared in any of
the three cases above:

- **What the organiser sees:** while the session has no layout, the form
  (`EventSessionFields.vue`, via `lib/roomLayouts.js::removedLayoutNotice`)
  shows: *The room layout "X" is no longer available, so it has been removed
  from this session. Please choose a new room layout.*
- **When it's cleared:** as soon as a layout is set again
  (`events_unflag_removed_room_layout`). Other edits leave it.
- **Never sent from the form:** `sessionPayload` leaves it out, so the
  database is the only thing that sets it.
- **Not part of the event details:** it isn't one of the fields
  `_from_database_event` returns, so it never appears in a change diff.

### Not recorded in event_logs

Clearing a layout from a draft or rejected session isn't logged. It's the
database reacting to Venue Staff's change, and no user is editing the event;
`event_logs.changed_by` expects one. The draft clearing that this extends was
never logged either. Rejected sessions are submitted events, so this is an
exception to "every change to a submitted event is logged", and is flagged.

### Completed and cancelled events keep the name

Permanently deleting a layout leaves its name on completed and cancelled
events (`events.room_layout`); only `room_layout_id` becomes null (ON DELETE
SET NULL). Their record of what was requested stays intact. This is
unchanged from the room layouts migration.

### Names are unique regardless of case

"Theatre" can't be added beside "theatre"; the index is on `lower(name)`.
A clash with a disabled layout says to restore it instead, because Venue
Staff can't otherwise tell why the name is taken.

### Who can manage them, and why others get 403, not 404

`room_layout.manage` is Venue Staff only. Every other role gets
`DENY_FORBIDDEN` (403), not a 404:

- Layouts are shared reference data with no owner: their names are on every
  venue's supported layouts and in every event form.
- A 403 hides nothing that a 404 would. docs/authz-usage.md's case for a 404
  (not revealing that a resource exists) doesn't apply.
- `room_layout.list` gives the same 403 to roles that never work with
  layouts (attendee, safety officer).

## CRUD in Venue Catalogue (IS-61, Sprint 3, 2026-10-23)

Story: "As a Venue staff, I want to add, edit and delete venues so that I can
easily manage what venues ConnectSphere currently has." Built on the existing
`public.venues` table: `POST /venues` (add), `POST /venues/<id>` (edit),
`DELETE /venues/<id>` (delete), in `app/venues/venue_service.py`, plus
migration `20261023100000_venue_catalogue_crud.sql`. Frontend:
`VenueFormView.vue` (add/edit), the staff actions on `VenueDetailView.vue`,
and `VenueRemovedAlert.vue` on the coordinator's event page. The calls below
are flagged in docs/open-questions.md.

### Deleting is a soft delete

`venues.deleted_at` / `deleted_by`, not a `DELETE`:

- `venue_bookings.venue_id` references the venue with no `ON DELETE`, so a
  real delete is refused while any booking, even a finished event's, points
  at it. Cascading instead would erase where completed events were held.
- The booking review page loads a booking's venue by id
  (`GET /venues/<id>`), which has to keep working for old bookings.

So a deleted venue leaves the catalogue (`GET /venues`), can't be edited
(409 `venue_deleted`) or booked, but `GET /venues/<id>` still returns it,
marked deleted. There is no restore: the story doesn't ask for one.

### Then a permanent delete

So a deleted venue isn't left as a stale row, Venue Staff can permanently
delete it: the catalogue's **Deleted** tab (`GET /venues/deleted`) lists
deleted venues, and the venue's page offers **Delete permanently**
(`DELETE /venues/<id>/permanent`, `venue.delete`). Same two-step shape as
IS-60's room layouts. Migration `20261023200000_venue_permanent_delete.sql`.

- **Past bookings keep the venue's name.** The booking's link to the venue
  becomes NULL (`ON DELETE SET NULL`) and trigger `before_venue_delete`
  copies the name into `venue_bookings.venue_name` first. Completed and
  cancelled events, above all, still say where they were held. Only the
  name is kept, not the venue's other details.
- **Readers show the kept name.** `booking_service.with_venue_names` fills
  the empty `venues(...)` embed from `venue_name` for the event's booking
  list, the Venue Staff queue and the safety review. The booking review page
  shows "Name (permanently deleted)" instead of loading the venue. The
  overlap and conflict checks treat a booking with no venue as clashing with
  nothing (they used to query `venue_id = None` and crash).
- **An event's room layout is unaffected:** it lives on the event
  (`events.room_layout`), not on the venue.
- **Two guards, split between the app and the database.** The app requires
  the venue to be deleted from the catalogue first. The database refuses
  removing a venue an ongoing event still has a live booking on, whoever
  runs the DELETE. "Deleted first" is deliberately not a database rule:
  other stories' integration tests remove their throwaway venues with a
  plain DELETE once their bookings are gone. Unlike a room layout, a venue
  nothing uses is safe to remove either way.
- **A booking can't become live without a venue.** A finished event's
  pending request left on a removed venue can't be approved (trigger
  `venue_bookings_refuse_deleted_venue`, extended).
- **`released_at`.** The coordinator's alert used a released booking's
  `updated_at` as its release time, but the SET NULL rewrites every booking
  of the venue, which would have moved it and could bring back an alert the
  coordinator had already dealt with. Released bookings now carry
  `released_at`, set by `delete_venue()` (existing ones backfilled from
  their release log entry), and the alert uses that.

### AC4: what "lose their booking" does

Deleting runs one database function, `delete_venue()`, so the soft delete and
the releases land together or not at all. Every **pending or confirmed**
booking of the venue whose event is **ongoing** (not completed, cancelled or
rejected -- the IS-60 reading) becomes `cancelled`, with
`released_by_venue_deletion = true` and a `venue_booking_status_log` row
(changed_by = the Venue Staff member, reason naming the venue). Bookings of
finished events are left as they were.

- **Pending bookings are released too.** A pending request for a venue that
  no longer exists can't be approved, and the coordinator needs to know.
- **Only that venue's bookings.** A session's bookings at other venues stay
  (IS-9: one arrangement's change doesn't remove the others).
- **A deleted venue can't be booked or approved against.** The backend says
  so first; trigger `trg_venue_bookings_refuse_deleted_venue` enforces it, so
  a request racing the delete is either released by it or refused.

### Confirmed sessions go back to planning

A session can't stay confirmed without the venue it was confirmed with, and a
coordinator can only book a venue in planning (`rule_venue_booking_create`).
So a released session that was **confirmed** moves `confirmed -> planning`,
the edge IS-9 already uses when a confirmed event's details change. It goes
through `transitions.transition()` (status is only written there), with the
reason in `event_status_log`, attributed to the Venue Staff member.

A session **under a safety check** (`safety_review`) goes back to planning
the same way (`safety_review -> planning`). Its pending safety review is
closed as `changes_requested`, with the reason as the comment
(`safety_service.withdraw_pending_review`). Left pending, the Safety Officer
couldn't decide it (the session is no longer in safety_review) and the
coordinator couldn't resubmit (one pending review per session).

Like every other status change that follows another write here, this step is
not in the same transaction as `delete_venue()`. A session that moved on in
between (e.g. was cancelled) is left alone.

### The coordinator's alert

`VenueRemovedAlert.vue`, at the top of the coordinator's event details page,
shows while the session has a booking released by a venue deletion that
hasn't been replaced (`lib/venueBookings.js::unreplacedVenueReleases`). It
names the venue and links to request another. "Replaced" means a pending or
confirmed booking made after the release (the released row's `updated_at`),
so it stays up if the session only has older bookings left, and goes once
the coordinator rebooks. The released booking stays listed under Venue
Booking, marked as released by the deletion. There is no email or push
notification: none exists anywhere in the app yet (`_notify_venue_deleted`
is the same no-op hook as the other `_notify_*` functions).

### Facilities and accessibility provisions are closed lists

The Sprint 1 migration left `facilities` / `accessibility_features` as open
`text[]`. Now that Venue Staff enter them, the backend only accepts the
values event sessions ask for (`event_service.EQUIPMENT` /
`ACCESSIBILITY_NEEDS`). Venue search and the suitability checks compare the
two lists value for value, so "Wheelchair Access" on a venue would never
match a session needing `wheelchair_access`. Adding a new facility is now a
code change rather than a data entry.

### Editing

- Only the fields sent change, but the merged record is re-checked, so an
  edit can never leave the venue invalid.
- A venue keeps a room layout it lists that has since been soft-deleted, but
  can't newly add one (same rule as event sessions).
- Changing setup/turnaround minutes doesn't touch existing bookings: each
  snapshotted them when made (`20261005100000_venue_bookings.sql`). New
  check constraint `venues_buffers_non_negative`.
- Lowering capacity, or removing a layout or provision, doesn't re-check
  existing bookings.
- The form has no status field. A new venue is added as `available`; an
  edit never sends the status, so a venue in maintenance stays that way.
  The API still accepts `status`.

### Required fields and minimums

A venue needs a name, a location, a capacity of at least 1, **at least one
supported room layout**, and setup and turnaround times of **at least 5
minutes** each. Both the form (`lib/venueCatalogue.js::validateVenueForm`)
and the backend (`venue_service._validated`, `MIN_BUFFER_MINUTES`) check
them, on add and on edit. An edit re-checks the whole venue, so an older
venue with no layouts must be given one before any change to it saves.

The 5-minute floor is not in the database: its constraint
(`venues_buffers_non_negative`) only refuses negatives. Other stories'
integration tests insert venues straight into the table with 0-minute
buffers (`test_venue_bookings_integration.py`), and raising the floor there
would need a new migration. Venues are only ever added or edited through
the backend, which enforces 5.

The form checks as Venue Staff go:

- **When an error appears:** once Venue Staff leave a field (blur). The
  room layout checkboxes count as one field, flagged when focus leaves the
  group rather than when it moves between boxes. After that, the message
  updates live and disappears as soon as the field is fixed.
- **Save:** disabled, with a short "Fill in every field marked *" hint,
  until every check passes.
- **Editing a venue that already breaks a rule:** its errors show
  immediately, so Save is never disabled without a visible reason.

### Operating hours are left out of add and edit

`venues.operating_hours_start/end` (added by IS-11) aren't in the venue form
or accepted by `POST /venues` / `POST /venues/<id>`. Nothing relies on them:
bookings, conflict checks and suitability checks ignore them, and the venue
calendar only shows them as a note. So a venue added here has no set hours
(both NULL), and an edit leaves a venue's existing hours (the seed data's)
as they are. The venue page still shows them read-only. If a later story
needs Venue Staff to set them, add the two fields back with their own rules,
including whether a venue may close after midnight.

### Who can do it

`venue.create` / `venue.edit` / `venue.delete`, Venue Staff only, 403 for
everyone else (venues are shared inventory every coordinator can list, so
there's nothing to hide with a 404). Edit is `POST /venues/<id>`, not PATCH,
matching `POST /room-layouts/<id>`.

## Notification System (IS-69, Sprint 4, 2026-10-27)

IS-69 builds where notifications land. Until now every story that said
someone "is notified" called a `print()` placeholder. Built: table
`public.notifications` (migration `20261027000000_notifications.sql`),
`app/notifications/notification_service.py`, routes in
`app/notifications/routes.py`, actions `notification.list` /
`notification.mark_read` / `notification.mark_all_read`. Backend only; the
bell and list in the web app are a separate change. The ticket's acceptance
criteria weren't in the repo, so the working criteria in
`docs/traceability.md` are our reading. They and the calls below are flagged
in docs/open-questions.md.

### The five hooks now write notifications, with their signatures unchanged

The five `_notify_*` hooks keep their names and arguments. Each body is now
one call handing those arguments to `notification_service`. Working out who
to tell, and every query that needs, lives in `notification_service`, so the
stories' own modules gain no notification queries:

| Hook (owner) | Calls | Who is told |
|---|---|---|
| `coordinator_service._notify_coordinator_assigned` (Justin) | `coordinator_assigned` | the coordinator assigned or reassigned |
| `booking_service._notify_booking_decision` (Josiah) | `venue_booking_decided` | the session's coordinator, for confirmed / rejected |
| `equipment_service._notify_request_decision` (Nawaz; also `change_service`) | `equipment_request_decided` | the session's coordinator, for confirmed / rejected / change accepted / change rejected |
| `safety_service._notify_safety_review` (Justin) | `safety_review_changed` | every Safety Officer for submitted / withdrawn; the session's coordinator for a decision |
| `venue_service._notify_venue_deleted` (Aaralyn) | `venue_booking_released` | the session's coordinator |

Four existing test files monkeypatch hooks (`test_coordinator_assignment.py`,
`test_coordinator_assignment_status.py`, `test_equipment_change.py`,
`test_equipment_reject.py`). They pass untouched, which is the evidence the
calling code didn't move. One `test_notification_hook_<name>.py` per hook
checks it passes its arguments through unchanged. Each hook's rewiring and
its test are their own commit, pending its owner's sign-off, so any of them
can be dropped and the suite stays green.

### Who is told: the session's current coordinator

A decision on a venue booking or equipment request goes to
`events.coordinator_id`, not to the booking's or request's `requested_by`.
Since reassignment (Week 7 #5), they can differ, and the coordinator running
the session now is the one who has to act on a decision. Nobody is told
about their own action: a coordinator cancelling their own booking gets
nothing, so the hook ignores `cancelled`. A session with no coordinator
notifies nobody.

A safety submission goes to every Safety Officer, since any of them may pick
it up (there's no assignment step). One row per officer, so each person's
read state is their own.

### In-app only

The container diagram already gives the API "in-app notifications" and the
SPA the job of showing them. Email and SMS are deferred. No mail or SMS
provider is set up, which means credentials, sender verification and a
delivery and bounce story nobody has scoped. Registrations' `notify_email` /
`notify_sms` preferences are stored, but nothing reads them yet.

### Writing is best effort: a failure is logged, not raised

Every hook runs after its story's own change is written. If writing the
notification then failed and raised, the caller would get a 500 for an
action that already happened (the booking IS confirmed), and might retry
it. So each writing function catches `Exception`, logs it with the
traceback (`logger.exception`), and returns. The trade-off: a notification
can be lost silently, as far as the user can tell. The log is the only
record, and there is no retry or outbox. That's acceptable while a
notification only says something the user can also see on the relevant
page. It would not be once a notification is the only way someone learns
something.

`BaseException` is not caught. The unit-test guard
(`UnitTestDatabaseAccessError`) is one on purpose, so a unit test that
reaches the real database still fails loudly. With the new conftest fixture
`_notifications_go_to_a_fake` disabled, 26 existing unit tests fail that
way; with it, they pass.

### The entity link has no foreign key

`entity_type` / `entity_id` say what a notification is about (`event` or
`safety_review` so far), so the frontend can link to it. One column can't
reference several tables, so there is no foreign key. Deleting the entity
leaves the notification pointing at nothing (an orphan). The table only
checks that a link has both halves or neither. Deletes are rare
(permanently deleted venues, drafts), and a link that leads nowhere should
be shown as plain text by the frontend. The alternative (one nullable
foreign-key column per entity type) needs a migration per new type, for a
cost that doesn't exist yet. `type` is text for the same reason, not an
enum: an enum value can never be removed.

### RLS: the recipient reads their own, nobody writes

Flask uses the service-role key and does the real check in `app/authz`. RLS
is still scoped to the recipient (`recipient_id = auth.uid()`), not the
"any authenticated user" placeholder on older tables, because a
notification names events and people. A signed-in caller going around Flask
must not read anyone else's. There is no insert, update or delete policy,
so only the backend writes. Proven by
`test_notifications_integration.py`. Mutation-tested by hand once: loosening
the live policy to `auth.role() = 'authenticated'` made
`test_a_signed_in_user_reads_only_their_own_notifications_directly` fail
(Alice's direct read returned Bob's notification). With it restored, all
pass.

### Reading and marking read

- `GET /notifications` gives the caller's own, newest first, capped at 50
  (`?unread=true` for unread only), plus `unread_count`.
- `GET /notifications/unread-count` is the bell's cheap poll.
- `POST /notifications/<id>/read` marks one read.
- `POST /notifications/read-all` marks all of the caller's read.

Every query is scoped to the caller in the service, because
`notification.list` is role-free and can't scope a query (same warning as
`EVENT_LIST`). Someone else's notification id is a 404, as is a malformed
one (instead of Postgres's 500). Marking read is conditioned on
`read_at IS NULL`, so a second mark keeps the first read time and isn't an
error. Mutation-tested by hand: removing that condition, and separately the
recipient scope on the list, each made the unit and integration tests fail.

### Out of scope

- **A reminder scheduler** (e.g. "your event starts tomorrow"). It needs a
  scheduler process; none exists, and APScheduler isn't a dependency. It
  currently has no owner or ticket.
- **New notification triggers.** Only the five existing hooks are wired.
  Events no hook covered are left to the stories that own them: IS-39's
  "Organizer is notified of cancellation", change-request notifications,
  and waitlist promotion. Each is now one `notify(...)` call.
- **PR #45** (Josiah, open) adds a sixth hook,
  `block_service._notify_coordinator_venue_blocked`. It needs the same
  one-line rewiring onto this service once it lands.
