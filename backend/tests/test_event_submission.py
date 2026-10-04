"""Tests for submitting event requests for review."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace

import pytest

import app.auth.context as context_module
import app.events.event_service as service
import app.events.routes as routes_module
import app.events.transitions as transitions
from app.events.coordinator_service import NoCoordinatorAvailableError
from app.events.event_service import (
    SINGAPORE_TZ,
    create_event_request,
    list_event_sessions,
    submit_event_request,
    validate_event_payload,
)
from app.shared.errors import ValidationError
from tests.factories import make_user
from tests.fake_supabase import FakeSupabase


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
    # Registration opens today and closes at noon today -- before every
    # session start any test below sets (all of them are tomorrow or later).
    registration_opens = datetime.combine(date.today(), time.min, tzinfo=SINGAPORE_TZ)
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
        "registration_start_datetime": registration_opens.isoformat(),
        "registration_end_datetime": (registration_opens + timedelta(hours=12)).isoformat(),
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


def test_submission_accepts_event_spanning_multiple_days():
    """Events are no longer capped at a 24-hour span -- a multi-day date
    range is accepted."""
    payload = _complete_payload()
    payload["preferred_start_date"] = "2026-11-10"
    payload["preferred_end_date"] = "2026-11-12"

    validate_event_payload(payload, for_submission=True)


def test_submission_accepts_next_day_event_exceeding_24_hours_precisely():
    """A precise duration of more than 24 hours is accepted now that the
    max-duration rule has been removed."""
    payload = _complete_payload()
    payload["preferred_start_date"] = "2026-11-10"
    payload["preferred_end_date"] = "2026-11-11"
    payload["preferred_start_time"] = "08:00"
    payload["preferred_end_time"] = "09:00"  # 25 hours later

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


# -- Registration window on submission -----------------------------------------


def test_submission_names_the_one_missing_registration_field():
    """When registration is needed but only the closing time is missing, the error
    names just that one field."""

    payload = _complete_payload()
    payload.pop("registration_end_datetime")

    with pytest.raises(ValidationError, match="^registration_end_datetime is required when registration"):
        validate_event_payload(payload, for_submission=True)


def test_submission_checks_registration_close_against_session_start_without_a_time():
    """With no start time, the session is taken to start at 00:00 on its
    start date, so registration must close by then."""
    payload = _complete_payload()
    payload["preferred_start_date"] = "2026-11-10"
    payload["preferred_end_date"] = "2026-11-10"
    payload["preferred_start_time"] = None
    payload["preferred_end_time"] = None
    payload["registration_end_datetime"] = "2026-11-10T00:30:00+08:00"

    with pytest.raises(ValidationError, match="on or before the session's preferred start"):
        validate_event_payload(payload, for_submission=True)


@pytest.mark.parametrize("value", ["not-a-date", 20261101, "2026-13-01T09:00:00+08:00"])
def test_submission_rejects_malformed_registration_datetimes(value):
    """Registration datetimes that aren't valid ISO strings (garbage text, a
    number, an impossible month) are rejected on submission."""

    payload = _complete_payload()
    payload["registration_start_datetime"] = value

    with pytest.raises(ValidationError, match="ISO datetime with a timezone offset"):
        validate_event_payload(payload, for_submission=True)


# -- Submitting a multi-session request ------------------------------------------


def _session_row(event_id, **overrides):
    """A complete, submittable draft session as stored in the events table."""
    payload = _complete_payload()
    row = {
        "id": event_id,
        "organizer_id": "user-1",
        "coordinator_id": None,
        "status": "draft",
        "shared_event_id": "group-1",
        "created_at": "2026-10-01T00:00:00+00:00",
        **{key: value for key, value in payload.items() if key != "equipment"},
        "equipment_needed": {"equipment": payload["equipment"]},
    }
    row.update(overrides)
    return row


@pytest.fixture
def fake_db(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(service, "supabase", fake)
    monkeypatch.setattr(transitions, "supabase", fake)
    return fake


@pytest.fixture
def assigned(monkeypatch, fake_db):
    """Stands in for coordinator auto-assignment. Like the real
    assign_initial_coordinator, one call assigns "coord-1" to every
    submitted session of the request (one coordinator per request).
    Records which event id it was called with."""
    calls = []

    def fake_assign(event_id, actor=None):
        calls.append(event_id)
        shared_event_id = fake_db.get(event_id)["shared_event_id"]
        for row in fake_db.rows:
            if row["id"] == event_id or (row["shared_event_id"] == shared_event_id and row["status"] == "submitted"):
                row.update(coordinator_id="coord-1", status="under_review")
        return {"id": "coord-1"}

    monkeypatch.setattr(service, "assign_initial_coordinator", fake_assign)
    return calls


def test_submit_from_one_session_submits_every_draft_session(fake_db, assigned):
    """Submitting from one session submits every draft session of the request.
    Coordinator assignment runs once, for the whole request, so every
    session ends up with the same coordinator. The response is the session
    the organiser submitted from."""

    fake_db.rows = [_session_row("a"), _session_row("b")]

    submitted = submit_event_request("a", SimpleNamespace(**fake_db.get("a")))

    assert {row["status"] for row in fake_db.rows} == {"under_review"}
    # One assignment for the request, after every session is submitted --
    # not one per session.
    assert len(assigned) == 1
    assert {row["coordinator_id"] for row in fake_db.rows} == {"coord-1"}
    # The response is the session the caller submitted from.
    assert submitted["id"] == "a"
    assert submitted["status"] == "under_review"


def test_submit_leaves_sessions_submitted_when_no_coordinator_is_free(fake_db, monkeypatch):
    """If no coordinator is available, every session still submits and stays
    "submitted" with no coordinator -- it isn't an error."""

    fake_db.rows = [_session_row("a"), _session_row("b")]

    def no_coordinator(event_id, actor=None):
        raise NoCoordinatorAvailableError("everyone is busy")

    monkeypatch.setattr(service, "assign_initial_coordinator", no_coordinator)

    submitted = submit_event_request("a", SimpleNamespace(**fake_db.get("a")))

    assert {row["status"] for row in fake_db.rows} == {"submitted"}
    assert submitted["coordinator_id"] is None


