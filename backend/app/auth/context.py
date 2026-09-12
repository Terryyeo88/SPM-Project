"""
Per-request authenticated user context.

register_auth_hooks(app), called once from the app factory, installs a
before_request hook that: verifies the bearer token (app.auth.jwt), then
enforces the session idle timeout, then loads the caller's profile and
roles in ONE database round trip, and attaches the result to flask.g as
a CurrentUser.

Order matters and is enforced in that order on purpose: verify the
token's signature first, so a token that was never valid doesn't cost a
database call at all; check idle timeout second, since that's a DB read
keyed only by the token's own session_id (still no profile load); only
once both of those pass do we load the profile, which is the most
expensive step.

Routes are PROTECTED by default. A route only becomes public by being
decorated with @public (see below) -- a teammate who adds a route
without thinking about auth gets a 401, not an open endpoint.

NOTE: `profiles` has no organisation_id, and no organisations table
exists anywhere in the schema (see
supabase/migrations/20260911120000_init_users_events.sql). CurrentUser
does NOT carry an organisation id because there is nothing in the
schema for it to carry -- don't invent one here. Organiser-scoped
authorisation in Phase 4 keys off events.organizer_id instead.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from flask import Flask, g, request

from app.auth.jwt import verify_token
from app.extensions import supabase
from app.shared.errors import AuthenticationError

# How rarely we actually write to session_activity on a session that's
# making frequent requests -- without this, every authenticated request
# would mean a write, for a value that's only ever checked in whole-
# minute windows anyway.
_ACTIVITY_DEBOUNCE_SECONDS = 60

_DEFAULT_IDLE_TIMEOUT_MINUTES = 30


@dataclass(frozen=True)
class CurrentUser:
    id: str
    email: str
    name: str
    roles: frozenset[str]
    session_id: str


def public(view_func):
    """Mark a route as exempt from authentication. This is how a route
    opts OUT of the login wall -- routes are protected by default, so a
    route added without this decorator stays behind it.

    Usage:
        @health_bp.route("/health")
        @public
        def health():
            return {"status": "ok"}
    """
    view_func._is_public = True
    return view_func


def current_user() -> CurrentUser:
    """The authenticated caller for this request. Raises
    AuthenticationError rather than returning None if somehow no user was
    attached (hook didn't run, or ran and found a public route) -- so
    downstream code never has to handle a None case."""
    user = g.get("current_user")
    if user is None:
        raise AuthenticationError("No authenticated user for this request.", code="auth_missing_token")
    return user


def register_auth_hooks(app: Flask) -> None:
    @app.before_request
    def _authenticate() -> None:
        if request.endpoint in (None, "static"):
            # None: Flask hasn't matched a route yet (e.g. a 404) --
            # nothing to authenticate, the routing layer handles it.
            # "static": Flask's own built-in static-file endpoint, not
            # an application route.
            return

        view_func = app.view_functions.get(request.endpoint)
        if getattr(view_func, "_is_public", False):
            return

        claims = verify_token(request.headers.get("Authorization"))
        user_id = claims["sub"]
        session_id = claims["session_id"]

        _check_and_update_session_activity(session_id, user_id)

        name, email, roles = _load_profile_with_roles(user_id)
        g.current_user = CurrentUser(
            id=user_id, email=email, name=name, roles=roles, session_id=session_id,
        )


def _idle_timeout_minutes() -> int:
    # os.environ.get's default only applies when the key is ABSENT -- a
    # key present but empty (e.g. a teammate copied .env.example and left
    # this blank) would otherwise reach int("") and raise. `or` catches
    # both cases.
    return int(os.environ.get("SESSION_IDLE_TIMEOUT_MINUTES") or _DEFAULT_IDLE_TIMEOUT_MINUTES)


def _check_and_update_session_activity(session_id: str, user_id: str) -> None:
    now = datetime.now(timezone.utc)
    last_active = _get_last_active(session_id)

    if last_active is not None and (now - last_active) > timedelta(minutes=_idle_timeout_minutes()):
        # Deliberately return WITHOUT touching last_active first -- a
        # request that arrives after the timeout window must not be able
        # to silently refresh its own clock on the way to being rejected.
        raise AuthenticationError("Session has been idle too long.", code="auth_session_idle")

    if last_active is None or (now - last_active).total_seconds() >= _ACTIVITY_DEBOUNCE_SECONDS:
        _touch_session_activity(session_id, user_id, now)


def _get_last_active(session_id: str) -> datetime | None:
    result = (
        supabase.table("session_activity")
        .select("last_active_at")
        .eq("session_id", session_id)
        .maybe_single()
        .execute()
    )
    # maybe_single().execute() returns None itself (not a response object
    # with .data = None) when zero rows match -- confirmed against the
    # real table, not assumed.
    if result is None or not result.data:
        return None
    return datetime.fromisoformat(result.data["last_active_at"])


def _touch_session_activity(session_id: str, user_id: str, now: datetime) -> None:
    supabase.table("session_activity").upsert(
        {"session_id": session_id, "user_id": user_id, "last_active_at": now.isoformat()},
        on_conflict="session_id",
    ).execute()


def _load_profile_with_roles(user_id: str) -> tuple[str, str, frozenset[str]]:
    """One round trip: profile fields plus every role row, joined."""
    result = (
        supabase.table("profiles")
        .select("name, email, user_roles(role)")
        .eq("id", user_id)
        .single()
        .execute()
    )
    profile: dict[str, Any] = result.data
    roles = frozenset(row["role"] for row in profile.get("user_roles", []))
    return profile["name"], profile["email"], roles
