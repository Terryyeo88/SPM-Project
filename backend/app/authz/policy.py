"""
can(user, action, resource=None) -> bool
authorise(user, action, resource=None) -> None, raises on denial

DENY BY DEFAULT: an action string with no registered rule -- whether
it's simply not a real action at all, or a real one from
app.authz.actions that a teammate forgot to wire into _RULES below --
returns False from can(), never True, and AuthorisationError (403) from
authorise(). 403, not 404: there is no resource whose existence needs
hiding in this case, only a missing rule. A loud 403 surfaces that gap
immediately; a quiet 404 would make a wiring bug look like a correct
access decision, which is the worse failure mode for something this
central.

THE 403-vs-404 CHOICE for everything else comes straight from
app.authz.rules' Decision:

  DENY_NOT_FOUND  -> NotFoundError (404). The caller has no qualifying
                     relationship to the resource at all -- they aren't
                     entitled to know it exists, so hiding it is the
                     whole point (see app.shared.errors.AuthorisationError's
                     docstring, which this module is the concrete
                     realisation of).
  DENY_FORBIDDEN  -> AuthorisationError (403). The caller DOES have a
                     qualifying relationship (it's their event, or
                     they're its assigned coordinator), but some other
                     condition blocks the action -- they already
                     legitimately know the resource exists, so 403
                     leaks nothing a 404 would have hidden.

Rules decide which one applies, not the caller of authorise() -- see
app.authz.rules' module docstring for exactly how each rule decides.
That's deliberate: leaving this judgement call to each route/service
author is how you end up with the same action returning 403 in one
place and 404 in another for the same reason.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.authz import actions
from app.authz.rules import (
    Decision,
    rule_event_approve,
    rule_event_cancel,
    rule_event_create,
    rule_event_delete,
    rule_event_edit,
    rule_event_list,
    rule_event_reassign_coordinator,
    rule_event_reject,
    rule_event_request_clarification,
    rule_event_submit,
    rule_event_view,
)
from app.shared.errors import AuthorisationError, NotFoundError

RuleFunc = Callable[[Any, Any], Decision]

_RULES: dict[str, RuleFunc] = {
    actions.EVENT_VIEW: rule_event_view,
    actions.EVENT_LIST: rule_event_list,
    actions.EVENT_CREATE: rule_event_create,
    actions.EVENT_SUBMIT: rule_event_submit,
    actions.EVENT_EDIT: rule_event_edit,
    actions.EVENT_DELETE: rule_event_delete,
    actions.EVENT_APPROVE: rule_event_approve,
    actions.EVENT_REJECT: rule_event_reject,
    actions.EVENT_REQUEST_CLARIFICATION: rule_event_request_clarification,
    actions.EVENT_CANCEL: rule_event_cancel,
    actions.EVENT_REASSIGN_COORDINATOR: rule_event_reassign_coordinator,
}


def _decide(user: Any, action: str, resource: Any) -> Decision:
    rule = _RULES.get(action)
    if rule is None:
        return Decision.DENY_FORBIDDEN
    return rule(user, resource)


def can(user: Any, action: str, resource: Any = None) -> bool:
    return _decide(user, action, resource) is Decision.ALLOW


def authorise(user: Any, action: str, resource: Any = None) -> None:
    decision = _decide(user, action, resource)
    if decision is Decision.ALLOW:
        return
    if decision is Decision.DENY_NOT_FOUND:
        raise NotFoundError("Resource not found.")
    raise AuthorisationError(f"Not authorised to perform '{action}'.")
