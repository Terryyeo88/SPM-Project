"""
IS-25 Notification (Venue Staff): WHEN each notification is triggered. Each
hook runs only once its own change has been written, and hands its
arguments, untouched, to notification_service. Who is told what is
test_notification_venue_staff.py's job; the editing hooks (update and
approve a session change) sit next to their own tests in test_event_update.py
and test_event_change_requests.py.
"""

from __future__ import annotations

import pytest

import app.events.event_update as event_update
import app.events.routes as routes_module
import app.notifications.notification_service as notification_service
import app.venues.booking_service as booking_service
from app.shared.errors import ValidationError
from tests.test_booking_service import _event, _venue
from tests.test_booking_service import fake_db as booking_db  # noqa: F401 -- fixture
from tests.test_event_lifecycle import _auth, world  # noqa: F401 -- `world` is a fixture


@pytest.fixture
def news(monkeypatch):
    seen = []
    monkeypatch.setattr(
        notification_service, "venue_staff_booking_requested", lambda *a: seen.append(("request", a))
    )
    monkeypatch.setattr(
        notification_service, "venue_staff_event_news", lambda *a, **k: seen.append(("event", a, k))
    )
    return seen


def test_the_hooks_pass_their_arguments_to_the_notification_service(news, monkeypatch):
    monkeypatch.setattr(routes_module, "current_user", lambda: type("U", (), {"id": "coord-1"})())

    booking_service._notify_venue_staff({"id": "b1"}, "coord-1")
    booking_service._notify_venue_staff({"id": "b1"})
    event_update.notify_venue_staff_of_change("s1", {"preferred_start_date": "x", "name": "y"}, "coord-1")
    routes_module._notify_venue_staff_cancelled("s1", [{"id": "b1"}, {"id": "b2"}])

    assert news == [
        ("request", ({"id": "b1"}, "coord-1")),
        ("request", ({"id": "b1"}, None)),
        ("event", ("s1", "changed", {"preferred_start_date", "name"}, "coord-1"), {}),
        ("event", ("s1", "cancelled"), {"actor_id": "coord-1", "released_booking_ids": ["b1", "b2"]}),
    ]


# -- AC1: a booking request is created -------------------------------------------------------------


def test_requesting_a_venue_triggers_the_hook_with_the_new_booking(booking_db, news):  # noqa: F811
    booking_db.tables["venues"] = [_venue()]

    booking = booking_service.create_booking_request(_event(), "venue-1", "coord-1")

    assert news == [("request", (booking, "coord-1"))]
    assert booking["status"] == "pending"


def test_a_refused_booking_request_triggers_nothing(booking_db, news):  # noqa: F811
    with pytest.raises(ValidationError):
        booking_service.create_booking_request(_event(), "no-such-venue", "coord-1")

    assert news == []


# -- AC4: the session is cancelled (through the real route) ----------------------------------------


@pytest.fixture
def route_news(monkeypatch):
    seen = []
    monkeypatch.setattr(routes_module, "_notify_venue_staff_cancelled", lambda *a: seen.append(a))
    return seen


def test_cancelling_a_session_triggers_the_hook_with_the_bookings_it_released(
    client, signing_key, world, route_news  # noqa: F811
):
    world(["event_coordinator"], "planning")

    response = client.post("/events/event-1/cancel", headers=_auth(signing_key), json={"reason": "No venue"})

    assert response.status_code == 200
    assert route_news == [("event-1", [{"id": "booking-1"}])]


def test_a_refused_cancellation_triggers_nothing(client, signing_key, world, route_news):  # noqa: F811
    world(["event_coordinator"], "completed")

    response = client.post("/events/event-1/cancel", headers=_auth(signing_key), json={"reason": "No venue"})

    assert response.status_code == 403
    assert route_news == []
