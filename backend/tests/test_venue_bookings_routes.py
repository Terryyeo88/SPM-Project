"""
Tests for the venue booking HTTP routes:
  POST/GET /events/<event_id>/venue-bookings    (app/events/routes.py)
  GET      /venues/bookings                     (app/venues/routes.py)
  GET      /venues/bookings/<booking_id>
  POST     /venues/bookings/<booking_id>/approve
  POST     /venues/bookings/<booking_id>/reject

Unit-level, like test_event_decisions.py / test_venues_routes.py: no real
Supabase. load_event/load_booking and the booking_service functions
imported into each route module's namespace are monkeypatched, so these
tests check routing + authz wiring only -- service-level behaviour is
covered by test_booking_service.py.
"""

from __future__ import annotations

import app.auth.context as context_module
import app.events.routes as events_routes
import app.venues.routes as venues_routes
from app.shared.errors import NotFoundError
from tests.factories import FakeEvent, FakeVenueBooking


def _mock_profile(monkeypatch, roles):
    monkeypatch.setattr(
        context_module,
        "_load_profile_with_roles",
        lambda user_id: ("Test User", "test@example.com", frozenset(roles)),
    )
    monkeypatch.setattr(context_module, "_get_last_active", lambda session_id: None)
    monkeypatch.setattr(context_module, "_touch_session_activity", lambda *a, **k: None)


def _auth(signing_key, user_id="user-1"):
    return {"Authorization": f"Bearer {signing_key.make_token(sub=user_id)}"}


# -- POST /events/<event_id>/venue-bookings --------------------------------


