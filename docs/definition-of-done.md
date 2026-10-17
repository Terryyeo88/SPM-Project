# Definition of Done

A story is not Done until every box below is ticked. The reviewer ticks them,
not the author.

## Acceptance criteria

- [ ] Every AC in the story is either implemented or explicitly logged in `docs/open-questions.md` as deferred/out of scope, with a reason, never silently skipped.
- [ ] Any interpretive call made because the story text didn't fully specify something is written up in `docs/design-decisions.md` (the reasoning) and flagged in `docs/open-questions.md` (the "please confirm").
- [ ] `docs/traceability.md` has a row mapping each AC to its test and its implementation.

## Code

- [ ] New authz actions follow the 5-step checklist in `docs/authz-usage.md` (action → protocol if needed → rule with explicit 404-vs-403 reasoning → registered in `policy._RULES`).
- [ ] Any status write goes through the established guarded mechanism (`transitions.transition()` for events), never a raw `UPDATE ... SET status`. This is exactly the gap that got caught in IS-14 review; it's now a checklist item specifically because it slipped through once.
- [ ] A new migration has a scope comment header, a rollback-intent block at the end, RLS enabled with at least a placeholder policy, and its timestamp checked against every other currently-open branch/PR for a collision (the IS-14/coordinator-lead collision cost a rename after merge; check `supabase/migrations/` on main and on sibling open PRs before picking a timestamp).
- [ ] `ruff check .` clean.

## Tests

- [ ] Unit tests pass with no real database reachable (the autouse guard in `conftest.py` catches this).
- [ ] Integration tests (`@pytest.mark.integration`) exist for anything that needs a real DB to prove (joins, constraints, RLS) and pass against a local Supabase.
- [ ] Any race-prone or easy-to-get-wrong guard (a conditional update, an overlap check, an exclusion constraint) is mutation-tested by hand once: break it, confirm the test catches the break, restore it. Don't just trust that a passing suite means the guard is actually load-bearing.
- [ ] Full suite run, not just the new files, to confirm nothing upstream broke.
- [ ] Frontend: `npm run build` clean, `npm test` passes, and any new route has a `ROUTE_ACCESS` entry (the drift guard in `router/index.test.js` enforces this structurally; don't bypass it).

## Before pushing

- [ ] Fresh-install simulation: fresh venv `pip install` + fresh `npm ci`, full suite, from a clean copy, not just "it works in my already-set-up environment."
- [ ] Branch is merge-clean against current main, not stale. Check right before pushing, not once at branch-creation time.
- [ ] Any change to a file owned by another story/teammate gets their explicit sign-off before it lands, even if it's small and obviously correct (see Terry's `[PENDING JOSIAH'S SIGN-OFF]` commit as the model: built, tested, clearly marked droppable, merged only after an actual yes).
- [ ] New functionality is tracked as a pointed story, never folded into a `fix(...)` commit to dodge backlog visibility. `fix` is reserved for correcting already-accepted behavior, not for new scope.

## PR / CI

- [ ] PR description states what shipped, what's explicitly flagged for review, and a test-plan checklist (what was actually run, what wasn't and why, e.g. no local Supabase, no browser available).
- [ ] Both CI jobs (`test`, `frontend-test`) green on the PR itself, not just locally.
- [ ] Reviewed and merged, not left open past the point it's actually ready (PR #18 sitting CI-green with zero reviews for two days is the thing to avoid repeating).