def test_submit_validates_every_session_before_submitting_any(fake_db, assigned):
    """One incomplete session blocks the whole request -- none of them
    changes status, so the request is never left half-submitted."""
    fake_db.rows = [
        _session_row("a"),
        _session_row("b", preferred_start_date="2026-11-20", preferred_end_date="2026-11-20", room_layout=None),
    ]

    with pytest.raises(ValidationError, match="^Session 2: Missing required fields: room_layout"):
        submit_event_request("a", SimpleNamespace(**fake_db.get("a")))

    assert {row["status"] for row in fake_db.rows} == {"draft"}
    assert assigned == []
    assert [call["op"] for call in fake_db.calls] == ["select"]


def test_submit_single_session_error_has_no_session_prefix(fake_db, assigned):
    """For a request with only one session, a validation error isn't prefixed with
    "Session 1:"."""

    fake_db.rows = [_session_row("a", room_layout=None)]

    with pytest.raises(ValidationError, match="^Missing required fields: room_layout"):
        submit_event_request("a", SimpleNamespace(**fake_db.get("a")))


def test_submit_ignores_sessions_already_past_draft(fake_db, assigned):
    """Only still-draft sessions of the request are submitted; a sibling
    already in review keeps its status and coordinator."""
    fake_db.rows = [
        _session_row("a"),
        _session_row("reviewed", status="approved", coordinator_id="coord-9"),
        _session_row("other-request", shared_event_id="group-2"),
    ]

    submit_event_request("a", SimpleNamespace(**fake_db.get("a")))

    assert assigned == ["a"]
    assert fake_db.get("reviewed")["status"] == "approved"
    assert fake_db.get("reviewed")["coordinator_id"] == "coord-9"
    assert fake_db.get("other-request")["status"] == "draft"


