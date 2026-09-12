# Using the authorisation module (`app/authz`)

For Aaralyn, Justin, Nawaz — when you build a route, use this, don't read the
internals. Full reasoning, if you ever want it, is in `docs/design-decisions.md`.

## Protecting a route: `@require`

```python
from app.authz.decorators import require
from app.authz.actions import EVENT_APPROVE

@events_bp.route("/events/<event_id>/approve", methods=["POST"])
@require(EVENT_APPROVE, loader=lambda event_id: load_event(event_id))
def approve_event(event):
    ...  # `event` is whatever your loader returned
```

`loader` gets called with the route's URL kwargs and must return the resource,
or raise `NotFoundError` itself if it genuinely doesn't exist — either way
produces the same 404 (see below). No resource to check? Drop `loader`
entirely: `@require(EVENT_CREATE)` — the view gets called with no extra
argument. Your route must already sit behind authentication, which it does
by default — every route is protected unless explicitly decorated `@public`.

## The action vocabulary

| Action | Who | What it checks |
|---|---|---|
| `EVENT_VIEW` | organiser (own event) or coordinator (assigned) | relationship only, any status |
| `EVENT_LIST` | organiser or coordinator | role only — **see warning below** |
| `EVENT_CREATE` | organiser | role only |
| `EVENT_SUBMIT` | organiser (own event) | status must be `draft` |
| `EVENT_EDIT` | organiser (own, `draft`) **or** coordinator (assigned, `planning`) | either relationship, its own status window |
| `EVENT_APPROVE` / `EVENT_REJECT` | coordinator (assigned) | status must be `under_review` |
| `EVENT_REQUEST_CLARIFICATION` | coordinator (assigned) | status must be `under_review` |
| `EVENT_CANCEL` | coordinator (assigned) | status in `approved, planning, confirmed` |
| `EVENT_REASSIGN_COORDINATOR` | current coordinator (assigned) | no status check |

All of it is in `app/authz/actions.py` (the strings) and `app/authz/rules.py`
(the logic, with the source story quoted for every precondition).

## `EVENT_LIST` and `EVENT_CREATE` do NOT scope your query for you

`can(user, EVENT_LIST)` passing means "this role is allowed to list
*something*" — it does **not** mean "return every event." If you're writing
a list endpoint, **you** must filter the query yourself:

- organiser listing -> `WHERE organizer_id = user.id`
- coordinator listing -> `WHERE coordinator_id = user.id`

Forgetting this filter is not a degraded experience — it's every event in
the table leaked to whoever calls the route. `can()` has no way to see your
query and cannot enforce this for you.

## 403 vs 404 — don't override it

`authorise()` picks the status code for you based on the rule's result. You
don't get to choose, and you shouldn't try to:

- **404** — the caller has no relationship to the resource at all. They
  aren't entitled to know it exists, so a 403 here would itself leak
  information (that it exists, just not to them).
- **403** — the caller *does* have a relationship (it's their event, or
  they're its coordinator) but something else blocks the action (wrong
  status, wrong coordinator-of-record). They already know it exists, so 403
  leaks nothing a 404 would have hidden.

If you catch yourself wanting to return 403 for "doesn't exist" or 404 for
"exists but you can't touch it right now," that's a sign the resource
relationship belongs in the rule, not in your route.

## Adding a new action (venues, equipment, registrations)

1. Add the resource's protocol to `app/authz/protocol.py` — just the fields
   a rule actually needs to read (see `EventLike` for the shape).
2. Add the action string(s) to `app/authz/actions.py`, one line each, with
   the story/criterion it comes from. No source, don't add it.
3. Add one rule function per action in `app/authz/rules.py`, returning a
   `Decision` (`ALLOW` / `DENY_NOT_FOUND` / `DENY_FORBIDDEN`) — relationship
   check first, status/condition check second, same shape as every existing
   rule. Keep it a pure function: no DB, no Flask, no imports beyond the
   protocol and other rules.
4. Register it in `app/authz/policy.py`'s `_RULES` dict. **Forgetting this
   step is not a crash and not a silent allow — it's a 403 for everyone,
   loudly, until you notice.** Still register it.
5. Use `@require` in your route, per the example above.

If an action genuinely has multiple roles, write the role-branching inside
the ONE rule function (see `rule_event_edit` for the pattern) — don't create
two actions for one verb just because two roles can do it.
