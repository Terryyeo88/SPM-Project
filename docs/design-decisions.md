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
one resource" instead of removing it. The coordinator's window is `planning`
only — a direct match to the story's literal wording ("during planning"),
not an inference the way `event.cancel`'s range is, so there's no
open-questions.md entry for this one. One real bug came out of building
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
