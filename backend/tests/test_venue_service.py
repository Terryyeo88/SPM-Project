"""
Unit tests for app.venues.venue_service -- the venue-settings write path
added for "Request Venue Booking with Setup and Turnaround Time" (Josiah,
Sprint 3). list_venues/get_venue are covered by test_venues_integration.py
(real DB) and test_venues_routes.py (route-level mocking); this file is
new specifically for update_venue_settings, this module's first write path.
"""

from __future__ import annotations

import pytest
from postgrest.exceptions import APIError

import app.venues.venue_service as service_module
from app.shared.errors import NotFoundError, ValidationError


class _FakeQuery:
    def __init__(self, db, table):
        self.db, self.table, self.filters = db, table, []
        self.op, self.payload = None, None

    def select(self, *_):
        return self

    def update(self, payload):
        self.op, self.payload = "update", payload
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def maybe_single(self):
        return self

    def execute(self):
        if self.db.raise_on_update and self.op == "update":
            raise self.db.raise_on_update
        rows = self.db.tables.setdefault(self.table, [])
        matched = [row for row in rows if all(row.get(c) == v for c, v in self.filters)]
        if self.op == "update":
            for row in matched:
                row.update(self.payload)
        data = [dict(row) for row in matched]
        return type("Result", (), {"data": data})()


class _FakeSupabase:
    def __init__(self):
        self.tables = {}
        self.raise_on_update = None

    def table(self, name):
        self.tables.setdefault(name, [])
        return _FakeQuery(self, name)


@pytest.fixture
def fake_db(monkeypatch):
    db = _FakeSupabase()
    monkeypatch.setattr(service_module, "supabase", db)
    return db


def _venue(venue_id="venue-1", **overrides):
    row = {"id": venue_id, "setup_minutes": 30, "turnaround_minutes": 30, "tentative_hold_minutes": 1440}
    row.update(overrides)
    return row


# -- _settings_from / update_venue_settings: validation ------------------


def test_update_venue_settings_rejects_a_non_object_body(fake_db):
    fake_db.tables["venues"] = [_venue()]
    with pytest.raises(ValidationError):
        service_module.update_venue_settings("venue-1", ["not", "a", "dict"])


def test_update_venue_settings_rejects_an_unknown_field(fake_db):
    fake_db.tables["venues"] = [_venue()]
    with pytest.raises(ValidationError, match="Unknown venue setting fields"):
        service_module.update_venue_settings("venue-1", {"capacity": 500})


def test_update_venue_settings_rejects_an_empty_body(fake_db):
    fake_db.tables["venues"] = [_venue()]
    with pytest.raises(ValidationError, match="Provide at least one"):
        service_module.update_venue_settings("venue-1", {})


@pytest.mark.parametrize("value", [0, -5, 1.5, "30", True, None])
def test_update_venue_settings_rejects_a_non_positive_int(fake_db, value):
    fake_db.tables["venues"] = [_venue()]
    with pytest.raises(ValidationError):
        service_module.update_venue_settings("venue-1", {"setup_minutes": value})


# -- update_venue_settings: happy path ------------------------------------


def test_update_venue_settings_updates_only_the_fields_given(fake_db):
    fake_db.tables["venues"] = [_venue(setup_minutes=30, turnaround_minutes=30, tentative_hold_minutes=1440)]

    result = service_module.update_venue_settings("venue-1", {"tentative_hold_minutes": 90})

    assert result["tentative_hold_minutes"] == 90
    assert result["setup_minutes"] == 30  # untouched
    assert result["turnaround_minutes"] == 30  # untouched


def test_update_venue_settings_can_update_all_three_fields_at_once(fake_db):
    fake_db.tables["venues"] = [_venue()]

    result = service_module.update_venue_settings(
        "venue-1", {"setup_minutes": 15, "turnaround_minutes": 45, "tentative_hold_minutes": 60}
    )

    assert result["setup_minutes"] == 15
    assert result["turnaround_minutes"] == 45
    assert result["tentative_hold_minutes"] == 60


def test_update_venue_settings_raises_not_found_for_an_unknown_venue(fake_db):
    with pytest.raises(NotFoundError):
        service_module.update_venue_settings("does-not-exist", {"setup_minutes": 15})


def test_update_venue_settings_translates_a_check_violation(fake_db):
    fake_db.tables["venues"] = [_venue()]
    fake_db.raise_on_update = APIError({"message": "check violation", "code": "23514", "hint": None, "details": None})

    with pytest.raises(ValidationError):
        service_module.update_venue_settings("venue-1", {"setup_minutes": 15})


def test_update_venue_settings_reraises_an_unrelated_database_error(fake_db):
    fake_db.tables["venues"] = [_venue()]
    fake_db.raise_on_update = APIError({"message": "fk violation", "code": "23503", "hint": None, "details": None})

    with pytest.raises(APIError):
        service_module.update_venue_settings("venue-1", {"setup_minutes": 15})
