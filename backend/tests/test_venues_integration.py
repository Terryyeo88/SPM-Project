"""Live Supabase integration tests for the venue catalogue (View Venue
Catalogue, Nawaz, Sprint 1). Unlike events, a venue has no owning user,
so these tests skip the auth.users/profiles dance entirely -- see
test_event_submission_integration.py for that pattern where it's
actually needed."""

from __future__ import annotations

import uuid

import pytest

from app.extensions import supabase
from app.shared.errors import NotFoundError
from app.venues.venue_service import get_venue, list_venues

pytestmark = pytest.mark.integration


def _insert_venue(**overrides) -> dict:
    payload = {
        "name": f"Integration Test Venue {uuid.uuid4()}",
        "location": "Test Wing",
        "capacity": 50,
        "facilities": ["wifi"],
        "accessibility_features": [],
        "supported_layouts": ["boardroom"],
        "status": "available",
    }
    payload.update(overrides)
    result = supabase.table("venues").insert(payload).execute()
    return result.data[0]


def test_list_venues_returns_seeded_and_created_rows():
    venue = _insert_venue()
    try:
        venues = list_venues()
        assert any(v["id"] == venue["id"] for v in venues)
    finally:
        supabase.table("venues").delete().eq("id", venue["id"]).execute()


def test_list_venues_filters_by_status():
    available = _insert_venue(status="available")
    maintenance = _insert_venue(status="maintenance")
    try:
        results = list_venues(status="maintenance")
        result_ids = {v["id"] for v in results}
        assert maintenance["id"] in result_ids
        assert available["id"] not in result_ids
    finally:
        supabase.table("venues").delete().eq("id", available["id"]).execute()
        supabase.table("venues").delete().eq("id", maintenance["id"]).execute()


def test_get_venue_returns_full_record():
    venue = _insert_venue(
        name=f"Full Record Venue {uuid.uuid4()}",
        capacity=120,
        facilities=["projector", "wifi"],
        accessibility_features=["wheelchair_access"],
        supported_layouts=["theatre", "classroom"],
    )
    try:
        fetched = get_venue(venue["id"])
        assert fetched["name"] == venue["name"]
        assert fetched["capacity"] == 120
        assert set(fetched["facilities"]) == {"projector", "wifi"}
        assert fetched["accessibility_features"] == ["wheelchair_access"]
        assert set(fetched["supported_layouts"]) == {"theatre", "classroom"}
    finally:
        supabase.table("venues").delete().eq("id", venue["id"]).execute()


def test_get_venue_raises_not_found_for_missing_id():
    with pytest.raises(NotFoundError):
        get_venue(str(uuid.uuid4()))
