"""Tests for multi-session event requests and the per-session
registration window."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import pytest

import app.auth.context as context_module
import app.events.event_service as service
import app.events.routes as routes_module
from app.events.event_service import (
    create_draft_request,
    create_event_request,
    list_event_sessions,
    validate_event_group,
    validate_event_payload,
)
from app.shared.errors import ValidationError
from tests.factories import make_user
from tests.fake_supabase import FakeSupabase


def _local(day: date, hour: int) -> str:
    """Singapore wall-clock time, as the session date/time columns are."""
    return datetime.combine(day, time(hour), tzinfo=service.SINGAPORE_TZ).isoformat()


def _session(days_ahead: int = 1, **overrides):
    day = date.today() + timedelta(days=days_ahead)
    session = {
        "preferred_start_date": day.isoformat(),
        "preferred_end_date": day.isoformat(),
        "preferred_start_time": "09:00",
        "preferred_end_time": "17:00",
        "expected_attendance": 50,
        "accessibility_needs": [],
        "room_layout": "theatre",
        "equipment": [],
        "registration_needs": True,
        "registration_start_datetime": _local(date.today(), 0),
        "registration_end_datetime": _local(date.today(), 12),
        "special_requests": "",
    }
    session.update(overrides)
    return session


def _group(*sessions):
    return {
        "name": "Community Conference",
        "description": "A community conference.",
        "purpose": "Knowledge sharing.",
        "sessions": list(sessions) or [_session()],
    }


def _flat(**overrides):
    return {"name": "Community Conference", "description": "d", "purpose": "p", **_session(**overrides)}


# -- Registration window -------------------------------------------------------


def test_registration_window_required_when_registration_is_needed():
    payload = _flat(registration_start_datetime=None, registration_end_datetime="")

    with pytest.raises(ValidationError, match="required when registration is needed"):
        validate_event_payload(payload, for_submission=True)


def test_registration_window_not_required_when_registration_not_needed():
    payload = _flat(
        registration_needs=False,
        registration_start_datetime=_local(date.today(), 0),
        registration_end_datetime=_local(date.today(), 12),
    )

    validated = validate_event_payload(payload, for_submission=True)

    # A stale window from a since-unticked checkbox is dropped, not stored.
    assert validated["registration_start_datetime"] is None
    assert validated["registration_end_datetime"] is None


def test_registration_must_close_after_it_opens():
    payload = _flat(
        registration_start_datetime=_local(date.today(), 12),
        registration_end_datetime=_local(date.today(), 12),
    )

    with pytest.raises(ValidationError, match="after registration_start_datetime"):
        validate_event_payload(payload, for_submission=True)


def test_registration_must_close_by_the_session_start():
    tomorrow = date.today() + timedelta(days=1)
    payload = _flat(registration_end_datetime=_local(tomorrow, 10))  # session starts 09:00

    with pytest.raises(ValidationError, match="on or before the session's preferred start"):
        validate_event_payload(payload, for_submission=True)


def test_registration_may_close_exactly_when_the_session_starts():
    tomorrow = date.today() + timedelta(days=1)
    payload = _flat(registration_end_datetime=_local(tomorrow, 9))

    validate_event_payload(payload, for_submission=True)


def test_registration_datetime_must_carry_a_timezone_offset():
    payload = _flat(registration_start_datetime="2026-11-01T09:00:00")

    with pytest.raises(ValidationError, match="timezone offset"):
        validate_event_payload(payload, for_submission=True)


def test_registration_window_is_stored_in_singapore_time():
    """The browser sends UTC ("...Z"); it's written to the timestamptz
    columns as the same instant with Singapore's +08:00 offset."""
    payload = _flat(
        preferred_start_date="2026-11-10",
        preferred_end_date="2026-11-10",
        registration_start_datetime="2026-10-31T16:00:00.000Z",  # 1 Nov 00:00 SGT
        registration_end_datetime="2026-11-01T01:00:00Z",  # 1 Nov 09:00 SGT
    )

    validated = validate_event_payload(payload, for_submission=True)

    assert validated["registration_start_datetime"] == "2026-11-01T00:00:00+08:00"
    assert validated["registration_end_datetime"] == "2026-11-01T09:00:00+08:00"


