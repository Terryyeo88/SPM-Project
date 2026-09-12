# Design decisions

Short entries for choices made on IS-1 (User Authorisation and Authentication)
that aren't obvious from the code alone. One paragraph each, written to defend
out loud, not as a changelog.

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
