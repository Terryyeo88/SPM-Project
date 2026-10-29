"""In-app notifications (IS-69: Notification System).

Two halves:

  WRITING -- notify(), plus one function per thing that notifies someone.
  Each of those is what a story's _notify_* hook now calls, with the hook's
  own arguments (the hooks' signatures are unchanged):

    coordinator_service._notify_coordinator_assigned -> coordinator_assigned
    booking_service._notify_booking_decision         -> venue_booking_decided
    equipment_service._notify_request_decision       -> equipment_request_decided
      (also change_service's accept/reject, which call the same hook)
    safety_service._notify_safety_review             -> safety_review_changed
    venue_service._notify_venue_deleted              -> venue_booking_released

  Working out WHO to tell (the session's current coordinator, every Safety
  Officer) and writing the rows both happen here, so the stories' own
  modules don't gain any notification queries.

  READING -- the recipient's own list, unread count, mark one / all read
  (app/notifications/routes.py).

BEST EFFORT: every writing function runs AFTER the story's own change has
been written, and a failure to notify must not turn that change into an
error response (the booking IS confirmed; reporting a 500 would make the
caller retry something that already happened). So a writing function that
hits an Exception logs it, with the traceback, and returns -- the
notification is lost, the action stands. See docs/design-decisions.md
(IS-69) for the trade-off. BaseException is not caught, so the unit-test
database guard (conftest.py) still fails a test loudly.

WHO IS TOLD about an event session's arrangements is that session's
CURRENT assigned coordinator (events.coordinator_id), not whoever made the
request: a reassigned session's new coordinator is the one who has to act
on a decision. Nobody is told about their own action (a coordinator
cancelling their own booking). See docs/design-decisions.md (IS-69).

The entity reference (entity_type / entity_id) has no foreign key -- see
the migration. ENTITY_* below is the vocabulary the frontend links from.
"""

from __future__ import annotations

import functools
import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from app.extensions import supabase
from app.shared.errors import NotFoundError, ValidationError

logger = logging.getLogger(__name__)

TABLE = "notifications"

# The most a list returns: the bell shows recent notifications, not an
# archive. The unread count is not capped by it.
LIST_LIMIT = 50

# What a notification links to.
ENTITY_EVENT = "event"
ENTITY_SAFETY_REVIEW = "safety_review"

# Notification types (notifications.type).
COORDINATOR_ASSIGNED = "coordinator_assigned"
VENUE_BOOKING_CONFIRMED = "venue_booking_confirmed"
VENUE_BOOKING_REJECTED = "venue_booking_rejected"
VENUE_BOOKING_RELEASED = "venue_booking_released"
EQUIPMENT_REQUEST_CONFIRMED = "equipment_request_confirmed"
EQUIPMENT_REQUEST_REJECTED = "equipment_request_rejected"
EQUIPMENT_CHANGE_ACCEPTED = "equipment_change_accepted"
EQUIPMENT_CHANGE_REJECTED = "equipment_change_rejected"
SAFETY_REVIEW_SUBMITTED = "safety_review_submitted"
SAFETY_REVIEW_WITHDRAWN = "safety_review_withdrawn"
SAFETY_REVIEW_APPROVED = "safety_review_approved"
SAFETY_REVIEW_REJECTED = "safety_review_rejected"
SAFETY_REVIEW_CHANGES_REQUESTED = "safety_review_changes_requested"

SAFETY_OFFICER_ROLE = "safety_officer"


def _best_effort(func):
    """See BEST EFFORT in the module docstring."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception:
            logger.exception("Notification not sent: %s failed", func.__name__)
            return None

    return wrapper


# -- writing -------------------------------------------------------------------


@_best_effort
def notify(
    recipient_ids: Iterable[str | None],
    type_: str,
    message: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
) -> int:
    """One notification row per distinct recipient (None skipped), in one
    insert. Returns how many were written."""
    recipients = sorted({recipient for recipient in recipient_ids if recipient})
    if not recipients:
        return 0
    rows = [
        {
            "recipient_id": recipient,
            "type": type_,
            "message": message,
            "entity_type": entity_type,
            "entity_id": entity_id,
        }
        for recipient in recipients
    ]
    supabase.table(TABLE).insert(rows).execute()
    return len(rows)


def _event(event_id: str | None) -> dict | None:
    """The session's name and current coordinator, or None."""
    if not event_id:
        return None
    result = supabase.table("events").select("id, name, coordinator_id").eq("id", event_id).maybe_single().execute()
    return result.data if result is not None else None


