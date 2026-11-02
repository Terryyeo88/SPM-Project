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

  IS-26 (Receive Technical Support Notifications) -- the "Technical Support
  Staff" section:

    equipment_service._notify_technical_support      -> technical_support_request_news
      (also change_service.create_change_request, for a quantity change)
    events.routes._notify_technical_support_cancelled -> technical_support_event_news
    event_update.notify_technical_support_of_change   -> technical_support_event_news

  IS-76 (Notification (Attendees)) -- see the "attendees" section:

    registration_service._notify_registered          -> registration_recorded
    registration_service._notify_withdrawn           -> registration_withdrawn
    events.routes._notify_attendees_cancelled        -> event_cancelled
    events.routes._notify_attendees_reconfirmed      -> event_reconfirmed

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
from datetime import UTC, date, datetime, time

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
# The attendee's own page for a session (/attend/<id>) -- attendees can't
# open the "event" page.
ENTITY_ATTENDEE_EVENT = "attendee_event"

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
REGISTRATION_CONFIRMED = "registration_confirmed"
REGISTRATION_WAITLISTED = "registration_waitlisted"
REGISTRATION_PROMOTED = "registration_promoted"
REGISTRATION_WITHDRAWN = "registration_withdrawn"
EVENT_DETAILS_UPDATED = "event_details_updated"
EVENT_CANCELLED = "event_cancelled"

SAFETY_OFFICER_ROLE = "safety_officer"

# IS-26 (Receive Technical Support Notifications).
TECHNICAL_SUPPORT_ROLE = "technical_support_staff"
ENTITY_EQUIPMENT_REQUEST = "equipment_request"
EQUIPMENT_REQUEST_SUBMITTED = "equipment_request_submitted"
EQUIPMENT_CHANGE_REQUESTED = "equipment_change_requested"
EQUIPMENT_REQUEST_CANCELLED = "equipment_request_cancelled"
EQUIPMENT_EVENT_CANCELLED = "equipment_event_cancelled"
EQUIPMENT_EVENT_CHANGED = "equipment_event_changed"
# The session details Technical Support arrange around (the same ones
# change_impact's technical-support check watches): the date and time, the
# equipment list and the room layout.
TECHNICAL_SUPPORT_TIMING_FIELDS = frozenset(
    {"preferred_start_date", "preferred_end_date", "preferred_start_time", "preferred_end_time"}
)
TECHNICAL_SUPPORT_FIELDS = TECHNICAL_SUPPORT_TIMING_FIELDS | {"equipment", "room_layout"}
_LIVE_EQUIPMENT_REQUEST_STATUSES = ("pending", "confirmed")


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


# -- Technical Support Staff (IS-26) ------------------------------------------
#
# Every Technical Support Staff member is told: the system has no
# assignment of staff to requests or events, so "the relevant Technical
# Support Staff" can only mean the role (see docs/design-decisions.md).
# "Relevant" is enforced on the other side: an event is only worth a
# notification if it has an equipment request still waiting or confirmed,
# and an event change only if it touched the date, time, equipment or room
# layout. The person who did the thing is never told about it.


def _technical_support_ids(actor_id: str | None) -> list[str]:
    return [user for user in _users_with_role(TECHNICAL_SUPPORT_ROLE) if user != actor_id]


def _live_equipment_requests(event_id: str) -> list[dict]:
    result = (
        supabase.table("equipment_requests")
        .select("id, status")
        .eq("event_id", event_id)
        .in_("status", list(_LIVE_EQUIPMENT_REQUEST_STATUSES))
        .execute()
    )
    return sorted(result.data or [], key=lambda row: str(row["id"]))


_TECHNICAL_SUPPORT_REQUEST_NEWS = {
    "submitted": (EQUIPMENT_REQUEST_SUBMITTED, 'A new equipment request for "{name}" is waiting for your review.'),
    "change requested": (
        EQUIPMENT_CHANGE_REQUESTED,
        'The coordinator asked to change the quantity of an item on the equipment request for "{name}".',
    ),
    "cancelled": (
        EQUIPMENT_REQUEST_CANCELLED,
        'The equipment request for "{name}" was cancelled by the coordinator.',
    ),
}


