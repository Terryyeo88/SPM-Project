"""
Structural typing for what a rule needs from a resource -- NOT the full
shape of any real table. Each protocol should expose only the attributes
rules actually read, nothing more.

Add new protocols here as new resource types get policy rules (e.g.
VenueLike, RegistrationLike, once those tables and stories exist) --
follow this same pattern. Do not add a protocol for a resource that has
no rule written against it yet; an unused protocol is exactly the kind
of thing that silently goes stale and misleads the next reader about
what's actually implemented.
"""

from __future__ import annotations

from typing import Protocol


class EventLike(Protocol):
    id: str
    organizer_id: str
    coordinator_id: str | None
    status: str
