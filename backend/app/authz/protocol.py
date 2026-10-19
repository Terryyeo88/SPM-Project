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


class VenueBookingLike(Protocol):
    id: str
    requested_by: str
    status: str


class VenueBookingWithEventLike(VenueBookingLike, Protocol):
    """venue_booking.cancel's resource: the booking plus its event's
    assigned coordinator and status (app.venues.routes.load_booking_with_event)."""

    event_coordinator_id: str | None
    event_status: str


class EquipmentRequestLike(Protocol):
    id: str
    requested_by: str
    status: str
    event_status: str | None


class SafetyReviewLike(Protocol):
    id: str
    event_id: str
    status: str
