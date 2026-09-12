"""
Plain test-double factories for authz/auth tests.

Deliberately NOT conftest.py fixtures: a fixture can't take per-call
arguments (which roles, what status) without parametrize/indirect
tricks that make simple tests harder to read. Plain importable functions
and a plain dataclass do the same job with ordinary function calls.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.auth.context import CurrentUser


def make_user(roles, user_id: str = "user-1", email: str | None = None, name: str = "Test User") -> CurrentUser:
    return CurrentUser(
        id=user_id,
        email=email or f"{user_id}@example.com",
        name=name,
        roles=frozenset(roles),
        session_id="session-1",
    )


@dataclass(frozen=True)
class FakeEvent:
    """Implements app.authz.protocol.EventLike -- only the four
    attributes any rule in app.authz.rules actually reads, not the full
    events table."""

    id: str = "event-1"
    organizer_id: str = "organizer-1"
    coordinator_id: str | None = None
    status: str = "draft"
