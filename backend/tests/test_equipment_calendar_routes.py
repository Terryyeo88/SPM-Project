"""
Tests for GET /equipment/<equipment_id>/calendar
(app/equipment/calendar_routes.py, IS-47). Same style as test_venue_calendar_routes.py: no real Supabase.
get_equipment (imported into the route module's namespace, and what the
route's load_unit loader calls) is monkeypatched; the calendar service
itself is the real one, so these also cover the range filter end to end.
"""

from __future__ import annotations

import app.auth.context as context_module
import app.equipment.calendar_routes as routes_module
from app.shared.errors import NotFoundError


def _mock_profile(monkeypatch, roles):
    monkeypatch.setattr(
        context_module,
        "_load_profile_with_roles",
        lambda user_id: ("Test User", "test@example.com", frozenset(roles)),
    )
    monkeypatch.setattr(context_module, "_get_last_active", lambda session_id: None)
    monkeypatch.setattr(context_module, "_touch_session_activity", lambda *a, **k: None)


_UNIT = {
    "id": "unit-1",
    "asset_tag": "PRJ-001",
    "status": "available",
    "notes": None,
    "equipment_type_id": "type-1",
    "type": "projector",
    "occupancy": [
        {
            "reservation_id": "res-1",
            "reserved_start": "2026-12-10T01:00:00+00:00",
            "reserved_end": "2026-12-10T05:00:00+00:00",
            "request_id": "req-1",
            "event_id": "event-1",
            "event_name": "Annual Tech Symposium",
        }
    ],
}


def _missing(equipment_id):
    raise NotFoundError("Equipment not found.")


def _get(client, signing_key, path="/equipment/unit-1/calendar?start=2026-12-01&end=2026-12-31"):
    token = signing_key.make_token(sub="user-1")
    return client.get(path, headers={"Authorization": f"Bearer {token}"})


def test_route_succeeds_for_technical_staff(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["technical_support_staff"])
    monkeypatch.setattr(routes_module, "get_equipment", lambda equipment_id: _UNIT)

    response = _get(client, signing_key)

    assert response.status_code == 200
    assert response.get_json() == {
        "equipment": {
            "id": "unit-1",
            "asset_tag": "PRJ-001",
            "type": "projector",
            "notes": None,
            "status": "available",
        },
        "range": {"start": "2026-12-01", "end": "2026-12-31"},
        "entries": [
            {
                "type": "reservation",
                "state": "reserved",
                "start": "2026-12-10T01:00:00+00:00",
                "end": "2026-12-10T05:00:00+00:00",
                "event_id": "event-1",
                "event_name": "Annual Tech Symposium",
            }
        ],
    }


def test_route_passes_the_loaded_unit_id(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["technical_support_staff"])
    asked = []
    monkeypatch.setattr(routes_module, "get_equipment", lambda equipment_id: asked.append(equipment_id) or _UNIT)

    _get(client, signing_key)

    assert asked == ["unit-1"]


def test_route_is_404_for_every_other_role(client, signing_key, monkeypatch):
    monkeypatch.setattr(routes_module, "get_equipment", lambda equipment_id: _UNIT)
    for role in ("event_coordinator", "event_coordinator_lead", "event_organizer", "venue_staff", "attendee"):
        _mock_profile(monkeypatch, [role])

        response = _get(client, signing_key)

        assert response.status_code == 404, role


def test_route_returns_404_for_an_unknown_unit(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["technical_support_staff"])
    monkeypatch.setattr(routes_module, "get_equipment", _missing)

    response = _get(client, signing_key, "/equipment/no-such-unit/calendar?start=2026-12-01&end=2026-12-31")

    assert response.status_code == 404


def test_a_hidden_unit_and_an_unknown_unit_get_the_same_response(client, signing_key, monkeypatch):
    """AC6: a non-staff caller gets exactly what an unknown unit gives --
    same status AND same body, so the response can't tell them apart."""
    _mock_profile(monkeypatch, ["technical_support_staff"])
    monkeypatch.setattr(routes_module, "get_equipment", _missing)
    unknown = _get(client, signing_key)

    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(routes_module, "get_equipment", lambda equipment_id: _UNIT)
    hidden = _get(client, signing_key)

    assert (hidden.status_code, hidden.get_json()) == (unknown.status_code, unknown.get_json())


def test_route_requires_start_and_end(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["technical_support_staff"])
    monkeypatch.setattr(routes_module, "get_equipment", lambda equipment_id: _UNIT)

    for query in ("", "?start=2026-12-01", "?end=2026-12-31"):
        response = _get(client, signing_key, f"/equipment/unit-1/calendar{query}")

        assert response.status_code == 400, query
        assert response.get_json()["error"]["code"] == "validation_error"


def test_route_rejects_malformed_dates_and_end_before_start(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["technical_support_staff"])
    monkeypatch.setattr(routes_module, "get_equipment", lambda equipment_id: _UNIT)

    for query in ("start=2026-12-01&end=nope", "start=2026-12-31&end=2026-12-01"):
        response = _get(client, signing_key, f"/equipment/unit-1/calendar?{query}")

        assert response.status_code == 400, query
        assert response.get_json()["error"]["code"] == "validation_error"


def test_route_rejects_unauthenticated(client):
    response = client.get("/equipment/unit-1/calendar?start=2026-12-01&end=2026-12-31")
    assert response.status_code == 401