def _users_with_role(role: str) -> list[str]:
    result = supabase.table("user_roles").select("user_id").eq("role", role).execute()
    return [row["user_id"] for row in result.data or []]


def _notify_coordinator_of(event: dict | None, type_: str, message: str) -> None:
    if event:
        notify([event.get("coordinator_id")], type_, message, ENTITY_EVENT, event["id"])


@_best_effort
def coordinator_assigned(event: dict, coordinator: dict) -> None:
    """Week 7 change #5: "Relevant users should be notified when assignments
    or reassignments occur." One notification for the request, not one per
    session (the caller's own rule), linked to the session it was called
    with."""
    notify(
        [coordinator["id"]],
        COORDINATOR_ASSIGNED,
        f'You have been assigned to coordinate "{event["name"]}".',
        ENTITY_EVENT,
        event["id"],
    )


_BOOKING_DECISIONS = {
    "confirmed": (VENUE_BOOKING_CONFIRMED, 'Your venue booking for "{name}" was confirmed.'),
    "rejected": (VENUE_BOOKING_REJECTED, 'Your venue booking for "{name}" was rejected.'),
}


@_best_effort
def venue_booking_decided(booking: dict, decision: str) -> None:
    """IS-14: "An approved booking should notify the Coordinator" (and a
    rejected one, with its reason on the event page). "cancelled" is the
    coordinator's own action, so nobody is told (see the module docstring)."""
    if decision not in _BOOKING_DECISIONS:
        return
    type_, template = _BOOKING_DECISIONS[decision]
    event = _event(booking.get("event_id"))
    if event:
        _notify_coordinator_of(event, type_, template.format(name=event["name"]))


@_best_effort
def venue_booking_released(released_booking: dict, venue: dict) -> None:
    """IS-61 AC4: a deleted venue's ongoing bookings are released and "their
    coordinator is alerted ... to book another venue". The event page's
    alert (VenueRemovedAlert.vue) stays; this tells them to go and look."""
    event = _event(released_booking.get("event_id"))
    if event:
        _notify_coordinator_of(
            event,
            VENUE_BOOKING_RELEASED,
            f'Venue "{venue["name"]}" was deleted from the venue catalogue, so the booking for '
            f'"{event["name"]}" was released. Book another venue.',
        )


_EQUIPMENT_DECISIONS = {
    "confirmed": (EQUIPMENT_REQUEST_CONFIRMED, 'Your equipment request for "{name}" was accepted.'),
    "rejected": (EQUIPMENT_REQUEST_REJECTED, 'Your equipment request for "{name}" was rejected.'),
    "change accepted": (EQUIPMENT_CHANGE_ACCEPTED, 'Your equipment change for "{name}" was accepted.'),
    "change rejected": (EQUIPMENT_CHANGE_REJECTED, 'Your equipment change for "{name}" was rejected.'),
}


@_best_effort
def equipment_request_decided(request_id: str, decision: str) -> None:
    """IS-19/IS-41/IS-43: Technical Support Staff's decisions on a request
    (and on a change to a confirmed one). IS-41: "Rejecting requires an
    explanation that's sent to the Event Coordinator" -- the reason itself
    stays on the request, where the coordinator's page shows it."""
    if decision not in _EQUIPMENT_DECISIONS:
        return
    result = supabase.table("equipment_requests").select("event_id").eq("id", request_id).maybe_single().execute()
    request = result.data if result is not None else None
    event = _event(request.get("event_id")) if request else None
    if event:
        type_, template = _EQUIPMENT_DECISIONS[decision]
        _notify_coordinator_of(event, type_, template.format(name=event["name"]))