def test_submit_only_moves_rows_that_are_still_drafts(fake_db, assigned):
    """The status update is conditioned on status = draft, so a double
    submit can't push an already-submitted session back to "submitted"."""
    fake_db.rows = [_session_row("a")]

    submit_event_request("a", SimpleNamespace(**fake_db.get("a")))

    updates = [call for call in fake_db.calls if call["op"] == "update"]
    assert updates and all(("eq", "status", "draft") in call["filters"] for call in updates)


# -- Submitting without saving a draft first --------------------------------------


def _group_body(*sessions):
    payload = _complete_payload()
    shared = {key: payload[key] for key in ("name", "description", "purpose")}
    session = {key: value for key, value in payload.items() if key not in shared}
    return {**shared, "sessions": [{**session, **overrides} for overrides in sessions] or [session]}


def test_create_event_request_inserts_and_submits_every_session(fake_db, assigned):
    """Submitting without saving a draft first inserts every session under one
    shared_event_id, owned by the organiser, and submits all of them under
    one coordinator. A session without registration is stored with no
    registration window."""

    group = create_event_request(
        "user-1",
        _group_body({"room_layout": "theatre"}, {"room_layout": "banquet", "registration_needs": False}),
    )

    assert len(fake_db.rows) == 2
    assert len({row["shared_event_id"] for row in fake_db.rows}) == 1
    uuid.UUID(fake_db.rows[0]["shared_event_id"])  # a real uuid, generated on the server
    assert all(row["organizer_id"] == "user-1" for row in fake_db.rows)
    assert len(assigned) == 1
    assert {row["coordinator_id"] for row in fake_db.rows} == {"coord-1"}
    assert {row["status"] for row in group["sessions"]} == {"under_review"}
    assert group["shared_event_id"] == fake_db.rows[0]["shared_event_id"]
    # A session without registration is stored with no window at all.
    banquet = next(row for row in fake_db.rows if row["room_layout"] == "banquet")
    assert banquet["registration_start_datetime"] is None
    assert banquet["registration_end_datetime"] is None


def test_create_event_request_stores_registration_window_as_singapore_timestamptz(fake_db, assigned):
    """Submitting straight away (no draft) writes the registration window
    to the timestamptz columns with Singapore's +08:00 offset."""
    body = _group_body(
        {
            "preferred_start_date": "2026-11-10",
            "preferred_end_date": "2026-11-10",
            "registration_start_datetime": "2026-11-01T01:00:00.000Z",
            "registration_end_datetime": "2026-11-09T10:00:00.000Z",
        }
    )

    create_event_request("user-1", body)

    (row,) = fake_db.rows
    assert row["registration_start_datetime"] == "2026-11-01T09:00:00+08:00"
    assert row["registration_end_datetime"] == "2026-11-09T18:00:00+08:00"


def test_create_event_request_writes_nothing_when_any_session_is_invalid(fake_db, assigned):
    """If any session is invalid, submitting without a draft writes nothing and
    assigns no coordinator, and the error names the failing session."""

    with pytest.raises(ValidationError, match="^Session 2: expected_attendance"):
        create_event_request("user-1", _group_body({}, {"expected_attendance": -5}))

    assert fake_db.calls == []
    assert assigned == []


# -- Routes ---------------------------------------------------------------------


def _post(client, signing_key, path, body):
    token = signing_key.make_token(sub="user-1")
    return client.post(path, headers={"Authorization": f"Bearer {token}"}, json=body)


def test_create_route_passes_the_group_body_and_returns_201(client, signing_key, monkeypatch):
    """POST /events hands the organiser's id and the request body to
    create_event_request unchanged, and responds 201 with the result."""

    _mock_profile(monkeypatch, ["event_organizer"])
    calls = []

    def fake_create(organizer_id, payload):
        calls.append((organizer_id, payload))
        return {"shared_event_id": "group-1", "sessions": [{"id": "event-1", "status": "submitted"}]}

    monkeypatch.setattr(routes_module, "create_event_request", fake_create)
    body = _group_body()

    response = _post(client, signing_key, "/events", body)

    assert response.status_code == 201
    assert response.get_json()["shared_event_id"] == "group-1"
    assert calls == [("user-1", body)]