def test_create_booking_route_for_assigned_coordinator(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    event = FakeEvent(id="event-1", coordinator_id="user-1", status="approved")
    monkeypatch.setattr(events_routes, "load_event", lambda event_id: event)
    calls = []

    def fake_create(loaded_event, venue_id, requested_by):
        calls.append((loaded_event.id, venue_id, requested_by))
        return {"id": "booking-1", "status": "pending", "venue_id": venue_id}

    monkeypatch.setattr(events_routes, "create_booking_request", fake_create)

    response = client.post(
        "/events/event-1/venue-bookings", headers=_auth(signing_key), json={"venue_id": "venue-1"}
    )

    assert response.status_code == 201
    assert response.get_json()["status"] == "pending"
    assert calls == [("event-1", "venue-1", "user-1")]


def test_create_booking_route_404_for_coordinator_not_assigned(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    event = FakeEvent(id="event-1", coordinator_id="someone-else", status="approved")
    monkeypatch.setattr(events_routes, "load_event", lambda event_id: event)
    called = []
    monkeypatch.setattr(events_routes, "create_booking_request", lambda *a: called.append(a))

    response = client.post(
        "/events/event-1/venue-bookings", headers=_auth(signing_key), json={"venue_id": "venue-1"}
    )

    assert response.status_code == 404
    assert called == []


def test_create_booking_route_403_when_event_not_approved_or_planning(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    event = FakeEvent(id="event-1", coordinator_id="user-1", status="under_review")
    monkeypatch.setattr(events_routes, "load_event", lambda event_id: event)
    called = []
    monkeypatch.setattr(events_routes, "create_booking_request", lambda *a: called.append(a))

    response = client.post(
        "/events/event-1/venue-bookings", headers=_auth(signing_key), json={"venue_id": "venue-1"}
    )

    assert response.status_code == 403
    assert called == []


def test_create_booking_route_denies_organiser(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_organizer"])
    event = FakeEvent(id="event-1", organizer_id="user-1", coordinator_id="coord-1", status="approved")
    monkeypatch.setattr(events_routes, "load_event", lambda event_id: event)

    response = client.post(
        "/events/event-1/venue-bookings", headers=_auth(signing_key), json={"venue_id": "venue-1"}
    )

    assert response.status_code == 404


# -- GET /events/<event_id>/venue-bookings ---------------------------------


def test_list_bookings_for_event_route_for_assigned_coordinator(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    event = FakeEvent(id="event-1", coordinator_id="user-1", status="planning")
    monkeypatch.setattr(events_routes, "load_event", lambda event_id: event)
    bookings = [{"id": "booking-1", "status": "pending"}]
    monkeypatch.setattr(events_routes, "list_bookings_for_event", lambda event_id: bookings)

    response = client.get("/events/event-1/venue-bookings", headers=_auth(signing_key))

    assert response.status_code == 200
    assert response.get_json() == bookings


def test_list_bookings_for_event_route_404_for_unrelated_organiser(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_organizer"])
    event = FakeEvent(id="event-1", organizer_id="someone-else", status="planning")
    monkeypatch.setattr(events_routes, "load_event", lambda event_id: event)

    response = client.get("/events/event-1/venue-bookings", headers=_auth(signing_key))

    assert response.status_code == 404


# -- GET /venues/bookings ----------------------------------------------------


def test_list_venue_bookings_route_for_venue_staff(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["venue_staff"])
    bookings = [{"id": "booking-1", "status": "pending"}]
    seen = []

    def fake_list(user, status):
        seen.append((user.id, status))
        return bookings

    monkeypatch.setattr(venues_routes, "list_bookings", fake_list)

    response = client.get("/venues/bookings", headers=_auth(signing_key))

    assert response.status_code == 200
    assert response.get_json() == bookings
    assert seen == [("user-1", None)]


def test_list_venue_bookings_route_passes_status_filter_through(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["venue_staff"])
    seen = []
    monkeypatch.setattr(venues_routes, "list_bookings", lambda user, status: seen.append(status) or [])

    response = client.get("/venues/bookings?status=pending", headers=_auth(signing_key))

    assert response.status_code == 200
    assert seen == ["pending"]


def test_list_venue_bookings_route_rejects_invalid_status(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["venue_staff"])
    monkeypatch.setattr(
        venues_routes, "list_bookings", lambda *a: (_ for _ in ()).throw(AssertionError("should not be called"))
    )

    response = client.get("/venues/bookings?status=on_fire", headers=_auth(signing_key))

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "validation_error"


def test_list_venue_bookings_route_denies_attendee(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["attendee"])

    response = client.get("/venues/bookings", headers=_auth(signing_key))

    assert response.status_code == 403


def test_list_venue_bookings_route_rejects_unauthenticated(client):
    response = client.get("/venues/bookings")
    assert response.status_code == 401


# -- GET /venues/bookings/<booking_id> --------------------------------------
# Also proves the static "/bookings" route is matched ahead of the
# catalogue's dynamic "/<venue_id>" route (if it weren't, this would 404
# or 403 from the wrong rule entirely instead of resolving through
# load_booking/rule_venue_booking_view).


def test_get_venue_booking_route_for_requesting_coordinator(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    booking = FakeVenueBooking(id="booking-1", requested_by="user-1", status="rejected")
    monkeypatch.setattr(venues_routes, "load_booking", lambda booking_id: booking)

    response = client.get("/venues/bookings/booking-1", headers=_auth(signing_key))

    assert response.status_code == 200
    assert response.get_json()["id"] == "booking-1"


def test_get_venue_booking_route_404_for_unrelated_coordinator(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    booking = FakeVenueBooking(id="booking-1", requested_by="someone-else", status="pending")
    monkeypatch.setattr(venues_routes, "load_booking", lambda booking_id: booking)

    response = client.get("/venues/bookings/booking-1", headers=_auth(signing_key))

    assert response.status_code == 404


def test_get_venue_booking_route_404_for_missing_booking(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["venue_staff"])

    def missing(booking_id):
        raise NotFoundError("Venue booking not found.")

    monkeypatch.setattr(venues_routes, "load_booking", missing)

    response = client.get("/venues/bookings/does-not-exist", headers=_auth(signing_key))

    assert response.status_code == 404


def test_get_venue_booking_route_rejects_unauthenticated(client):
    response = client.get("/venues/bookings/booking-1")
    assert response.status_code == 401


# -- POST /venues/bookings/<booking_id>/approve -----------------------------


def test_approve_booking_route_for_venue_staff(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["venue_staff"])
    booking = FakeVenueBooking(id="booking-1", status="pending")
    monkeypatch.setattr(venues_routes, "load_booking", lambda booking_id: booking)
    calls = []

    def fake_confirm(booking_id, loaded, decided_by):
        calls.append((booking_id, decided_by))
        return {"id": booking_id, "status": "confirmed"}

    monkeypatch.setattr(venues_routes, "confirm_booking", fake_confirm)

    response = client.post("/venues/bookings/booking-1/approve", headers=_auth(signing_key))

    assert response.status_code == 200
    assert response.get_json()["status"] == "confirmed"
    assert calls == [("booking-1", "user-1")]


def test_approve_booking_route_403_when_not_pending(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["venue_staff"])
    booking = FakeVenueBooking(id="booking-1", status="confirmed")
    monkeypatch.setattr(venues_routes, "load_booking", lambda booking_id: booking)
    called = []
    monkeypatch.setattr(venues_routes, "confirm_booking", lambda *a: called.append(a))

    response = client.post("/venues/bookings/booking-1/approve", headers=_auth(signing_key))

    assert response.status_code == 403
    assert called == []


def test_approve_booking_route_denies_requesting_coordinator(client, signing_key, monkeypatch):
    """Deciding is venue_staff's action only -- even the requester gets
    404 (no qualifying relationship for THIS action)."""
    _mock_profile(monkeypatch, ["event_coordinator"])
    booking = FakeVenueBooking(id="booking-1", requested_by="user-1", status="pending")
    monkeypatch.setattr(venues_routes, "load_booking", lambda booking_id: booking)

    response = client.post("/venues/bookings/booking-1/approve", headers=_auth(signing_key))

    assert response.status_code == 404


# -- POST /venues/bookings/<booking_id>/reject ------------------------------


def test_reject_booking_route_passes_reason_to_service(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["venue_staff"])
    booking = FakeVenueBooking(id="booking-1", status="pending")
    monkeypatch.setattr(venues_routes, "load_booking", lambda booking_id: booking)
    calls = []

    def fake_reject(booking_id, loaded, decided_by, reason):
        calls.append((booking_id, decided_by, reason))
        return {"id": booking_id, "status": "rejected"}

    monkeypatch.setattr(venues_routes, "reject_booking", fake_reject)

    response = client.post(
        "/venues/bookings/booking-1/reject", headers=_auth(signing_key), json={"reason": "Too small"}
    )

    assert response.status_code == 200
    assert calls == [("booking-1", "user-1", "Too small")]


def test_reject_booking_route_403_when_not_pending(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["venue_staff"])
    booking = FakeVenueBooking(id="booking-1", status="rejected")
    monkeypatch.setattr(venues_routes, "load_booking", lambda booking_id: booking)
    called = []
    monkeypatch.setattr(venues_routes, "reject_booking", lambda *a: called.append(a))

    response = client.post(
        "/venues/bookings/booking-1/reject", headers=_auth(signing_key), json={"reason": "x"}
    )

    assert response.status_code == 403
    assert called == []
