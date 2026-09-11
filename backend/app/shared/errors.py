"""
Application error types.

These are the only exceptions the JSON error handlers registered in
app.create_app() know how to translate into a response. Anything else
becomes a generic 500 with no detail leaked (see app/__init__.py).
"""

from __future__ import annotations


class AppError(Exception):
    """Base for every error the API is allowed to expose to a caller.
    Subclasses fix a status_code and a machine-readable code; `message`
    is the human-readable detail, defaulting to the code itself."""

    status_code = 500
    code = "internal_error"

    def __init__(self, message: str | None = None):
        self.message = message or self.code
        super().__init__(self.message)


class AuthenticationError(AppError):
    """The caller didn't present a valid session at all."""

    status_code = 401
    code = "authentication_required"


class AuthorisationError(AppError):
    """The caller is authenticated, and the resource's existence is not
    itself sensitive -- they just aren't allowed to do this.

    This is deliberately NOT the error to raise for "you have no
    visibility into this resource at all". For that case, raise
    NotFoundError instead: a 403 tells a caller the resource exists but
    they're blocked, which is itself information they may not be
    entitled to (e.g. an Event Organizer probing another organizer's
    event id). Raising NotFoundError there makes "forbidden" and
    "doesn't exist" produce the same 404, so probing can't distinguish
    them. Use AuthorisationError only where the caller already
    legitimately knows the resource exists (e.g. they can see their own
    event, but can't edit it post-submission) -- that choice is made by
    whoever calls authorise()/raises this, typically app.authz, not by
    this class.
    """

    status_code = 403
    code = "not_authorised"


class NotFoundError(AppError):
    """The resource doesn't exist, OR the caller isn't entitled to know
    whether it does -- see AuthorisationError's docstring. Both cases
    return this same 404 on purpose."""

    status_code = 404
    code = "not_found"


class ValidationError(AppError):
    """The request itself is malformed -- bad/missing fields, not an
    authorisation or existence question."""

    status_code = 400
    code = "validation_error"