def test_create_route_returns_400_for_an_invalid_session(client, signing_key, monkeypatch):
    """End to end through the real service: validation fails before any
    database call, so no fake client is needed."""
    _mock_profile(monkeypatch, ["event_organizer"])

    response = _post(client, signing_key, "/events", _group_body({}, {"room_layout": "stadium"}))

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "validation_error"
    assert "Session 2" in response.get_json()["error"]["message"]


def test_create_route_denies_a_non_organizer(client, signing_key, monkeypatch):
    """A user without the event_organizer role can't create a request through POST
    /events -- the service is never called."""

    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(routes_module, "create_event_request", lambda *a: pytest.fail("must not create"))

    response = _post(client, signing_key, "/events", _group_body())

    assert response.status_code in (403, 404)


def test_save_draft_route_passes_the_group_body(client, signing_key, monkeypatch):
    """POST /events/<id>/draft hands the loaded event and the request body
    (sessions included) to save_draft_request unchanged, and responds 200."""

    _mock_profile(monkeypatch, ["event_organizer"])
    event = _complete_draft()
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: event)
    calls = []

    def fake_save(event_id, loaded_event, payload):
        calls.append((event_id, loaded_event, payload))
        return {"shared_event_id": "group-1", "sessions": [{"id": event_id}]}

    monkeypatch.setattr(routes_module, "save_draft_request", fake_save)
    body = {"name": "Workshop", "sessions": [{"id": "event-1"}, {"expected_attendance": 10}]}

    response = _post(client, signing_key, "/events/event-1/draft", body)

    assert response.status_code == 200
    assert calls == [("event-1", event, body)]


# -- IS-31 Submit event request ------------------------------------------------
# "As an Event Organizer, I want to submit my completed event request, so
# that it can be reviewed by an Event Coordinator."
#
# Tests elsewhere that already cover these acceptance criteria (not repeated
# here):
#   AC1 status -> Submitted:
#     test_submit_event_route_sets_submitted_for_organizer,
#     test_submit_leaves_sessions_submitted_when_no_coordinator_is_free,
#     test_submit_from_one_session_submits_every_draft_session (this file);
#     test_organiser_allowed_event_submit_from_draft,
#     test_organiser_denied_event_submit_from_status_other_than_draft
#     (test_authz_policy.py)
#   AC2 visible in the assigned Coordinator's queue:
#     test_coordinator_allowed_view_on_assigned_event (test_authz_policy.py),
#     test_coordinator_sees_only_events_assigned_to_them
#     (test_event_list_integration.py),
#     test_submitted_request_appears_in_assigned_coordinators_queue_against_supabase
#     (test_event_submission_integration.py)
#   AC3 only the Event Coordinator may edit once submitted:
#     test_organiser_denied_edit_after_submission,
#     test_coordinator_allowed_edit_assigned_event_under_review_or_planning,
#     test_coordinator_denied_edit_on_event_assigned_to_someone_else
#     (test_authz_policy.py); test_delete_route_denies_submitted_event
#     (test_events_routes.py)
#
# The tests below cover what those don't: the same rules enforced at the
# HTTP API the frontend actually calls, and per-session queue visibility.


def _submitted_event(**overrides):
    event = _complete_draft()
    event.status = "submitted"
    for key, value in overrides.items():
        setattr(event, key, value)
    return event


def test_is31_submitted_request_cannot_be_submitted_again(client, signing_key, monkeypatch):
    """AC1: once a request is submitted, submitting it again is refused with
    403 (the organiser knows it exists, it's just past the draft stage), and
    the submit service never runs -- so no second coordinator assignment."""
    _mock_profile(monkeypatch, ["event_organizer"])
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: _submitted_event())
    monkeypatch.setattr(routes_module, "submit_event_request", lambda *a: pytest.fail("must not submit"))

    response = _post(client, signing_key, "/events/event-1/submit", {})

    assert response.status_code == 403