@_best_effort
def technical_support_request_news(request_id: str, what: str, actor_id: str | None = None) -> None:
    """IS-26 AC1/AC2: a request is submitted, a quantity change is asked
    for on a confirmed one, or a request is withdrawn (IS-66)."""
    if what not in _TECHNICAL_SUPPORT_REQUEST_NEWS:
        return
    result = supabase.table("equipment_requests").select("event_id").eq("id", request_id).maybe_single().execute()
    request = result.data if result is not None else None
    event = _event(request.get("event_id")) if request else None
    if not event:
        return
    type_, template = _TECHNICAL_SUPPORT_REQUEST_NEWS[what]
    notify(
        _technical_support_ids(actor_id),
        type_,
        template.format(name=event["name"]),
        ENTITY_EQUIPMENT_REQUEST,
        request_id,
    )


@_best_effort
def technical_support_event_news(
    event_id: str, what: str, changed_fields: Iterable[str] = (), actor_id: str | None = None
) -> None:
    """IS-26 AC3/AC4: a session with equipment arranged was cancelled
    (what == "cancelled") or had its date, time, equipment or room layout
    changed (what == "changed", with the fields). Nothing is sent for a
    session with no live equipment request, or for a change that touched
    none of those fields."""
    if what == "changed":
        touched = set(changed_fields) & TECHNICAL_SUPPORT_FIELDS
        if not touched:
            return
    elif what != "cancelled":
        return
    event = _event(event_id)
    requests = _live_equipment_requests(event_id) if event else []
    if not requests:
        return
    name = event["name"]
    if what == "cancelled":
        type_ = EQUIPMENT_EVENT_CANCELLED
        message = f'"{name}" was cancelled. Its equipment has been released.'
    elif touched & TECHNICAL_SUPPORT_TIMING_FIELDS:
        type_ = EQUIPMENT_EVENT_CHANGED
        message = f'"{name}" was rescheduled. Check that its equipment booking still fits the new date and time.'
    else:
        type_ = EQUIPMENT_EVENT_CHANGED
        message = f'The equipment or room layout for "{name}" was changed. Check its equipment booking.'
    notify(_technical_support_ids(actor_id), type_, message, ENTITY_EQUIPMENT_REQUEST, requests[0]["id"])


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


# -- attendees (IS-76: Notification (Attendees)) -------------------------------
#
# Who is told: a session's attendees are its registrations that are
# "confirmed" or "waitlisted" (withdrawing deletes the row, so nobody else
# has one) -- AC10: anyone else hears nothing. One session at a time
# (AC9): each session is its own events row, and every query here is
# scoped to that one row.
#
# Details changes (AC5-AC7) are told when the session is CONFIRMED AGAIN,
# not at each edit: a change to a confirmed session sends it back to
# planning, and only reconfirmation means the new arrangements are final.
# A session cancelled before that gets only the cancellation (AC6). See
# docs/design-decisions.md (IS-76).

ATTENDEE_STATUSES = ("confirmed", "waitlisted")

# AC "Relevant event details": session date and time, venue, and event
# name. Venue isn't an event field -- it's the session's confirmed venue
# bookings, compared separately (_venue_changed_since).
ATTENDEE_RELEVANT_SESSION_FIELDS = frozenset(
    {"preferred_start_date", "preferred_end_date", "preferred_start_time", "preferred_end_time"}
)
# Shared by every session of the request, and logged once (on whichever
# session it was made on), so it counts for every session.
ATTENDEE_RELEVANT_SHARED_FIELDS = frozenset({"name"})


def _session(event_id: str | None) -> dict | None:
    """What the attendee notifications need from one session, or None."""
    if not event_id:
        return None
    result = (
        supabase.table("events")
        .select(
            "id, shared_event_id, name, preferred_start_date, preferred_start_time, organizer_id, coordinator_id"
        )
        .eq("id", event_id)
        .maybe_single()
        .execute()
    )
    return result.data if result is not None else None