def test_registration_close_is_compared_with_session_start_in_singapore_time():
    """Session times are Singapore wall-clock. 01:30 UTC is 09:30 SGT --
    after a 09:00 session start -- whatever timezone the server runs in."""
    payload = _flat(
        preferred_start_date="2026-11-10",
        preferred_end_date="2026-11-10",
        registration_start_datetime="2026-11-01T00:00:00Z",
        registration_end_datetime="2026-11-10T01:30:00Z",
    )

    with pytest.raises(ValidationError, match="on or before the session's preferred start"):
        validate_event_payload(payload, for_submission=True)

    payload["registration_end_datetime"] = "2026-11-10T01:00:00Z"  # exactly 09:00 SGT
    validate_event_payload(payload, for_submission=True)


# -- Group validation ----------------------------------------------------------


def test_group_requires_at_least_one_session():
    with pytest.raises(ValidationError, match="non-empty list"):
        validate_event_group({**_group(), "sessions": []}, for_submission=True)


def test_group_rejects_unknown_session_field():
    with pytest.raises(ValidationError, match="Session 1: unknown session fields: venue"):
        validate_event_group(_group(_session(venue="Hall A")), for_submission=True)


def test_group_rejects_shared_field_inside_a_session():
    """name/description/purpose belong to the request, not to a session."""
    with pytest.raises(ValidationError, match="unknown session fields: name"):
        validate_event_group(_group(_session(name="Other")), for_submission=True)


def test_group_error_names_the_failing_session():
    group = _group(_session(), _session(days_ahead=2, expected_attendance=0))

    with pytest.raises(ValidationError, match="^Session 2: expected_attendance"):
        validate_event_group(group, for_submission=True)


def test_group_reports_missing_shared_field_once_not_per_session():
    group = _group(_session(), _session(days_ahead=2))
    group["purpose"] = ""

    with pytest.raises(ValidationError) as exc_info:
        validate_event_group(group, for_submission=True)
    assert "Session" not in exc_info.value.message


def test_group_sessions_may_differ_in_every_session_field():
    group = _group(
        _session(room_layout="theatre", expected_attendance=200),
        _session(
            days_ahead=3,
            room_layout="banquet",
            expected_attendance=40,
            registration_needs=False,
            equipment=[{"item": "microphone", "quantity": 2}],
            accessibility_needs=[{"item": "lift_access"}],
        ),
    )

    rows = validate_event_group(group, for_submission=True)

    assert [row["room_layout"] for row in rows] == ["theatre", "banquet"]
    assert all(row["name"] == "Community Conference" for row in rows)


# -- Creation --------------------------------------------------------------------


def test_create_event_request_ignores_client_supplied_shared_event_id():
    """shared_event_id is generated server-side -- a client can't pick it."""
    group = _group()
    group["shared_event_id"] = str(uuid.uuid4())

    with pytest.raises(ValidationError, match="Unknown event fields: shared_event_id"):
        create_event_request("user-1", group)


def test_create_draft_request_allows_half_filled_sessions(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        service,
        "_insert_sessions",
        lambda organizer_id, rows, shared_event_id: captured.setdefault("rows", rows),
    )

    create_draft_request(
        "user-1",
        {"sessions": [{"expected_attendance": 30}, {"room_layout": "", "registration_start_datetime": ""}]},
    )

    first, second = captured["rows"]
    assert first["name"] == service.DRAFT_NAME
    assert first["expected_attendance"] == 30
    assert second["room_layout"] is None
    assert second["registration_start_datetime"] is None


def test_create_draft_request_rejects_an_entirely_empty_request():
    with pytest.raises(ValidationError, match="At least one event field"):
        create_draft_request("user-1", {"name": "", "sessions": [{}, {"room_layout": ""}]})


# -- Editing / viewing -----------------------------------------------------------


def _rejected_event():
    return SimpleNamespace(
        id="event-1", organizer_id="user-1", coordinator_id="coord-1", status="rejected",
        shared_event_id="group-1", name="n", description="d", purpose="p",
        preferred_start_date=None, preferred_end_date=None, preferred_start_time=None,
        preferred_end_time=None, expected_attendance=None, accessibility_needs=[], room_layout=None,
        equipment_needed={}, registration_needs=False, special_requests=None,
    )