def test_is31_coordinator_sees_only_the_sessions_assigned_to_them(monkeypatch):
    """AC2: each submitted session lands in the queue of the coordinator it
    was assigned to. Viewing a request's sessions, a coordinator sees only
    their own assigned session(s) -- not a sibling session assigned to a
    different coordinator -- while the organiser sees all of them."""
    fake = FakeSupabase(
        [
            {"id": "a", "shared_event_id": "group-1", "organizer_id": "user-1",
             "coordinator_id": "coord-1", "status": "under_review", "name": "Workshop"},
            {"id": "b", "shared_event_id": "group-1", "organizer_id": "user-1",
             "coordinator_id": "coord-2", "status": "under_review", "name": "Workshop"},
        ]
    )
    monkeypatch.setattr(service, "supabase", fake)
    monkeypatch.setattr(transitions, "supabase", fake)
    event = SimpleNamespace(**fake.get("a"))

    coordinator_view = list_event_sessions(event, make_user(["event_coordinator"], user_id="coord-1"))
    organizer_view = list_event_sessions(event, make_user(["event_organizer"], user_id="user-1"))

    assert [s["id"] for s in coordinator_view["sessions"]] == ["a"]
    assert sorted(s["id"] for s in organizer_view["sessions"]) == ["a", "b"]


@pytest.mark.parametrize("status", ["submitted", "under_review", "approved", "planning"])
def test_is31_organizer_cannot_save_changes_once_submitted(client, signing_key, monkeypatch, status):
    """AC3: after submission the organiser can't change any field through the
    save endpoint the edit form uses -- refused with 403, and nothing is
    saved, at every status past draft (rejected is the one exception,
    covered by test_organiser_allowed_edit_after_rejection)."""
    _mock_profile(monkeypatch, ["event_organizer"])
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: _submitted_event(status=status))
    monkeypatch.setattr(routes_module, "save_draft_request", lambda *a: pytest.fail("must not save"))

    response = _post(
        client, signing_key, "/events/event-1/draft", {"name": "Changed", "sessions": [{"id": "event-1"}]}
    )

    assert response.status_code == 403


def test_is31_organizer_cannot_edit_a_submitted_request_directly(client, signing_key, monkeypatch):
    """AC3: the direct field-edit endpoint (POST /events/<id>) is refused
    for the organiser once the request is submitted, and nothing is changed."""
    _mock_profile(monkeypatch, ["event_organizer"])
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: _submitted_event())
    monkeypatch.setattr(routes_module, "edit_event_request", lambda *a: pytest.fail("must not edit"))

    response = _post(client, signing_key, "/events/event-1", {"expected_attendance": 500})

    assert response.status_code == 403


@pytest.mark.parametrize("status", ["under_review", "planning"])
def test_is31_assigned_coordinator_can_edit_the_request(client, signing_key, monkeypatch, status):
    """AC3: the Event Coordinator assigned to the request CAN edit it through
    the same endpoint the organiser is refused on -- both while reviewing it
    (under_review) and later during planning."""
    _mock_profile(monkeypatch, ["event_coordinator"])
    event = _submitted_event(status=status, organizer_id="organizer-2", coordinator_id="user-1")
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: event)
    calls = []

    def fake_edit(event_id, loaded_event, payload):
        calls.append((event_id, payload))
        return {"id": event_id, "expected_attendance": payload["expected_attendance"]}

    monkeypatch.setattr(routes_module, "edit_event_request", fake_edit)

    response = _post(client, signing_key, "/events/event-1", {"expected_attendance": 500})

    assert response.status_code == 200
    assert calls == [("event-1", {"expected_attendance": 500})]