def _format_when(start_date, start_time) -> str:
    """'12 Nov 2026, 2:00 PM' (or just the date, or '' when unknown)."""
    try:
        day = date.fromisoformat(str(start_date)) if start_date else None
    except ValueError:
        day = None
    if day is None:
        return ""
    text = f"{day.day} {day.strftime('%b %Y')}"
    try:
        moment = time.fromisoformat(str(start_time)) if start_time else None
    except ValueError:
        moment = None
    if moment is not None:
        hour = moment.hour % 12 or 12
        text += f", {hour}:{moment.strftime('%M')} {'AM' if moment.hour < 12 else 'PM'}"
    return text


def session_label(session: dict) -> str:
    """AC11: every attendee notification names the event AND the session --
    sessions of one request share the name, so the session is told apart by
    its start: '"Tech Talk" on 12 Nov 2026, 2:00 PM'."""
    name = f'"{session.get("name") or "Your event"}"'
    when = _format_when(session.get("preferred_start_date"), session.get("preferred_start_time"))
    return f"{name} on {when}" if when else name


def _attendee_ids(event_id: str) -> list[str]:
    result = (
        supabase.table("registrations")
        .select("attendee_id")
        .eq("event_id", event_id)
        .in_("status", ATTENDEE_STATUSES)
        .execute()
    )
    return [row["attendee_id"] for row in result.data or []]


def _waitlist_position(event_id: str, registration_id: str) -> int | None:
    """1 = next in line; same order the database promotes in
    (registered_at, then id -- public.withdraw_registration)."""
    result = (
        supabase.table("registrations")
        .select("id, registered_at")
        .eq("event_id", event_id)
        .eq("status", "waitlisted")
        .execute()
    )
    queue = sorted(result.data or [], key=lambda row: (str(row.get("registered_at") or ""), str(row["id"])))
    ids = [row["id"] for row in queue]
    return ids.index(registration_id) + 1 if registration_id in ids else None


def _notify_attendees(recipients, type_: str, message: str, session: dict, link: bool = True) -> None:
    notify(recipients, type_, message, *((ENTITY_ATTENDEE_EVENT, session["id"]) if link else (None, None)))


@_best_effort
def registration_recorded(registration: dict) -> None:
    """AC1 (a place was available) and AC2 (the session was full: waiting
    list, with their place in it)."""
    session = _session(registration.get("event_id"))
    if not session:
        return
    label = session_label(session)
    status = registration.get("status")
    if status == "confirmed":
        _notify_attendees(
            [registration.get("attendee_id")],
            REGISTRATION_CONFIRMED,
            f"Your registration for {label} is confirmed.",
            session,
        )
    elif status == "waitlisted":
        position = _waitlist_position(session["id"], registration.get("id"))
        place = f" You are number {position} on the waiting list." if position else ""
        _notify_attendees(
            [registration.get("attendee_id")],
            REGISTRATION_WAITLISTED,
            f"{label} is full, so you have been placed on the waiting list.{place}",
            session,
        )


@_best_effort
def registration_withdrawn(event_id: str, attendee_id: str, promoted_registration_id: str | None) -> None:
    """AC4: the attendee who withdrew is told it went through. AC3: if
    their place went to the first person on the waiting list, that person
    is told their registration is now confirmed."""
    session = _session(event_id)
    if not session:
        return
    label = session_label(session)
    _notify_attendees(
        [attendee_id],
        REGISTRATION_WITHDRAWN,
        f"You have withdrawn from {label}.",
        session,
    )
    if not promoted_registration_id:
        return
    result = (
        supabase.table("registrations")
        .select("attendee_id")
        .eq("id", promoted_registration_id)
        .maybe_single()
        .execute()
    )
    promoted = result.data if result is not None else None
    if promoted:
        _notify_attendees(
            [promoted.get("attendee_id")],
            REGISTRATION_PROMOTED,
            f"A place opened up: your registration for {label} is now confirmed.",
            session,
        )


