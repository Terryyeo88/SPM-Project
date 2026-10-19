"""IS-9: "Changes or cancellation of one venue arrangement should not
automatically remove the other venue bookings."

POST /venues/bookings/<booking_id>/cancel (app.venues.routes) ->
app.venues.booking_service.cancel_booking, gated by venue_booking.cancel
(rule_venue_booking_cancel). Unit-level: the shared FakeSupabase stands in
for the booking service and the route's event lookup, so these run the real
route, loader, authz rule and service together.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

import app.auth.context as context_module
import app.venues.booking_service as booking_service
import app.venues.routes as venues_routes
from app.authz import actions
from app.authz.policy import authorise, can
from app.shared.errors import AuthorisationError, NotFoundError, ValidationError
from app.venues.booking_service import cancel_booking, list_bookings_for_event
from tests.factories import make_user
from tests.fake_supabase import FakeSupabase

COORDINATOR = "coord-1"
DAY = (date.today() + timedelta(days=30)).isoformat()


def _booking(booking_id, *, event_id="session-1", status="confirmed", venue_id=None, requested_by=COORDINATOR):
    return {
        "id": booking_id,
        "event_id": event_id,
        "venue_id": venue_id or f"venue-{booking_id}",
        "status": status,
        "requested_by": requested_by,
        "setup_minutes": 30,
        "turnaround_minutes": 30,
        "booking_start": f"{DAY}T08:30:00+08:00",
        "booking_end": f"{DAY}T17:30:00+08:00",
    }


@pytest.fixture
def fake(monkeypatch):
    db = FakeSupabase(
        [
            {"id": "session-1", "coordinator_id": COORDINATOR, "status": "planning"},
            {"id": "session-2", "coordinator_id": COORDINATOR, "status": "planning"},
        ]
    )
    db.tables["venue_bookings"] = [
        _booking("main-hall"),
        _booking("breakout-room"),
        _booking("overflow-room", status="pending"),
        _booking("other-session", event_id="session-2"),
    ]
    monkeypatch.setattr(booking_service, "supabase", db)
    monkeypatch.setattr(venues_routes, "supabase", db)
    return db


def _row(fake, booking_id):
    return next(row for row in fake.tables["venue_bookings"] if row["id"] == booking_id)


def _ns(fake, booking_id):
    return SimpleNamespace(**dict(_row(fake, booking_id)))


def _status_log(fake):
    return fake.tables.get("venue_booking_status_log", [])


def _mock_profile(monkeypatch, roles):
    monkeypatch.setattr(
        context_module, "_load_profile_with_roles", lambda user_id: ("Test User", "t@example.com", frozenset(roles))
    )
    monkeypatch.setattr(context_module, "_get_last_active", lambda session_id: None)
    monkeypatch.setattr(context_module, "_touch_session_activity", lambda *a, **k: None)


def _auth(signing_key, user_id=COORDINATOR):
    return {"Authorization": f"Bearer {signing_key.make_token(sub=user_id)}"}


# -- the service: one booking changes, the others don't ----------------------


def test_cancelling_one_booking_leaves_every_other_booking_untouched(fake):
    others_before = [dict(row) for row in fake.tables["venue_bookings"] if row["id"] != "main-hall"]

    cancelled = cancel_booking("main-hall", _ns(fake, "main-hall"), COORDINATOR, "Moved to the auditorium.")

    assert cancelled["status"] == "cancelled"
    assert _row(fake, "main-hall")["status"] == "cancelled"
    assert [row for row in fake.tables["venue_bookings"] if row["id"] != "main-hall"] == others_before


def test_only_the_cancelled_booking_is_written(fake):
    cancel_booking("overflow-room", _ns(fake, "overflow-room"), COORDINATOR, "Not needed.")

    writes = [call for call in fake.calls if call["table"] == "venue_bookings" and call["op"] == "update"]
    assert len(writes) == 1
    assert ("eq", "id", "overflow-room") in writes[0]["filters"]
    assert writes[0]["payload"] == {"status": "cancelled"}


def test_the_event_status_is_not_changed_by_cancelling_a_booking(fake):
    cancel_booking("main-hall", _ns(fake, "main-hall"), COORDINATOR, "Moved.")

    assert fake.get("session-1")["status"] == "planning"
    assert [call for call in fake.calls if call["table"] == "events" and call["op"] == "update"] == []


def test_a_cancellation_is_recorded_with_who_when_and_why(fake):
    cancel_booking("main-hall", _ns(fake, "main-hall"), COORDINATOR, "  Moved to the auditorium.  ")

    assert len(_status_log(fake)) == 1
    entry = _status_log(fake)[0]
    assert entry["booking_id"] == "main-hall"
    assert entry["from_status"] == "confirmed"
    assert entry["to_status"] == "cancelled"
    assert entry["changed_by"] == COORDINATOR
    assert entry["reason"] == "Moved to the auditorium."


@pytest.mark.parametrize("reason", [None, "", "   ", 42])
def test_a_reason_is_required_and_nothing_is_written_without_one(fake, reason):
    before = [dict(row) for row in fake.tables["venue_bookings"]]

    with pytest.raises(ValidationError, match="reason is required"):
        cancel_booking("main-hall", _ns(fake, "main-hall"), COORDINATOR, reason)

    assert fake.tables["venue_bookings"] == before
    assert _status_log(fake) == []


def test_a_cancel_racing_a_status_change_is_refused_not_overwritten(fake):
    """The coordinator loaded a pending booking, then Venue Staff rejected it:
    the cancel is conditioned on "pending" and must not overwrite "rejected"."""
    stale = _ns(fake, "overflow-room")
    _row(fake, "overflow-room")["status"] = "rejected"

    with pytest.raises(ValidationError, match="changed while you were cancelling"):
        cancel_booking("overflow-room", stale, COORDINATOR, "Not needed.")

    assert _row(fake, "overflow-room")["status"] == "rejected"
    assert _status_log(fake) == []


def test_the_coordinator_can_read_why_a_booking_was_cancelled(fake):
    cancel_booking("main-hall", _ns(fake, "main-hall"), COORDINATOR, "Moved to the auditorium.")
    fake.tables["venue_booking_status_log"][0]["profiles"] = {"name": "Casey Coordinator"}

    bookings = {row["id"]: row for row in list_bookings_for_event("session-1")}

    assert bookings["main-hall"]["cancellation"]["reason"] == "Moved to the auditorium."
    assert bookings["main-hall"]["cancellation"]["cancelled_by"] == "Casey Coordinator"
    assert "cancellation" not in bookings["breakout-room"]
    assert {row["status"] for row in bookings.values()} == {"cancelled", "confirmed", "pending"}


# -- authz: venue_booking.cancel ----------------------------------------------


def _resource(status="confirmed", event_status="planning", event_coordinator_id=COORDINATOR):
    return SimpleNamespace(
        id="booking-1",
        requested_by="someone-who-requested-it",
        status=status,
        event_status=event_status,
        event_coordinator_id=event_coordinator_id,
    )


@pytest.mark.parametrize("status", ["pending", "confirmed"])
@pytest.mark.parametrize("event_status", ["planning", "safety_review", "confirmed"])
def test_the_assigned_coordinator_can_cancel_an_active_booking(status, event_status):
    user = make_user(["event_coordinator"], user_id=COORDINATOR)
    assert can(user, actions.VENUE_BOOKING_CANCEL, _resource(status, event_status)) is True


def test_the_current_coordinator_cancels_even_a_booking_their_predecessor_requested():
    """Reassignment by the Lead: the event's coordinator now, not the
    booking's requester, decides about its arrangements."""
    new = make_user(["event_coordinator"], user_id="coord-2")
    old = make_user(["event_coordinator"], user_id="someone-who-requested-it")
    resource = _resource(event_coordinator_id="coord-2")

    assert can(new, actions.VENUE_BOOKING_CANCEL, resource) is True
    with pytest.raises(NotFoundError):
        authorise(old, actions.VENUE_BOOKING_CANCEL, resource)