def test_is31_coordinator_edit_form_payload_is_saved(fake_db):
    """AC3: the coordinator's "Edit Details" form (CoordinatorEventReview)
    sends the whole session in one body -- shared fields plus every session
    field, with the registration window in UTC. edit_event_request accepts
    exactly that shape and writes it to the event's own row, leaving the
    status and the assigned coordinator as they were."""
    fake_db.rows = [_session_row("a", status="under_review", coordinator_id="coord-1")]
    form_body = {
        "name": "Community Conference (revised)",
        "description": "Updated by the coordinator.",
        "purpose": "Knowledge sharing.",
        "preferred_start_date": "2026-11-10",
        "preferred_start_time": "10:00",
        "preferred_end_date": "2026-11-10",
        "preferred_end_time": "16:00",
        "expected_attendance": 120,
        "accessibility_needs": [{"item": "lift_access"}],
        "room_layout": "banquet",
        "equipment": [{"item": "screen", "quantity": 2}],
        "registration_needs": True,
        "registration_start_datetime": "2026-11-01T01:00:00.000Z",
        "registration_end_datetime": "2026-11-09T10:00:00.000Z",
        "special_requests": "",
    }

    service.edit_event_request("a", SimpleNamespace(**fake_db.get("a")), form_body)

    row = fake_db.get("a")
    assert row["name"] == "Community Conference (revised)"
    assert row["expected_attendance"] == 120
    assert row["room_layout"] == "banquet"
    assert row["equipment_needed"] == {"equipment": [{"item": "screen", "quantity": 2}]}
    assert row["registration_end_datetime"] == "2026-11-09T18:00:00+08:00"
    assert row["status"] == "under_review"
    assert row["coordinator_id"] == "coord-1"


# -- Resubmitting a rejected request ---------------------------------------------


def test_resubmit_route_accepts_a_rejected_request(client, signing_key, monkeypatch):
    """The organiser can submit their own rejected request again through
    POST /events/<id>/submit -- it reaches the submit service (200)."""
    _mock_profile(monkeypatch, ["event_organizer"])
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: _submitted_event(status="rejected"))
    calls = []
    monkeypatch.setattr(
        routes_module,
        "submit_event_request",
        lambda event_id, event: calls.append(event_id) or {"id": event_id, "status": "under_review"},
    )

    response = _post(client, signing_key, "/events/event-1/submit", {})

    assert response.status_code == 200
    assert calls == ["event-1"]


def test_resubmit_returns_every_rejected_session_to_its_coordinator(fake_db, assigned):
    """Resubmitting from one rejected session sends every rejected session of
    the request back to the coordinator who rejected them, as under_review
    -- no new coordinator is picked, so the request keeps its one
    coordinator. A sibling with its own outcome (approved) is untouched,
    and each resubmission is recorded in the status audit log."""
    fake_db.rows = [
        _session_row("r1", status="rejected", coordinator_id="coord-7"),
        _session_row("r2", status="rejected", coordinator_id="coord-7"),
        _session_row("ok", status="approved", coordinator_id="coord-7"),
    ]

    resubmitted = submit_event_request("r1", SimpleNamespace(**fake_db.get("r1")))

    assert fake_db.get("r1")["status"] == fake_db.get("r2")["status"] == "under_review"
    assert {fake_db.get(i)["coordinator_id"] for i in ("r1", "r2", "ok")} == {"coord-7"}
    assert fake_db.get("ok")["status"] == "approved"
    assert assigned == []
    assert resubmitted["id"] == "r1"
    # Every status change goes through transition(), so each session logs
    # both steps, attributed to the organiser whose resubmit caused them.
    log = fake_db.tables["event_status_log"]
    assert sorted(entry["event_id"] for entry in log) == ["r1", "r1", "r2", "r2"]
    assert {(entry["from_status"], entry["to_status"], entry["changed_by"]) for entry in log} == {
        ("rejected", "submitted", "user-1"),
        ("submitted", "under_review", "user-1"),
    }


def test_resubmit_validates_every_rejected_session_before_any_moves(fake_db, assigned):
    """A rejected session that still isn't complete blocks the whole
    resubmission -- every session stays rejected and nothing is logged."""
    fake_db.rows = [
        _session_row("r1", status="rejected", coordinator_id="coord-7"),
        _session_row("r2", status="rejected", coordinator_id="coord-7", expected_attendance=None),
    ]

    with pytest.raises(ValidationError, match="^Session 2: Missing required fields: expected_attendance"):
        submit_event_request("r1", SimpleNamespace(**fake_db.get("r1")))

    assert {row["status"] for row in fake_db.rows} == {"rejected"}
    assert "event_status_log" not in fake_db.tables


# -- Malformed submissions and edge cases ------------------------------------------


