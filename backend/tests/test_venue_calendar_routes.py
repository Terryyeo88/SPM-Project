"""
Tests for GET /venues/<venue_id>/calendar (app/venues/routes.py). Unit
level, same style as test_venues_routes.py: no real Supabase,
get_venue_calendar and load_venue (imported into the route module's
namespace) are monkeypatched so this file tests routing/authz/query-
param wiring only.
"""

from __future__ import annotations

import app.auth.context as context_module
import app.venues.routes as routes_module
from app.shared.errors import NotFoundError


def _mock_profile(monkeypatch, roles):
    monkeypatch.setattr(
        context_module,
        "_load_profile_with_roles",
        lambda user_id: ("Test User", "test@example.com", frozenset(roles)),
    )
    monkeypatch.setattr(context_module, "_get_last_active", lambda session_id: None)
    monkeypatch.setattr(context_module, "_touch_session_activity", lambda *a, **k: None)


_SAMPLE_VENUE = {"id": "venue-1", "name": "Grand Ballroom", "status": "available"}
_SAMPLE_CALENDAR = {
    "venue": {"id": "venue-1", "name": "Grand Ballroom", "operating_hours_start": None, "operating_hours_end": None},
    "range": {"start": "2026-12-01", "end": "2026-12-31"},
    "entries": [],
}


def test_route_succeeds_for_coordinator(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(routes_module, "load_venue", lambda venue_id: _SAMPLE_VENUE)
    monkeypatch.setattr(routes_module, "get_venue_calendar", lambda venue_id, start, end: _SAMPLE_CALENDAR)

    token = signing_key.make_token(sub="user-1")
    response = client.get(
        "/venues/venue-1/calendar?start=2026-12-01&end=2026-12-31",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.get_json() == _SAMPLE_CALENDAR


def test_route_succeeds_for_venue_staff(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["venue_staff"])
    monkeypatch.setattr(routes_module, "load_venue", lambda venue_id: _SAMPLE_VENUE)
    monkeypatch.setattr(routes_module, "get_venue_calendar", lambda venue_id, start, end: _SAMPLE_CALENDAR)

    token = signing_key.make_token(sub="user-1")
    response = client.get(
        "/venues/venue-1/calendar?start=2026-12-01&end=2026-12-31",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200


def test_route_denies_role_with_no_catalogue_access(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_organizer"])
    monkeypatch.setattr(routes_module, "load_venue", lambda venue_id: _SAMPLE_VENUE)
    monkeypatch.setattr(
        routes_module,
        "get_venue_calendar",
        lambda venue_id, start, end: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    token = signing_key.make_token(sub="user-1")
    response = client.get(
        "/venues/venue-1/calendar?start=2026-12-01&end=2026-12-31",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403


def test_route_requires_start_and_end(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["venue_staff"])
    monkeypatch.setattr(routes_module, "load_venue", lambda venue_id: _SAMPLE_VENUE)
    monkeypatch.setattr(
        routes_module,
        "get_venue_calendar",
        lambda venue_id, start, end: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    token = signing_key.make_token(sub="user-1")
    response = client.get("/venues/venue-1/calendar", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "validation_error"


def test_route_returns_404_for_missing_venue(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["venue_staff"])

    def missing(venue_id):
        raise NotFoundError("Venue not found.")

    monkeypatch.setattr(routes_module, "load_venue", missing)

    token = signing_key.make_token(sub="user-1")
    response = client.get(
        "/venues/does-not-exist/calendar?start=2026-12-01&end=2026-12-31",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 404


def test_route_rejects_unauthenticated(client):
    response = client.get("/venues/venue-1/calendar?start=2026-12-01&end=2026-12-31")
    assert response.status_code == 401
