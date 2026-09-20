"""Tests for submitting event requests for review."""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

import app.auth.context as context_module
import app.events.routes as routes_module
from app.events.event_service import validate_event_payload
from app.shared.errors import ValidationError


def _mock_profile(monkeypatch, roles):
    monkeypatch.setattr(
        context_module,
        "_load_profile_with_roles",
        lambda user_id: ("Test User", "test@example.com", frozenset(roles)),
    )
    monkeypatch.setattr(context_module, "_get_last_active", lambda session_id: None)
    monkeypatch.setattr(context_module, "_touch_session_activity", lambda *a, **k: None)


def _complete_draft():
    return SimpleNamespace(
        id="event-1",
        organizer_id="user-1",
        coordinator_id=None,
        status="draft",
        name="Community Conference",
        description="A community conference.",
        purpose="Knowledge sharing.",
        preferred_start_date="2026-11-10",
        preferred_end_date="2026-11-10",
        preferred_start_time=None,
        preferred_end_time=None,
        expected_attendance=100,
        accessibility_needs=[{"item": "wheelchair_access", "quantity": 2}],
        room_layout="theatre",
        equipment_needed={"equipment": [{"item": "projector", "quantity": 1}]},
        registration_needs=True,
        special_requests="Near the main entrance.",
    )


def _complete_payload():
    """Return a valid request body that edge-case tests can modify.

    preferred_end_date defaults to the SAME day as preferred_start_date --
    a single-day event -- so tests that only care about time-of-day
    ordering (and don't touch the dates) keep exercising the ordinary
    same-day comparison rather than the combined-datetime, multi-day one.
    """
    start_date = (date.today() + timedelta(days=1)).isoformat()
    return {
        "name": "Community Conference",
        "description": "A community conference.",
        "purpose": "Knowledge sharing.",
        "preferred_start_date": start_date,
        "preferred_end_date": start_date,
        "preferred_start_time": "09:00",
        "preferred_end_time": "17:00",
        "expected_attendance": 100,
        "accessibility_needs": [{"item": "wheelchair_access"}],
        "room_layout": "theatre",
        "equipment": [{"item": "projector", "quantity": 1}],
        "registration_needs": True,
        "special_requests": "Near the main entrance.",
    }


def test_submit_event_route_sets_submitted_for_organizer(client, signing_key, monkeypatch):
    """Verify an authenticated organizer can submit a complete draft."""
    _mock_profile(monkeypatch, ["event_organizer"])
    event = _complete_draft()
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: event)

    calls = []

    def fake_submit(event_id, loaded_event):
        calls.append((event_id, loaded_event))
        return {"id": event_id, "status": "submitted"}

    monkeypatch.setattr(routes_module, "submit_event_request", fake_submit)

    token = signing_key.make_token(sub="user-1")
    response = client.post(
        "/events/event-1/submit",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )

    assert response.status_code == 200
    assert response.get_json() == {"id": "event-1", "status": "submitted"}
    assert calls == [("event-1", event)]