def test_submission_rejects_a_body_that_is_not_an_object():
    with pytest.raises(ValidationError, match="must be a JSON object"):
        validate_event_payload(["not", "an", "object"], for_submission=True)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"venue": "Hall A"}, "Unknown event fields: venue"),
        ({"description": 42}, "description must be a non-empty string"),
        ({"special_requests": 42}, "special_requests must be a string"),
        ({"registration_needs": "yes"}, "registration_needs must be true or false"),
        ({"preferred_start_date": "next tuesday"}, "preferred_start_date must be an ISO date"),
        ({"preferred_end_date": "2026/11/10"}, "preferred_end_date must be an ISO date"),
        ({"preferred_start_time": "25:00"}, "preferred_start_time must be an ISO time"),
        ({"equipment": "projector"}, "equipment must be a list of objects"),
        (
            {"accessibility_needs": [{"item": "removable_seats", "quantity": 2, "notes": "   "}]},
            "Accessibility notes must be a non-empty string",
        ),
    ],
)
def test_submission_rejects_malformed_fields(changes, message):
    """Each field of a submitted request is type- and format-checked, with a
    message naming the field that's wrong."""
    payload = {**_complete_payload(), **changes}

    with pytest.raises(ValidationError, match=message):
        validate_event_payload(payload, for_submission=True)


def test_submission_rejects_registration_closing_when_it_opens():
    """The registration period must close strictly after it opens -- a
    zero-length window is refused."""
    payload = _complete_payload()
    payload["registration_end_datetime"] = payload["registration_start_datetime"]

    with pytest.raises(ValidationError, match="after registration_start_datetime"):
        validate_event_payload(payload, for_submission=True)


def test_edit_normalizes_blank_optional_fields_and_trims_notes():
    """On an edit (not a submission), emptied optional inputs arrive as ""
    and are stored as NULL, and accessibility notes are trimmed."""
    validated = validate_event_payload(
        {
            "name": "Workshop",
            "preferred_end_date": "",
            "preferred_start_time": "",
            "preferred_end_time": "",
            "registration_start_datetime": "",
            "accessibility_needs": [{"item": "removable_seats", "quantity": 2, "notes": "  front row  "}],
        },
        for_submission=False,
    )

    assert validated["preferred_end_date"] is None
    assert validated["preferred_start_time"] is None
    assert validated["preferred_end_time"] is None
    assert validated["registration_start_datetime"] is None
    assert validated["accessibility_needs"] == [{"item": "removable_seats", "quantity": 2, "notes": "front row"}]


def test_edit_orders_times_even_without_both_dates():
    """An edit carrying only the start and end times (no date pair) is still
    checked as a same-day range: the end must be after the start."""
    with pytest.raises(ValidationError, match="preferred_end_time must be after preferred_start_time"):
        validate_event_payload(
            {"name": "Workshop", "preferred_start_time": "17:00", "preferred_end_time": "09:00"},
            for_submission=False,
        )


def test_create_event_request_requires_every_shared_field(fake_db, assigned):
    """A request body with a shared field missing altogether (not just
    blank) is refused on submission, naming the field, and nothing is
    written."""
    body = _group_body()
    del body["description"]

    with pytest.raises(ValidationError, match="^Missing required fields: description"):
        create_event_request("user-1", body)
    assert fake_db.calls == []


def test_create_event_request_errors_if_the_database_returns_no_rows(fake_db, assigned, monkeypatch):
    """If the insert comes back with no rows, submission stops with a clear
    error and no coordinator is assigned."""
    monkeypatch.setattr(service, "_insert_sessions", lambda *args: [])

    with pytest.raises(ValidationError, match="did not return an event"):
        create_event_request("user-1", _group_body())
    assert assigned == []


def test_edit_of_a_session_that_no_longer_exists_is_refused(fake_db):
    """Editing a session that was deleted in the meantime updates nothing,
    and the coordinator gets a clear error instead of an empty response."""
    stale = SimpleNamespace(**_session_row("gone", status="under_review", coordinator_id="coord-1"))

    with pytest.raises(ValidationError, match="did not return an event"):
        service.edit_event_request("gone", stale, {"name": "Community Conference", "expected_attendance": 50})