@_best_effort
def event_cancelled(event_id: str) -> None:
    """AC8. No reason (it's internal planning information) and no link: a
    cancelled session's attendee page is no longer viewable."""
    session = _session(event_id)
    if session:
        _notify_attendees(
            _attendee_ids(event_id),
            EVENT_CANCELLED,
            f"{session_label(session)} has been cancelled.",
            session,
            link=False,
        )


@_best_effort
def event_reconfirmed(event_id: str) -> None:
    """AC5/AC7: called after a session is confirmed. Only a RE-confirmation
    can carry changes attendees haven't been told about (registration opens
    once a session is confirmed, so the first confirmation has nobody to
    tell). Tells them once, with a link to the event page, if a relevant
    detail changed since the previous confirmation; otherwise nothing."""
    session = _session(event_id)
    if not session:
        return
    confirmations = [
        _parse_timestamp(row["changed_at"]) for row in _status_history(event_id) if row.get("to_status") == "confirmed"
    ]
    if len(confirmations) < 2:
        return
    since = sorted(confirmations)[-2]
    if not (_details_changed_since(session, since) or _venue_changed_since(event_id, since)):
        return
    _notify_attendees(
        _attendee_ids(event_id),
        EVENT_DETAILS_UPDATED,
        f"The details of {session_label(session)} have been updated. View the event for the latest details.",
        session,
    )


def _parse_timestamp(value) -> datetime:
    moment = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def _status_history(event_id: str) -> list[dict]:
    result = (
        supabase.table("event_status_log")
        .select("to_status, changed_at")
        .eq("event_id", event_id)
        .order("changed_at")
        .execute()
    )
    return result.data or []


def _details_changed_since(session: dict, since: datetime) -> bool:
    """A name change anywhere in the request, or a date/time change on THIS
    session, made since `since`. Entries the organiser only ASKED for (a
    change request; app.events.event_log.entry_kind "requested") changed
    nothing -- only what the coordinator applied counts."""
    request_id = session.get("shared_event_id") or session["id"]
    result = (
        supabase.table("event_logs")
        .select("event_id, changes, changed_by, changed_at")
        .eq("shared_event_id", request_id)
        .execute()
    )
    for entry in result.data or []:
        if _parse_timestamp(entry["changed_at"]) <= since:
            continue
        by = entry.get("changed_by")
        if by and by == session.get("organizer_id") and by != session.get("coordinator_id"):
            continue
        fields = set(entry.get("changes") or {})
        if fields & ATTENDEE_RELEVANT_SHARED_FIELDS:
            return True
        if entry.get("event_id") == session["id"] and fields & ATTENDEE_RELEVANT_SESSION_FIELDS:
            return True
    return False


def _venue_key(booking: dict):
    # A permanently deleted venue loses venue_id but keeps its name (IS-61).
    return booking.get("venue_id") or booking.get("venue_name")


def _venue_changed_since(event_id: str, since: datetime) -> bool:
    """Whether the session's set of confirmed venues now differs from the
    set at `since`. The set then is replayed from venue_booking_status_log
    (every booking status change is written there); a booking cancelled and
    rebooked at the same venue is no change."""
    result = (
        supabase.table("venue_bookings")
        .select("id, venue_id, venue_name, status")
        .eq("event_id", event_id)
        .execute()
    )
    bookings = result.data or []
    if not bookings:
        return False
    now = {_venue_key(booking) for booking in bookings if booking.get("status") == "confirmed"}

    history = (
        supabase.table("venue_booking_status_log")
        .select("booking_id, to_status, changed_at")
        .in_("booking_id", [booking["id"] for booking in bookings])
        .order("changed_at")
        .execute()
    )
    status_then: dict[str, str] = {}
    for row in sorted(history.data or [], key=lambda row: _parse_timestamp(row["changed_at"])):
        if _parse_timestamp(row["changed_at"]) <= since:
            status_then[row["booking_id"]] = row.get("to_status")
    then = {_venue_key(booking) for booking in bookings if status_then.get(booking["id"]) == "confirmed"}
    return now != then


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