def test_submit_event_route_rejects_incomplete_draft(client, signing_key, monkeypatch):
    """Verify submission is blocked when a required field is blank."""
    # an HTTP/integration-level test
    # Going through Flask client with POST /events/<event_id>/submit
    # Exercises the whole request pipeline: auth, routing, loading the event,
    # calling validation, and error-to-JSON serialization.
    _mock_profile(monkeypatch, ["event_organizer"])
    event = _complete_draft()
    event.purpose = ""
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: event)

    token = signing_key.make_token(sub="user-1")
    response = client.post(
        "/events/event-1/submit",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize(
    "missing_field",
    [
        "name",
        "description",
        "purpose",
        "preferred_start_date",
        "preferred_end_date",
        "expected_attendance",
        "room_layout",
        "registration_needs",
    ],
)
def test_submission_rejects_each_missing_required_field(missing_field):
    """Verify every required event field prevents submission when missing."""
    # a unit-level test
    payload = _complete_payload()
    # 7 test cases each removing (popping) a different key from the payload dict
    # Checks only that validation logic itself raises
    payload.pop(missing_field)

    with pytest.raises(ValidationError):
        validate_event_payload(payload, for_submission=True)


@pytest.mark.parametrize(
    "event_date",
    [date.today().isoformat(), (date.today() - timedelta(days=1)).isoformat()],
)
def test_submission_rejects_today_and_past_preferred_start_dates(event_date):
    """Verify an event cannot be submitted for today or the previous day."""
    payload = _complete_payload()
    payload["preferred_start_date"] = event_date

    with pytest.raises(ValidationError, match="after today"):
        validate_event_payload(payload, for_submission=True)


def test_submission_accepts_tomorrows_preferred_start_date():
    """Verify the nearest valid preferred start date, tomorrow, is accepted."""
    payload = _complete_payload()
    payload["preferred_start_date"] = (date.today() + timedelta(days=1)).isoformat()

    validate_event_payload(payload, for_submission=True)


def test_submission_rejects_end_date_before_start_date():
    """preferred_end_date, when given, must not be earlier than
    preferred_start_date -- an event can't finish before it starts."""
    payload = _complete_payload()
    payload["preferred_start_date"] = "2026-11-10"
    payload["preferred_end_date"] = "2026-11-09"

    with pytest.raises(ValidationError, match="preferred_end_date"):
        validate_event_payload(payload, for_submission=True)


def test_submission_accepts_end_date_equal_to_start_date():
    """The single-day edge case where the end date equals the start date
    is valid."""
    payload = _complete_payload()
    payload["preferred_start_date"] = "2026-11-10"
    payload["preferred_end_date"] = "2026-11-10"

    validate_event_payload(payload, for_submission=True)


def test_submission_rejects_event_spanning_more_than_24_hours():
    """An event's total span, start to end, may not exceed 24 hours -- two
    or more calendar days apart is always over that regardless of times,
    so this is rejected outright before times even come into play."""
    payload = _complete_payload()
    payload["preferred_start_date"] = "2026-11-10"
    payload["preferred_end_date"] = "2026-11-12"

    with pytest.raises(ValidationError, match="24 hours"):
        validate_event_payload(payload, for_submission=True)


def test_submission_rejects_next_day_event_exceeding_24_hours_precisely():
    """One calendar day apart is ambiguous from the dates alone, but with
    times given the exact duration can still exceed 24 hours and must be
    rejected."""
    payload = _complete_payload()
    payload["preferred_start_date"] = "2026-11-10"
    payload["preferred_end_date"] = "2026-11-11"
    payload["preferred_start_time"] = "08:00"
    payload["preferred_end_time"] = "09:00"  # 25 hours later

    with pytest.raises(ValidationError, match="24 hours"):
        validate_event_payload(payload, for_submission=True)


def test_submission_accepts_event_exactly_24_hours_long():
    """Exactly 24 hours is the allowed boundary, not a violation."""
    payload = _complete_payload()
    payload["preferred_start_date"] = "2026-11-10"
    payload["preferred_end_date"] = "2026-11-11"
    payload["preferred_start_time"] = "08:00"
    payload["preferred_end_time"] = "08:00"  # exactly 24 hours later

    validate_event_payload(payload, for_submission=True)


def test_submission_requires_preferred_end_date():
    """preferred_end_date is a mandatory field -- even a single-day event
    must state its own end date (equal to the start date)."""
    payload = _complete_payload()
    payload.pop("preferred_end_date")

    with pytest.raises(ValidationError, match="preferred_end_date"):
        validate_event_payload(payload, for_submission=True)


def test_submission_allows_end_time_before_start_time_when_end_date_is_later():
    """An end time numerically earlier than the start time is a
    legitimate overnight event once the end DATE is on a later day (e.g.
    22:00 on day one to 06:00 on day two) -- the two pairs are compared
    as combined datetimes, not as separate date/time rules."""
    payload = _complete_payload()
    payload["preferred_start_date"] = "2026-11-10"
    payload["preferred_end_date"] = "2026-11-11"
    payload["preferred_start_time"] = "22:00"
    payload["preferred_end_time"] = "06:00"

    validate_event_payload(payload, for_submission=True)


def test_submission_rejects_end_time_before_start_time_on_the_same_date():
    """When the start and end dates are the SAME day, the end time must
    still be after the start time -- the combined-datetime check reduces
    to the ordinary same-day comparison in that case."""
    payload = _complete_payload()
    payload["preferred_start_date"] = "2026-11-10"
    payload["preferred_end_date"] = "2026-11-10"
    payload["preferred_start_time"] = "22:00"
    payload["preferred_end_time"] = "06:00"

    with pytest.raises(ValidationError, match="preferred_end_time"):
        validate_event_payload(payload, for_submission=True)


def test_submission_rejects_start_time_after_end_time():
    """Verify the event time range must run forwards, not backwards."""
    payload = _complete_payload()
    payload["preferred_start_date"] = "2026-11-10"
    payload["preferred_end_date"] = "2026-11-10"
    payload["preferred_start_time"] = "17:01"
    payload["preferred_end_time"] = "17:00"

    with pytest.raises(ValidationError, match="preferred_end_time"):
        validate_event_payload(payload, for_submission=True)


def test_submission_rejects_equal_start_and_end_times():
    """Verify an event cannot have a zero-length time range."""
    payload = _complete_payload()
    payload["preferred_start_date"] = "2026-11-10"
    payload["preferred_end_date"] = "2026-11-10"
    payload["preferred_start_time"] = "09:00"
    payload["preferred_end_time"] = "09:00"

    with pytest.raises(ValidationError, match="preferred_end_time"):
        validate_event_payload(payload, for_submission=True)


@pytest.mark.parametrize(
    ("start", "end"),
    [("00:00", "01:00"), ("05:00", "05:30"), ("23:00", "23:59")],
)
def test_submission_accepts_times_outside_old_venue_hours(start, end):
    """Venues are now available 24 hours -- times that used to fall
    outside the old 8am-10pm window are accepted."""
    payload = _complete_payload()
    payload["preferred_start_time"] = start
    payload["preferred_end_time"] = end

    validate_event_payload(payload, for_submission=True)


def test_submission_allows_empty_special_requests():
    """Verify special requests are optional and may be submitted blank."""
    payload = _complete_payload()
    payload["special_requests"] = ""

    validate_event_payload(payload, for_submission=True)


def test_submission_allows_empty_accessibility_and_equipment():
    """Verify accessibility needs and equipment are optional JSONB arrays."""
    payload = _complete_payload()
    payload["accessibility_needs"] = []
    payload["equipment"] = []

    validate_event_payload(payload, for_submission=True)


def test_submission_rejects_zero_equipment_quantity():
    """Verify equipment quantities must be positive integers."""
    payload = _complete_payload()
    payload["equipment"] = [{"item": "projector", "quantity": 0}]

    with pytest.raises(ValidationError, match="positive integer"):
        validate_event_payload(payload, for_submission=True)


def test_submission_rejects_unknown_jsonb_items():
    """Verify unsupported equipment and accessibility item names are rejected."""
    payload = _complete_payload()
    payload["equipment"] = [{"item": "laptop", "quantity": 1}]

    with pytest.raises(ValidationError, match="Unsupported equipment item"):
        validate_event_payload(payload, for_submission=True)
