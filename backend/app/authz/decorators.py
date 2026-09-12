"""
@require(action, loader=None) -- protect a Flask view with a policy
check. This is an interface for the other four developers; read this
docstring, not the function body, to use it.

USAGE:

    from app.authz.decorators import require
    from app.authz.actions import EVENT_APPROVE

    # Resource-based action: `loader` is called with the route's URL
    # kwargs and must return the resource to authorise against. The
    # loaded resource is then passed to the view as its first argument.
    @events_bp.route("/events/<event_id>/approve", methods=["POST"])
    @require(EVENT_APPROVE, loader=lambda event_id: load_event(event_id))
    def approve_event(event):
        ...

    # Role-only action: no `loader`, no resource, nothing extra passed
    # to the view.
    @events_bp.route("/events", methods=["POST"])
    @require(EVENT_CREATE)
    def create_event():
        ...

`loader` is free to raise NotFoundError itself (e.g. "no event with that
id") instead of returning None or similar -- that produces the exact
same 404 a failed authorisation would have produced for an action where
existence is sensitive (see app.authz.policy's docstring), which is the
point: a missing resource and a hidden one must be indistinguishable to
the caller, and letting the loader's own NotFoundError propagate
unmodified is how that stays true without this decorator needing to
know which actions are sensitive.

The caller must already be authenticated -- @require does not check
that itself, it calls app.auth.context.current_user(), which raises
AuthenticationError on its own if there's no authenticated user for this
request (routes are protected by default anyway; see app/auth/context.py).
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from app.auth.context import current_user
from app.authz.policy import authorise


def require(action: str, loader: Callable[..., Any] | None = None):
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(*args, **kwargs):
            user = current_user()
            if loader is not None:
                resource = loader(**kwargs)
                authorise(user, action, resource)
                return view_func(resource, *args, **kwargs)
            authorise(user, action, None)
            return view_func(*args, **kwargs)

        return wrapper

    return decorator