_SAFETY_DECISIONS = {
    "approved": (SAFETY_REVIEW_APPROVED, 'The safety check for "{name}" was approved.'),
    "rejected": (SAFETY_REVIEW_REJECTED, 'The safety check for "{name}" was rejected.'),
    "changes_requested": (
        SAFETY_REVIEW_CHANGES_REQUESTED,
        'The Safety Officer requested changes to "{name}".',
    ),
}


def _notify_safety_officers(review: dict, type_: str, message: str) -> None:
    notify(_users_with_role(SAFETY_OFFICER_ROLE), type_, message, ENTITY_SAFETY_REVIEW, review["id"])


@_best_effort
def safety_review_changed(review: dict, what: str) -> None:
    """Week 7 change #6. A submission goes to every Safety Officer (any of
    them may pick it up -- there's no assignment step), as does a pending
    review withdrawn because its venue was deleted (it leaves their queue).
    A decision goes to the session's coordinator, who "will decide on the
    subsequent action"."""
    event = _event(review.get("event_id"))
    if not event:
        return
    if what == "submitted":
        _notify_safety_officers(review, SAFETY_REVIEW_SUBMITTED, f'"{event["name"]}" is waiting for a safety check.')
    elif what == "withdrawn":
        _notify_safety_officers(
            review,
            SAFETY_REVIEW_WITHDRAWN,
            f'The safety check for "{event["name"]}" was withdrawn: its venue was deleted.',
        )
    elif what in _SAFETY_DECISIONS:
        type_, template = _SAFETY_DECISIONS[what]
        _notify_coordinator_of(event, type_, template.format(name=event["name"]))


# -- reading -------------------------------------------------------------------


def _parse_unread_only(value: str | None) -> bool:
    if value is None:
        return False
    if value in ("true", "1"):
        return True
    if value in ("false", "0"):
        return False
    raise ValidationError("unread must be true or false.")


def list_notifications(user_id: str, unread: str | None = None) -> list[dict]:
    """The caller's own notifications, newest first, at most LIST_LIMIT.
    Scoped HERE, not by authz (see rule_notification_list): every query
    filters to recipient_id = the caller."""
    query = supabase.table(TABLE).select("*").eq("recipient_id", user_id)
    if _parse_unread_only(unread):
        query = query.is_("read_at", "null")
    result = query.order("created_at", desc=True).limit(LIST_LIMIT).execute()
    return result.data or []


def unread_count(user_id: str) -> int:
    result = supabase.table(TABLE).select("id").eq("recipient_id", user_id).is_("read_at", "null").execute()
    return len(result.data or [])


def get_notification(notification_id: str) -> dict:
    """Raises NotFoundError for a missing row -- and for an id that isn't a
    UUID at all, which Postgres would otherwise refuse with a 500."""
    try:
        uuid.UUID(notification_id)
    except (ValueError, TypeError) as exc:
        raise NotFoundError("Notification not found.") from exc
    result = supabase.table(TABLE).select("*").eq("id", notification_id).maybe_single().execute()
    if result is None or not result.data:
        raise NotFoundError("Notification not found.")
    return result.data


def mark_read(notification_id: str, user_id: str) -> dict:
    """Marks one of the caller's notifications read and returns it. authz
    (rule_notification_mark_read) has already checked it's theirs; the
    update is scoped to them anyway. Conditioned on read_at still being
    NULL, so marking it again (another tab, a double click) keeps the first
    read time and is not an error."""
    result = (
        supabase.table(TABLE)
        .update({"read_at": datetime.now(UTC).isoformat()})
        .eq("id", notification_id)
        .eq("recipient_id", user_id)
        .is_("read_at", "null")
        .execute()
    )
    if result.data:
        return result.data[0]
    return get_notification(notification_id)


def mark_all_read(user_id: str) -> int:
    """Marks every unread notification of the caller's read; returns how
    many changed. Already-read ones keep their read time."""
    result = (
        supabase.table(TABLE)
        .update({"read_at": datetime.now(UTC).isoformat()})
        .eq("recipient_id", user_id)
        .is_("read_at", "null")
        .execute()
    )
    return len(result.data or [])
