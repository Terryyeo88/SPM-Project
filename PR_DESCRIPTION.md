<!--
Drafted for IS-1. Not opened as a PR by Claude -- paste into the actual PR,
then this file can be deleted.
-->

## Summary

This branch implements IS-1 (User Authorisation and Authentication):
JWT verification against this Supabase project's real signing-key system,
per-request session context with a server-enforced idle timeout, and a
centralised `app/authz` policy module that's the single place every
role/relationship/status rule for events lives. It also restructures
`backend/` into a proper Flask package, adds a CI pipeline that runs with
zero Supabase secrets, and leaves the backend in a state where the other
four stories (events, venues, equipment, registrations) have a tested
interface (`@require`, `can()`/`authorise()`) to build their routes against.

## Acceptance criteria

- [x] A user's access is limited to their role AND their relationship to an
  event — `tests/test_authz_policy.py` (whole file; every action checks
  relationship, not just role)
- [x] An organiser sees full details of their own events; other organisers'
  events are hidden — `test_organiser_denied_on_another_organisers_event`,
  `test_organiser_allowed_on_own_event`
- [x] An organiser cannot edit directly after submission; changes go via
  the coordinator — `test_organiser_denied_edit_after_submission`,
  `test_organiser_allowed_edit_while_draft`
- [x] A coordinator acts only on events assigned to them (approve/reject/
  request clarification/cancel/reassign) — see `docs/traceability.md` for
  the full per-action test list
- [x] A coordinator can update event information during planning (closed
  a real gap — no rule permitted this before) — `test_coordinator_allowed_
  edit_assigned_event_in_planning` and siblings
- [x] A coordinator can cancel an approved event — `test_coordinator_
  allowed_cancel_post_approval_on_own_event`
- [x] A user with multiple roles gets the union of their permissions,
  structurally — `test_multi_role_user_gets_union_of_permissions`,
  `test_multi_role_union_on_same_event_for_edit`
- [x] Given a user session, idle beyond a defined timeout logs them out —
  `test_idle_session_rejected_with_auth_session_idle`
- [x] Deny by default: unknown or unwired actions never allow —
  `test_unknown_action_denied`, `test_registered_action_with_no_rule_denied`
- [ ] An attendee cannot view another attendee's registration — **deferred**,
  see below
- [ ] An attendee sees no internal planning information — **deferred**,
  see below

Full criterion -> test -> implementation mapping: `docs/traceability.md`.

## Restructuring (Phase 1) — what moved

`backend/` is now a package, not a flat script directory:

- `backend/supabase_client.py` -> `backend/app/extensions.py`
- `backend/coordinator_assignment.py` -> `backend/app/events/coordinator_service.py`

**For teammates:** if you have local changes against the old paths, they'll
need re-pointing to the new module paths (`from app.extensions import
supabase`, `from app.events.coordinator_service import ...`). Both moves
were done as git renames (verified with `git show --stat --find-renames`),
so `git blame`/history on these files is intact, not reset.

## For Justin

`reassign_coordinator`'s `requested_by=None` escape hatch is ready to have
the policy plugged in, but I haven't touched your file (changed it once
already this sprint, didn't want to make it twice without you in the loop):

```python
from app.authz.policy import authorise
from app.authz.actions import EVENT_REASSIGN_COORDINATOR

authorise(current_user(), EVENT_REASSIGN_COORDINATOR, event)  # replaces the requested_by check
```

Also: your two manual test scripts (`test_assignment.py`,
`test_reassignment.py`) were converted into real, independent pytest tests
(`backend/tests/test_coordinator_assignment_integration.py`) and the
originals deleted. Your coverage (workload-based pick, conflict skip,
reassignment + audit log) is preserved; nothing of yours was dropped except
one scenario I added myself and then found untestable against our shared
seeded project (see that test file's docstring).

## Deferred, and why

- **Registrations** — no `registrations` table or attendee-event linkage
  exists in the schema yet. No action, no rule, no test; whoever builds
  that story should add rules the same way (`docs/authz-usage.md`).
- **Field-level visibility** ("no internal planning information" for
  attendees) — this is a serialisation concern, not a `can()` yes/no
  decision, and no event route/serialiser exists yet to build it against.
  Argued in full in `docs/design-decisions.md`.

## Open questions for the customer

See `docs/open-questions.md` — currently one item: whether `event.cancel`'s
"after approval" was meant as the range `approved/planning/confirmed` (what
we implemented, because the story's own scenario needs it) or literally
just the single status `approved`.

## Known gap, not part of this PR

Migrations are applied by hand via the Supabase SQL Editor; nothing
enforces that every environment is on the same version. Documented in the
README, raised separately at standup.
