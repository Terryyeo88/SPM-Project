"""
Tests for GET /venues and GET /venues/<venue_id> (app/venues/routes.py).

Unit-level, like test_events_routes.py: no real Supabase, no network.
venue_service functions (imported into this route module's namespace)
are monkeypatched so this file tests routing/authz wiring only.
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


_SAMPLE_VENUE = {
    "id": "venue-1",
    "name": "Grand Ballroom",
    "location": "Main Building, Level 3",
    "capacity": 300,
    "facilities": ["microphone", "projector", "screen", "wifi"],
    "accessibility_features": ["wheelchair_access", "lift_access"],
    "supported_layouts": ["theatre", "banquet", "networking"],
    "status": "available",
}


# -- GET /venues ------------------------------------------------------------


def test_list_route_succeeds_for_coordinator(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(routes_module, "list_venues", lambda status: [_SAMPLE_VENUE])

    token = signing_key.make_token(sub="user-1")
    response = client.get("/venues", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.get_json() == [_SAMPLE_VENUE]


def test_list_route_succeeds_for_venue_staff(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["venue_staff"])
    monkeypatch.setattr(routes_module, "list_venues", lambda status: [_SAMPLE_VENUE])

    token = signing_key.make_token(sub="user-1")
    response = client.get("/venues", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200


def test_list_route_denies_role_with_no_catalogue_access(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_organizer"])
    monkeypatch.setattr(
        routes_module, "list_venues", lambda status: (_ for _ in ()).throw(AssertionError("should not be called"))
    )

    token = signing_key.make_token(sub="user-1")
    response = client.get("/venues", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "not_authorised"


def test_list_route_passes_status_filter_through(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    seen = []

    def fake_list_venues(status):
        seen.append(status)
        return []

    monkeypatch.setattr(routes_module, "list_venues", fake_list_venues)

    token = signing_key.make_token(sub="user-1")
    response = client.get("/venues?status=available", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert seen == ["available"]


def test_list_route_rejects_invalid_status(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(
        routes_module, "list_venues", lambda status: (_ for _ in ()).throw(AssertionError("should not be called"))
    )

    token = signing_key.make_token(sub="user-1")
    response = client.get("/venues?status=on_fire", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "validation_error"


def test_list_route_rejects_unauthenticated(client):
    response = client.get("/venues")
    assert response.status_code == 401


# -- GET /venues/<venue_id> --------------------------------------------------


def test_get_route_succeeds_for_coordinator(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(routes_module, "load_venue", lambda venue_id: _SAMPLE_VENUE)

    token = signing_key.make_token(sub="user-1")
    response = client.get("/venues/venue-1", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.get_json() == _SAMPLE_VENUE


def test_get_route_denies_role_with_no_catalogue_access(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_organizer"])
    monkeypatch.setattr(routes_module, "load_venue", lambda venue_id: _SAMPLE_VENUE)

    token = signing_key.make_token(sub="user-1")
    response = client.get("/venues/venue-1", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403


def test_get_route_returns_404_for_missing_venue(client, signing_key, monkeypatch):
    """load_venue is free to raise NotFoundError itself (see
    app.authz.decorators' docstring on why that's the loader's job) --
    this must propagate through @require unchanged."""
    _mock_profile(monkeypatch, ["event_coordinator"])

    def missing(venue_id):
        raise NotFoundError("Venue not found.")

    monkeypatch.setattr(routes_module, "load_venue", missing)

    token = signing_key.make_token(sub="user-1")
    response = client.get("/venues/does-not-exist", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 404


def test_get_route_rejects_unauthenticated(client):
    response = client.get("/venues/venue-1")
    assert response.status_code == 401