def test_list_event_sessions_without_shared_id_is_a_group_of_one(monkeypatch):
    monkeypatch.setattr(service, "supabase", FakeSupabase())
    event = _rejected_event()
    event.shared_event_id = None

    group = list_event_sessions(event, make_user(["event_organizer"]))

    assert [s["id"] for s in group["sessions"]] == ["event-1"]
    assert group["name"] == "n"


# -- Rejection reason on rejected sessions -------------------------------------


def _log_entry(event_id, reason, changed_at, to_status="rejected", by="Alice Tan"):
    return {
        "event_id": event_id,
        "to_status": to_status,
        "reason": reason,
        "changed_at": changed_at,
        "profiles": {"name": by},
    }


def test_rejected_sessions_carry_the_coordinators_latest_rejection(monkeypatch):
    """A rejected session comes back with the coordinator's reason, who
    rejected it and when -- the MOST RECENT rejection, since a session can
    be rejected, fixed, resubmitted and rejected again. A session that
    isn't rejected gets no rejection, even if it was rejected in the past."""
    fake = FakeSupabase(
        [
            {"id": "r", "shared_event_id": "group-1", "organizer_id": "user-1", "coordinator_id": "coord-1",
             "status": "rejected", "name": "Workshop"},
            {"id": "ok", "shared_event_id": "group-1", "organizer_id": "user-1", "coordinator_id": "coord-1",
             "status": "under_review", "name": "Workshop"},
        ]
    )
    fake.tables["event_status_log"] = [
        _log_entry("r", "Venue too small.", "2026-10-01T09:00:00+00:00"),
        _log_entry("r", "Please add an accessible entrance.", "2026-10-03T09:00:00+00:00"),
        _log_entry("r", None, "2026-10-02T09:00:00+00:00", to_status="under_review", by="Organiser"),
        _log_entry("ok", "Old reason, since fixed.", "2026-10-01T09:00:00+00:00"),
    ]
    monkeypatch.setattr(service, "supabase", fake)

    group = list_event_sessions(SimpleNamespace(**fake.get("r")), make_user(["event_organizer"]))

    sessions = {s["id"]: s for s in group["sessions"]}
    assert sessions["r"]["rejection"] == {
        "reason": "Please add an accessible entrance.",
        "rejected_at": "2026-10-03T09:00:00+00:00",
        "rejected_by": "Alice Tan",
    }
    assert "rejection" not in sessions["ok"]


def test_no_rejection_lookup_when_nothing_is_rejected(monkeypatch):
    """Requests with no rejected session don't query the status log at all."""
    fake = FakeSupabase(
        [{"id": "a", "shared_event_id": "group-1", "organizer_id": "user-1", "coordinator_id": None,
          "status": "draft", "name": "Workshop"}]
    )
    monkeypatch.setattr(service, "supabase", fake)

    list_event_sessions(SimpleNamespace(**fake.get("a")), make_user(["event_organizer"]))

    assert {call["table"] for call in fake.calls} == {"events"}


def test_sessions_route_returns_group(client, signing_key, monkeypatch):
    monkeypatch.setattr(
        context_module,
        "_load_profile_with_roles",
        lambda user_id: ("Test User", "test@example.com", frozenset(["event_organizer"])),
    )
    monkeypatch.setattr(context_module, "_get_last_active", lambda session_id: None)
    monkeypatch.setattr(context_module, "_touch_session_activity", lambda *a, **k: None)
    event = SimpleNamespace(id="event-1", organizer_id="user-1", coordinator_id=None, status="draft")
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: event)
    monkeypatch.setattr(
        routes_module,
        "list_event_sessions",
        lambda loaded, user: {"shared_event_id": "group-1", "sessions": [{"id": loaded.id}]},
    )

    token = signing_key.make_token(sub="user-1")
    response = client.get("/events/event-1/sessions", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.get_json() == {"shared_event_id": "group-1", "sessions": [{"id": "event-1"}]}
