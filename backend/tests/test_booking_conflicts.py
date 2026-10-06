"""Unit tests for booking conflict reporting (IS-16): which confirmed
bookings a booking clashes with, and the route that exposes it.

No database: the one query is monkeypatched. That the constraint and this
query agree against real Postgres is in test_booking_conflicts_integration.py.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import app.auth.context as context_module
import app.venues.booking_conflicts as conflicts_module
import app.venues.conflict_routes as conflict_routes
from app.shared.errors import NotFoundError


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime.fromisoformat(f"2026-11-02T{hour:02d}:{minute:02d}:00+08:00")


def _row(booking_id: str, start: str, end: str, event_name: str = "Some Event") -> dict:
    return {
        "id": booking_id,
        "event_id": f"event-{booking_id}",
        "booking_start": f"2026-11-02T{start}:00+08:00",
        "booking_end": f"2026-11-02T{end}:00+08:00",
        "events": {"name": event_name},
    }


def _confirmed(monkeypatch, rows: list[dict]) -> list[str]:
    """Stub the query; returns the venue ids it was asked about."""
    asked = []

    def fake(venue_id):
        asked.append(venue_id)
        return rows

    monkeypatch.setattr(conflicts_module, "_db_blocking_bookings", fake)
    return asked


# -- confirmed_clashes -----------------------------------------------------


def test_returns_every_clashing_booking_not_just_the_first(monkeypatch):
    # The gap this fills: _confirmed_overlap_exists stops at the first match.
    _confirmed(monkeypatch, [_row("a", "09:00", "11:00"), _row("b", "10:30", "12:00")])

    clashes = conflicts_module.confirmed_clashes("venue-1", _at(10), _at(11, 30))

    assert [c["id"] for c in clashes] == ["a", "b"]


def test_bookings_that_only_touch_do_not_clash(monkeypatch):
    # End-exclusive, like the constraint's '[)' range and _spans_overlap:
    # one booking may end at the minute the next begins.
    _confirmed(monkeypatch, [_row("before", "08:00", "10:00"), _row("after", "12:00", "14:00")])

    assert conflicts_module.confirmed_clashes("venue-1", _at(10), _at(12)) == []


def test_one_minute_of_overlap_is_a_clash(monkeypatch):
    _confirmed(monkeypatch, [_row("a", "08:00", "10:01")])

    assert [c["id"] for c in conflicts_module.confirmed_clashes("venue-1", _at(10), _at(12))] == ["a"]


def test_a_booking_never_clashes_with_itself(monkeypatch):
    _confirmed(monkeypatch, [_row("self", "10:00", "12:00"), _row("other", "11:00", "13:00")])

    clashes = conflicts_module.confirmed_clashes("venue-1", _at(10), _at(12), exclude_booking_id="self")

    assert [c["id"] for c in clashes] == ["other"]


def test_clashes_are_earliest_first(monkeypatch):
    _confirmed(monkeypatch, [_row("late", "11:00", "13:00"), _row("early", "09:00", "10:30")])

    assert [c["id"] for c in conflicts_module.confirmed_clashes("venue-1", _at(10), _at(12))] == ["early", "late"]


def test_each_clash_says_which_event_holds_the_venue(monkeypatch):
    _confirmed(monkeypatch, [_row("a", "09:00", "11:00", event_name="Orientation Day")])

    (clash,) = conflicts_module.confirmed_clashes("venue-1", _at(10), _at(12))

    assert clash == {
        "id": "a",
        "event_id": "event-a",
        "event_name": "Orientation Day",
        "booking_start": "2026-11-02T09:00:00+08:00",
        "booking_end": "2026-11-02T11:00:00+08:00",
    }


def test_no_confirmed_bookings_means_no_clashes(monkeypatch):
    _confirmed(monkeypatch, [])

    assert conflicts_module.confirmed_clashes("venue-1", _at(10), _at(12)) == []


def test_clashes_for_booking_uses_the_bookings_own_venue_and_period(monkeypatch):
    asked = _confirmed(monkeypatch, [_row("self", "10:00", "12:00"), _row("other", "11:30", "13:00")])
    booking = SimpleNamespace(
        id="self",
        venue_id="venue-7",
        booking_start="2026-11-02T10:00:00+08:00",
        booking_end="2026-11-02T12:00:00+08:00",
    )

    clashes = conflicts_module.clashes_for_booking(booking)

    assert asked == ["venue-7"]
    assert [c["id"] for c in clashes] == ["other"]


def test_query_reads_only_the_statuses_the_constraint_covers():
    # One definition of "holds the venue" for the app check, this report and
    # the constraint's WHERE clause: confirmed only. Pending blocks nothing;
    # rejected (or any later status) has released its period.
    assert conflicts_module._BLOCKING_STATUSES == ("confirmed",)


# -- GET /venues/bookings/<booking_id>/conflicts ---------------------------


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


def _booking(**overrides) -> SimpleNamespace:
    fields = {
        "id": "booking-1",
        "venue_id": "venue-1",
        "requested_by": "coord-1",
        "status": "pending",
        "booking_start": "2026-11-02T10:00:00+08:00",
        "booking_end": "2026-11-02T12:00:00+08:00",
    }
    return SimpleNamespace(**{**fields, **overrides})


def test_venue_staff_see_which_bookings_clash(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["venue_staff"])
    monkeypatch.setattr(conflict_routes, "load_booking", lambda booking_id: _booking())
    _confirmed(monkeypatch, [_row("a", "11:00", "13:00", event_name="Orientation Day")])

    response = client.get("/venues/bookings/booking-1/conflicts", headers=_auth(signing_key))

    assert response.status_code == 200
    assert [(c["id"], c["event_name"]) for c in response.get_json()] == [("a", "Orientation Day")]


def test_requesting_coordinator_may_see_the_clashes(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(conflict_routes, "load_booking", lambda booking_id: _booking(requested_by="user-1"))
    _confirmed(monkeypatch, [])

    response = client.get("/venues/bookings/booking-1/conflicts", headers=_auth(signing_key))

    assert response.status_code == 200
    assert response.get_json() == []


def test_other_coordinators_get_404(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(conflict_routes, "load_booking", lambda booking_id: _booking(requested_by="someone-else"))
    asked = _confirmed(monkeypatch, [])

    response = client.get("/venues/bookings/booking-1/conflicts", headers=_auth(signing_key))

    assert response.status_code == 404
    assert asked == []


def test_missing_booking_is_404(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["venue_staff"])

    def missing(booking_id):
        raise NotFoundError("Venue booking not found.")

    monkeypatch.setattr(conflict_routes, "load_booking", missing)

    response = client.get("/venues/bookings/nope/conflicts", headers=_auth(signing_key))

    assert response.status_code == 404
