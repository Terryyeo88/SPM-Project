"""
Action constants for the authorisation policy (app.authz.policy).

Plain strings, not an enum -- callers pass these directly to can()/
authorise(), and they need to read cleanly in a route decorator and a
traceback alike. Grouped by resource; "event.*" is everything this
schema (public.events) can express today.

Every action here traces to a specific acceptance criterion or user
story clarification -- see app/authz/rules.py's module docstring for the
rule built against each one, and docs/traceability.md for the test that
proves it. "The schema could technically support it" is not a source on
its own -- see rules.py's docstring on EVENT_LIST / EVENT_CREATE for why
that distinction matters.

Deliberately NOT here: anything about registrations, venues, or
equipment (no such tables exist yet -- whoever builds those stories
should add their own actions the same way, sourced the same way), and no
profile.view_* (GET /me needs no policy check at all; see app/me/routes.py).
"""

from __future__ import annotations

# -- events ------------------------------------------------------------

EVENT_VIEW = "event.view"
EVENT_LIST = "event.list"
EVENT_CREATE = "event.create"
EVENT_SUBMIT = "event.submit"
EVENT_EDIT = "event.edit"
EVENT_APPROVE = "event.approve"
EVENT_REJECT = "event.reject"
EVENT_REQUEST_CLARIFICATION = "event.request_clarification"
EVENT_CANCEL = "event.cancel"
EVENT_REASSIGN_COORDINATOR = "event.reassign_coordinator"
