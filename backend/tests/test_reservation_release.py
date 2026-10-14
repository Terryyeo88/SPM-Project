"""
Unit tests for app.equipment.reservation_release -- Release Equipment on
Cancel (Justin, Sprint 3).

A small fake scoped to the three tables the release touches, same "fake
only what THIS module needs" precedent as test_equipment_service.py. The
real cascade/exclusion behaviour is proven in
test_reservation_release_integration.py; this file checks WHICH rows go.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.equipment.reservation_release as release_module


class _FakeTable:
    def __init__(self, rows):
        self._rows = rows
        self._eq = []
        self._in = []
        self._delete = False

    def select(self, *_a, **_k):
        return self

    def delete(self):
        self._delete = True
        return self

    def eq(self, column, value):
        self._eq.append((column, value))
        return self

    def in_(self, column, values):
        self._in.append((column, tuple(values)))
        return self

    def execute(self):
        matched = [
            row
            for row in self._rows
            if all(row.get(c) == v for c, v in self._eq) and all(row.get(c) in vs for c, vs in self._in)
        ]
        if self._delete:
            for row in matched:
                self._rows.remove(row)
        return SimpleNamespace(data=[dict(row) for row in matched])


class _FakeSupabase:
    def __init__(self, **tables):
        self.tables = {
            name: list(tables.get(name, []))
            for name in ("equipment_requests", "equipment_request_items", "equipment_reservations")
        }

    def table(self, name):
        return _FakeTable(self.tables[name])


@pytest.fixture
def db(monkeypatch):
    def _install(**tables):
        fake = _FakeSupabase(**tables)
        monkeypatch.setattr(release_module, "supabase", fake)
        return fake

    return _install


def _world(db):
    """Event 1 holds 3 units over two requests (one confirmed with two
    lines, one rejected with none); event 2 holds 1 unit."""
    return db(
        equipment_requests=[
            {"id": "req-1", "event_id": "event-1"},
            {"id": "req-2", "event_id": "event-1"},
            {"id": "req-3", "event_id": "event-2"},
        ],
        equipment_request_items=[
            {"id": "item-1a", "request_id": "req-1"},
            {"id": "item-1b", "request_id": "req-1"},
            {"id": "item-2", "request_id": "req-2"},
            {"id": "item-3", "request_id": "req-3"},
        ],
        equipment_reservations=[
            {"id": "res-prj", "request_item_id": "item-1a", "equipment_id": "PRJ-001"},
            {"id": "res-mic1", "request_item_id": "item-1b", "equipment_id": "MIC-001"},
            {"id": "res-mic2", "request_item_id": "item-1b", "equipment_id": "MIC-002"},
            {"id": "res-other", "request_item_id": "item-3", "equipment_id": "PRJ-002"},
        ],
    )


def test_cancelling_releases_every_unit_reserved_for_the_event(db):
    fake = _world(db)

    assert release_module.release_event_equipment("event-1") == 3
    assert [r["id"] for r in fake.tables["equipment_reservations"]] == ["res-other"]


def test_other_events_reservations_are_left_alone(db):
    fake = _world(db)

    release_module.release_event_equipment("event-1")

    assert fake.tables["equipment_reservations"] == [
        {"id": "res-other", "request_item_id": "item-3", "equipment_id": "PRJ-002"}
    ]


def test_requests_and_their_lines_are_kept(db):
    # The event page still shows what was asked for, as "Released".
    fake = _world(db)

    release_module.release_event_equipment("event-1")

    assert len(fake.tables["equipment_requests"]) == 3
    assert len(fake.tables["equipment_request_items"]) == 4


def test_event_with_no_equipment_requests_releases_nothing(db):
    _world(db)
    assert release_module.release_event_equipment("event-9") == 0


def test_event_whose_requests_have_no_lines_releases_nothing(db):
    db(equipment_requests=[{"id": "req-1", "event_id": "event-1"}])
    assert release_module.release_event_equipment("event-1") == 0


def test_releasing_twice_is_harmless(db):
    fake = _world(db)

    release_module.release_event_equipment("event-1")
    assert release_module.release_event_equipment("event-1") == 0
    assert [r["id"] for r in fake.tables["equipment_reservations"]] == ["res-other"]