@pytest.mark.parametrize("status", ["rejected", "cancelled"])
def test_a_decided_or_cancelled_booking_cannot_be_cancelled_again(status):
    user = make_user(["event_coordinator"], user_id=COORDINATOR)
    with pytest.raises(AuthorisationError, match=f"already {status}"):
        authorise(user, actions.VENUE_BOOKING_CANCEL, _resource(status=status))


@pytest.mark.parametrize("event_status", ["completed", "cancelled"])
def test_a_finished_events_bookings_cannot_be_cancelled(event_status):
    user = make_user(["event_coordinator"], user_id=COORDINATOR)
    with pytest.raises(AuthorisationError, match=f"event is {event_status}"):
        authorise(user, actions.VENUE_BOOKING_CANCEL, _resource(event_status=event_status))


@pytest.mark.parametrize(
    "roles,user_id",
    [
        (["event_coordinator"], "another-coordinator"),
        (["venue_staff"], COORDINATOR),
        (["event_organizer"], "org-1"),
        (["event_coordinator_lead"], "lead-1"),
    ],
)
def test_nobody_else_can_cancel_a_booking(roles, user_id):
    user = make_user(roles, user_id=user_id)
    with pytest.raises(NotFoundError):
        authorise(user, actions.VENUE_BOOKING_CANCEL, _resource())


# -- the route ------------------------------------------------------------------


def test_the_route_cancels_one_booking_and_leaves_the_rest(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch, ["event_coordinator"])

    response = client.post(
        "/venues/bookings/breakout-room/cancel", headers=_auth(signing_key), json={"reason": "Room no longer needed."}
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["status"] == "cancelled"
    statuses = {row["id"]: row["status"] for row in fake.tables["venue_bookings"]}
    assert statuses == {
        "main-hall": "confirmed",
        "breakout-room": "cancelled",
        "overflow-room": "pending",
        "other-session": "confirmed",
    }


def test_the_route_needs_a_reason(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch, ["event_coordinator"])

    response = client.post("/venues/bookings/main-hall/cancel", headers=_auth(signing_key), json={})

    assert response.status_code == 400
    assert _row(fake, "main-hall")["status"] == "confirmed"


def test_the_route_refuses_another_coordinator_with_a_404(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch, ["event_coordinator"])

    response = client.post(
        "/venues/bookings/main-hall/cancel", headers=_auth(signing_key, "another-coordinator"), json={"reason": "x"}
    )

    assert response.status_code == 404
    assert _row(fake, "main-hall")["status"] == "confirmed"


def test_the_route_refuses_a_completed_event_with_the_reason(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch, ["event_coordinator"])
    fake.get("session-1")["status"] = "completed"

    response = client.post("/venues/bookings/main-hall/cancel", headers=_auth(signing_key), json={"reason": "x"})

    assert response.status_code == 403
    assert "completed" in response.get_json()["error"]["message"]
    assert _row(fake, "main-hall")["status"] == "confirmed"


def test_the_route_404s_for_an_unknown_booking(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch, ["event_coordinator"])

    response = client.post("/venues/bookings/nope/cancel", headers=_auth(signing_key), json={"reason": "x"})

    assert response.status_code == 404
