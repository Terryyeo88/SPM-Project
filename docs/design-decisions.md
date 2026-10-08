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
the migration; `20261008000000_event_change_requests_and_logs.sql` was
rewritten to match them (live is the source of truth, as in
§"Live schema was the source of truth when reconciling migrations"),
plus two agreed fixes it also applies to live: `event_logs.change_request_id`
renamed to `event_log_id` (it is the entry's own id, not a link), and
`event_change_requests.reviewed_at` restored (so a rejection records when
it was decided).

