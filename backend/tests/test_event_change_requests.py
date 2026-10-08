"""IS-21 Request for Event Change.

"As an Event Organiser, I want to request changes to an event, so that the
event details can be updated when requirements change."

Unit-level: no real Supabase. Rule tests use plain FakeEvents; service and
end-to-end route tests swap the modules' `supabase` for FakeSupabase so the
tests can see exactly what is written to event_change_requests, event_logs
and events.

Acceptance criteria, and the tests that prove each one:
  AC1 request permitted changes for a submitted event
      -> test_organiser_may_request_a_change_once_submitted, ..._refused_*
  AC2 specify the event detail(s) to change
      -> test_request_records_only_the_details_that_change, ...validation tests
  AC3 the change request is recorded for the relevant event
      -> test_request_is_recorded_against_the_request_and_the_session
  AC4 the assigned coordinator can view and review it
      -> test_assigned_coordinator_may_review..., list/approve/reject tests
  AC5 a confirmed event can't be overwritten directly by the organiser
      -> test_organiser_cannot_edit_a_confirmed_event_directly,
         test_confirmed_event_changes_only_after_coordinator_approval
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

import app.auth.context as context_module
import app.events.change_impact as impact_module
import app.events.change_request_service as service
import app.events.event_log as event_log_module
import app.events.routes as routes_module
from app.authz import actions
from app.authz.policy import authorise, can
from app.authz.rules import CHANGE_REQUEST_STATUSES
from app.events.change_request_service import (
    ChangeRequestConflictError,
    approve_change_request,
    list_change_requests,
    reject_change_request,
    request_event_change,
)
from app.shared.errors import AuthorisationError, NotFoundError, ValidationError
from tests.factories import FakeEvent, make_user
from tests.fake_supabase import FakeSupabase

ORGANISER = "org-1"
COORDINATOR = "coord-1"
FUTURE = (date.today() + timedelta(days=30)).isoformat()
LATER = (date.today() + timedelta(days=31)).isoformat()


def _session(**overrides) -> dict:
    row = {
        "id": "session-1",
        "shared_event_id": "group-1",
        "organizer_id": ORGANISER,
        "coordinator_id": COORDINATOR,
        "status": "confirmed",
        "name": "Community Conference",
        "description": "A community conference.",
        "purpose": "Knowledge sharing.",
        "preferred_start_date": FUTURE,
        "preferred_end_date": FUTURE,
        "preferred_start_time": "09:00:00",
        "preferred_end_time": "17:00:00",
        "expected_attendance": 100,
        "accessibility_needs": [{"item": "wheelchair_access"}],
        "room_layout": "theatre",
        "equipment_needed": {"equipment": [{"item": "projector", "quantity": 1}]},
        "registration_needs": False,
        "registration_start_datetime": None,
        "registration_end_datetime": None,
        "special_requests": None,
    }
    row.update(overrides)
    return row


def _event(fake: FakeSupabase, event_id: str = "session-1") -> SimpleNamespace:
    """The session as @require's loader would hand it over: read fresh."""
    return SimpleNamespace(**dict(fake.get(event_id)))


@pytest.fixture
def fake(monkeypatch):
    db = FakeSupabase(
        [
            _session(),
            _session(id="session-2", preferred_start_date=LATER, preferred_end_date=LATER),
            _session(id="other-org-session", shared_event_id="group-1", organizer_id="org-2", coordinator_id="coord-2"),
        ]
    )
    monkeypatch.setattr(service, "supabase", db)
    monkeypatch.setattr(impact_module, "supabase", db)
    monkeypatch.setattr(event_log_module, "supabase", db)
    monkeypatch.setattr(routes_module, "supabase", db)
    return db


def _logs(fake: FakeSupabase) -> list[dict]:
    return fake.tables.get("event_change_requests", [])


# -- authz: who may request, who may review ---------------------------------


@pytest.mark.parametrize("status", CHANGE_REQUEST_STATUSES)
def test_organiser_may_request_a_change_once_submitted(status):
    organiser = make_user(["event_organizer"], user_id=ORGANISER)
    assert can(organiser, actions.EVENT_REQUEST_CHANGE, FakeEvent(organizer_id=ORGANISER, status=status))


@pytest.mark.parametrize("status", ["draft", "rejected", "completed", "cancelled"])
def test_request_change_refused_outside_the_submitted_window(status):
    # draft/rejected: the organiser edits those directly. completed/cancelled:
    # nothing left to change.
    organiser = make_user(["event_organizer"], user_id=ORGANISER)
    with pytest.raises(AuthorisationError):
        authorise(organiser, actions.EVENT_REQUEST_CHANGE, FakeEvent(organizer_id=ORGANISER, status=status))


def test_request_change_hidden_from_another_organiser():
    other = make_user(["event_organizer"], user_id="org-2")
    with pytest.raises(NotFoundError):
        authorise(other, actions.EVENT_REQUEST_CHANGE, FakeEvent(organizer_id=ORGANISER, status="confirmed"))


def test_coordinator_cannot_request_a_change_on_the_organisers_behalf():
    coordinator = make_user(["event_coordinator"], user_id=COORDINATOR)
    event = FakeEvent(organizer_id=ORGANISER, coordinator_id=COORDINATOR, status="planning")
    with pytest.raises(AuthorisationError):  # 403: they can already see it
        authorise(coordinator, actions.EVENT_REQUEST_CHANGE, event)


@pytest.mark.parametrize("status", CHANGE_REQUEST_STATUSES)
def test_assigned_coordinator_may_review_a_change(status):
    coordinator = make_user(["event_coordinator"], user_id=COORDINATOR)
    event = FakeEvent(organizer_id=ORGANISER, coordinator_id=COORDINATOR, status=status)
    assert can(coordinator, actions.EVENT_REVIEW_CHANGE, event)


@pytest.mark.parametrize("status", ["completed", "cancelled", "rejected"])
def test_review_refused_once_the_event_has_moved_on(status):
    coordinator = make_user(["event_coordinator"], user_id=COORDINATOR)
    event = FakeEvent(organizer_id=ORGANISER, coordinator_id=COORDINATOR, status=status)
    with pytest.raises(AuthorisationError):
        authorise(coordinator, actions.EVENT_REVIEW_CHANGE, event)


def test_only_the_assigned_coordinator_reviews():
    event = FakeEvent(organizer_id=ORGANISER, coordinator_id=COORDINATOR, status="confirmed")
    with pytest.raises(NotFoundError):
        authorise(make_user(["event_coordinator"], user_id="coord-2"), actions.EVENT_REVIEW_CHANGE, event)
    # The organiser and the Lead can see the event, so it's a 403 for them.
    with pytest.raises(AuthorisationError):
        authorise(make_user(["event_organizer"], user_id=ORGANISER), actions.EVENT_REVIEW_CHANGE, event)
    with pytest.raises(AuthorisationError):
        authorise(make_user(["event_coordinator_lead"], user_id="lead-1"), actions.EVENT_REVIEW_CHANGE, event)


def test_organiser_cannot_edit_a_confirmed_event_directly():
    """AC5 at the policy level: a change request doesn't widen event.edit."""
    organiser = make_user(["event_organizer"], user_id=ORGANISER)
    with pytest.raises(AuthorisationError):
        authorise(organiser, actions.EVENT_EDIT, FakeEvent(organizer_id=ORGANISER, status="confirmed"))


# -- requesting a change ------------------------------------------------------


def test_request_is_recorded_against_the_request_and_the_session(fake):
    change = request_event_change(
        _event(fake), ORGANISER, {"changes": {"expected_attendance": 150}, "reason": "  More sign-ups.  "}
    )

    assert _logs(fake) == [change]
    assert change["shared_event_id"] == "group-1"
    assert change["event_id"] == "session-1"
    assert change["status"] == "pending"
    assert change["requested_by"] == ORGANISER
    assert change["requested_changes"] == {"expected_attendance": 150}
    assert change["previous_values"] == {"expected_attendance": 100}
    assert change["reason"] == "More sign-ups."


def test_requesting_a_change_does_not_touch_the_event(fake):
    before = dict(fake.get("session-1"))

    request_event_change(_event(fake), ORGANISER, {"changes": {"expected_attendance": 150, "room_layout": "banquet"}})

    assert fake.get("session-1") == before
    assert not [call for call in fake.calls if call["table"] == "events" and call["op"] != "select"]


def test_legacy_event_without_shared_event_id_is_a_group_of_one(fake):
    fake.rows.append(_session(id="legacy-1", shared_event_id=None))

    change = request_event_change(_event(fake, "legacy-1"), ORGANISER, {"changes": {"room_layout": "classroom"}})

    assert change["shared_event_id"] == "legacy-1"


def test_request_records_only_the_details_that_change(fake):
    change = request_event_change(
        _event(fake),
        ORGANISER,
        {"changes": {"expected_attendance": 100, "room_layout": "banquet", "preferred_start_time": "09:00"}},
    )

    assert change["requested_changes"] == {"room_layout": "banquet"}
    assert change["previous_values"] == {"room_layout": "theatre"}


def test_several_details_can_be_changed_in_one_request(fake):
    change = request_event_change(
        _event(fake),
        ORGANISER,
        {
            "changes": {
                "name": "Community Conference 2026",
                "equipment": [{"item": "microphone", "quantity": 2}],
                "special_requests": "Near the lift.",
            }
        },
    )

    assert change["requested_changes"] == {
        "name": "Community Conference 2026",
        "equipment": [{"item": "microphone", "quantity": 2}],
        "special_requests": "Near the lift.",
    }
    assert change["previous_values"] == {
        "name": "Community Conference",
        "equipment": [{"item": "projector", "quantity": 1}],
        "special_requests": None,
    }


def test_turning_registration_off_records_the_cleared_window_too(fake):
    fake.rows[0].update(
        registration_needs=True,
        registration_start_datetime="2026-01-01T01:00:00+00:00",
        registration_end_datetime="2026-01-02T01:00:00+00:00",
    )

    change = request_event_change(_event(fake), ORGANISER, {"changes": {"registration_needs": False}})

    assert change["requested_changes"] == {
        "registration_needs": False,
        "registration_start_datetime": None,
        "registration_end_datetime": None,
    }


def test_the_same_instant_in_another_timezone_is_not_a_change(fake):
    fake.rows[0].update(
        registration_needs=True,
        registration_start_datetime="2026-01-01T01:00:00+00:00",
        registration_end_datetime="2026-01-02T01:00:00+00:00",
    )

    with pytest.raises(ValidationError, match="same as the current"):
        request_event_change(
            _event(fake), ORGANISER, {"changes": {"registration_start_datetime": "2026-01-01T09:00:00+08:00"}}
        )


@pytest.mark.parametrize(
    "payload, message",
    [
        (None, "JSON object"),
        ({}, "at least one event detail"),
        ({"changes": {}}, "at least one event detail"),
        ({"changes": ["name"]}, "at least one event detail"),
        ({"changes": {"room_layout": "banquet"}, "status": "approved"}, "Unknown change request fields: status"),
        ({"changes": {"status": "approved"}}, "can't be changed: status"),
        ({"changes": {"coordinator_id": "me"}}, "can't be changed: coordinator_id"),
        ({"changes": {"expected_attendance": 0}}, "expected_attendance must be a positive integer"),
        ({"changes": {"room_layout": "stadium"}}, "room_layout must be one of"),
        ({"changes": {"preferred_end_date": "2000-01-01"}}, "preferred_end_date must be on or after"),
        ({"changes": {"name": ""}}, "name is required"),
        ({"changes": {"room_layout": "banquet"}, "reason": 5}, "reason must be a string"),
    ],
)
def test_invalid_change_requests_are_refused_and_nothing_is_recorded(fake, payload, message):
    with pytest.raises(ValidationError, match=message):
        request_event_change(_event(fake), ORGANISER, payload)
    assert _logs(fake) == []


def test_a_change_to_nothing_new_is_refused(fake):
    with pytest.raises(ValidationError, match="same as the current"):
        request_event_change(_event(fake), ORGANISER, {"changes": {"room_layout": "theatre"}})


def test_only_one_change_request_waits_for_review_per_session(fake):
    request_event_change(_event(fake), ORGANISER, {"changes": {"room_layout": "banquet"}})

    with pytest.raises(ChangeRequestConflictError) as exc_info:
        request_event_change(_event(fake), ORGANISER, {"changes": {"expected_attendance": 120}})
    assert exc_info.value.status_code == 409
    assert len(_logs(fake)) == 1

    # Another session of the same request has its own queue.
    request_event_change(_event(fake, "session-2"), ORGANISER, {"changes": {"expected_attendance": 120}})
    assert len(_logs(fake)) == 2


def test_a_new_change_may_be_requested_once_the_last_one_is_reviewed(fake):
    first = request_event_change(_event(fake), ORGANISER, {"changes": {"room_layout": "banquet"}})
    reject_change_request(_event(fake), first["event_change_req_id"], COORDINATOR, "No banquet rooms that day.")

    second = request_event_change(_event(fake), ORGANISER, {"changes": {"room_layout": "classroom"}})

    assert second["status"] == "pending"
    assert [row["status"] for row in _logs(fake)] == ["rejected", "pending"]


# -- viewing -------------------------------------------------------------------


def test_list_is_every_change_for_the_request_newest_first(fake):
    first = request_event_change(_event(fake), ORGANISER, {"changes": {"room_layout": "banquet"}})
    second = request_event_change(_event(fake, "session-2"), ORGANISER, {"changes": {"expected_attendance": 80}})
    first_row = next(row for row in _logs(fake) if row["event_change_req_id"] == first["event_change_req_id"])
    second_row = next(row for row in _logs(fake) if row["event_change_req_id"] == second["event_change_req_id"])
    first_row["created_at"], second_row["created_at"] = "2026-10-01T00:00:00Z", "2026-10-02T00:00:00Z"
    fake.tables["event_change_requests"].append(
        {"event_change_req_id": "elsewhere", "shared_event_id": "group-2", "event_id": "x"}
    )

    listed = list_change_requests(_event(fake), make_user(["event_coordinator"], user_id=COORDINATOR))

    assert [row["event_change_req_id"] for row in listed] == [
        second["event_change_req_id"],
        first["event_change_req_id"],
    ]


def test_list_hides_changes_on_sessions_the_caller_cannot_see(fake):
    fake.tables["event_change_requests"] = [
        {
            "event_change_req_id": "mine",
            "event_id": "session-1",
            "shared_event_id": "group-1",
            "status": "approved",
        },
        {
            "event_change_req_id": "theirs",
            "event_id": "other-org-session",
            "shared_event_id": "group-1",
            "status": "approved",
        },
    ]

    listed = list_change_requests(_event(fake), make_user(["event_organizer"], user_id=ORGANISER))

    assert [row["event_change_req_id"] for row in listed] == ["mine"]


# -- reviewing ------------------------------------------------------------------


def test_approving_writes_the_change_to_the_session(fake):
    change = request_event_change(_event(fake), ORGANISER, {"changes": {"expected_attendance": 150}})

    result = approve_change_request(_event(fake), change["event_change_req_id"], COORDINATOR, "  Room fits 150.  ")

    assert fake.get("session-1")["expected_attendance"] == 150
    assert fake.get("session-2")["expected_attendance"] == 100  # per-session field: siblings untouched
    assert result["event"]["expected_attendance"] == 150
    assert result["change_request"]["status"] == "approved"
    assert result["change_request"]["reviewed_by"] == COORDINATOR
    assert result["change_request"]["review_comment"] == "Room fits 150."
    assert result["change_request"]["reviewed_at"]


def test_approving_a_shared_detail_renames_every_session_of_the_request(fake):
    change = request_event_change(_event(fake), ORGANISER, {"changes": {"name": "Community Summit"}})

    approve_change_request(_event(fake), change["event_change_req_id"], COORDINATOR)

    assert fake.get("session-1")["name"] == "Community Summit"
    assert fake.get("session-2")["name"] == "Community Summit"
    # Scoped to the organiser's own sessions, never someone else's row.
    assert fake.get("other-org-session")["name"] == "Community Conference"


def test_approved_equipment_change_lands_in_equipment_needed(fake):
    change = request_event_change(
        _event(fake), ORGANISER, {"changes": {"equipment": [{"item": "screen", "quantity": 2}]}}
    )

    approve_change_request(
        _event(fake), change["event_change_req_id"], COORDINATOR, acknowledge_impacts=["equipment", "technical_support"]
    )

    assert fake.get("session-1")["equipment_needed"] == {"equipment": [{"item": "screen", "quantity": 2}]}


def test_rejecting_keeps_the_event_as_it_was_and_records_the_reason(fake):
    change = request_event_change(_event(fake), ORGANISER, {"changes": {"room_layout": "banquet"}})
    before = dict(fake.get("session-1"))

    rejected = reject_change_request(
        _event(fake), change["event_change_req_id"], COORDINATOR, " Venue is booked as theatre. "
    )

    assert fake.get("session-1") == before
    assert rejected["status"] == "rejected"
    assert rejected["review_comment"] == "Venue is booked as theatre."
    assert rejected["reviewed_by"] == COORDINATOR


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_rejecting_needs_a_reason(fake, reason):
    change = request_event_change(_event(fake), ORGANISER, {"changes": {"room_layout": "banquet"}})

    with pytest.raises(ValidationError, match="reason is required"):
        reject_change_request(_event(fake), change["event_change_req_id"], COORDINATOR, reason)
    assert _logs(fake)[0]["status"] == "pending"


@pytest.mark.parametrize("first", ["approve", "reject"])
def test_a_change_is_reviewed_once(fake, first):
    change = request_event_change(_event(fake), ORGANISER, {"changes": {"room_layout": "banquet"}})
    if first == "approve":
        approve_change_request(
            _event(fake), change["event_change_req_id"], COORDINATOR, acknowledge_impacts=["technical_support"]
        )
    else:
        reject_change_request(_event(fake), change["event_change_req_id"], COORDINATOR, "No.")

    with pytest.raises(ChangeRequestConflictError):
        approve_change_request(_event(fake), change["event_change_req_id"], COORDINATOR)
    with pytest.raises(ChangeRequestConflictError):
        reject_change_request(_event(fake), change["event_change_req_id"], COORDINATOR, "No.")


def test_a_decision_that_loses_the_race_writes_nothing(fake, monkeypatch):
    """Between loading the change and claiming it, someone else decided it:
    the conditional claim matches no row, and the event isn't written."""
    change = request_event_change(_event(fake), ORGANISER, {"changes": {"expected_attendance": 150}})
    real_load = service._load_change

    def load_then_lose_race(event, change_id):
        loaded = real_load(event, change_id)
        fake.tables["event_change_requests"][0]["status"] = "rejected"
        return loaded

    monkeypatch.setattr(service, "_load_change", load_then_lose_race)

    with pytest.raises(ChangeRequestConflictError):
        approve_change_request(_event(fake), change["event_change_req_id"], COORDINATOR)
    assert fake.get("session-1")["expected_attendance"] == 100


def test_a_change_filed_on_another_session_is_not_found_here(fake):
    change = request_event_change(_event(fake, "session-2"), ORGANISER, {"changes": {"expected_attendance": 80}})

    with pytest.raises(NotFoundError):
        approve_change_request(_event(fake), change["event_change_req_id"], COORDINATOR)
    with pytest.raises(NotFoundError):
        reject_change_request(_event(fake), "no-such-change", COORDINATOR, "No.")


def test_approval_is_revalidated_against_the_event_as_it_is_now(fake):
    """The coordinator edited the session after the change was requested, so
    the requested end date now falls before the start: refused, nothing
    written, still pending."""
    change = request_event_change(_event(fake), ORGANISER, {"changes": {"preferred_end_date": LATER}})
    much_later = (date.today() + timedelta(days=40)).isoformat()
    fake.rows[0].update(preferred_start_date=much_later, preferred_end_date=much_later)

    with pytest.raises(ValidationError, match="preferred_end_date must be on or after"):
        approve_change_request(_event(fake), change["event_change_req_id"], COORDINATOR)
    assert fake.get("session-1")["preferred_end_date"] == much_later
    assert _logs(fake)[0]["status"] == "pending"


# -- routes ----------------------------------------------------------------------


def _mock_profile(monkeypatch, roles):
    monkeypatch.setattr(
        context_module,
        "_load_profile_with_roles",
        lambda user_id: ("Test User", "test@example.com", frozenset(roles)),
    )
    monkeypatch.setattr(context_module, "_get_last_active", lambda session_id: None)
    monkeypatch.setattr(context_module, "_touch_session_activity", lambda *a, **k: None)


def _auth(signing_key, user_id):
    return {"Authorization": f"Bearer {signing_key.make_token(sub=user_id)}"}


def test_create_route_records_a_change_for_the_organiser(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch, ["event_organizer"])

    response = client.post(
        "/events/session-1/change-requests",
        headers=_auth(signing_key, ORGANISER),
        json={"changes": {"room_layout": "banquet"}, "reason": "Dinner added."},
    )

    assert response.status_code == 201
    body = response.get_json()
    assert body["status"] == "pending"
    assert body["requested_by"] == ORGANISER
    assert body["requested_changes"] == {"room_layout": "banquet"}


def test_create_route_refuses_a_draft(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch, ["event_organizer"])
    fake.rows[0]["status"] = "draft"

    response = client.post(
        "/events/session-1/change-requests",
        headers=_auth(signing_key, ORGANISER),
        json={"changes": {"room_layout": "banquet"}},
    )

    assert response.status_code == 403
    assert _logs(fake) == []


def test_create_route_hides_another_organisers_event(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch, ["event_organizer"])

    response = client.post(
        "/events/session-1/change-requests",
        headers=_auth(signing_key, "org-2"),
        json={"changes": {"room_layout": "banquet"}},
    )

    assert response.status_code == 404


def test_create_route_reports_a_second_pending_change_as_409(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch, ["event_organizer"])
    headers = _auth(signing_key, ORGANISER)
    client.post("/events/session-1/change-requests", headers=headers, json={"changes": {"room_layout": "banquet"}})

    response = client.post(
        "/events/session-1/change-requests", headers=headers, json={"changes": {"expected_attendance": 99}}
    )

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "change_request_conflict"


def test_assigned_coordinator_lists_the_change_requests(client, signing_key, monkeypatch, fake):
    request_event_change(_event(fake), ORGANISER, {"changes": {"room_layout": "banquet"}})
    _mock_profile(monkeypatch, ["event_coordinator"])

    response = client.get("/events/session-1/change-requests", headers=_auth(signing_key, COORDINATOR))

    assert response.status_code == 200
    assert [row["requested_changes"] for row in response.get_json()] == [{"room_layout": "banquet"}]


def test_unrelated_coordinator_cannot_list_the_change_requests(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch, ["event_coordinator"])

    response = client.get("/events/session-1/change-requests", headers=_auth(signing_key, "coord-2"))

    assert response.status_code == 404


def test_organiser_cannot_approve_their_own_change(client, signing_key, monkeypatch, fake):
    change = request_event_change(_event(fake), ORGANISER, {"changes": {"room_layout": "banquet"}})
    _mock_profile(monkeypatch, ["event_organizer"])

    response = client.post(
        f"/events/session-1/change-requests/{change['event_change_req_id']}/approve",
        headers=_auth(signing_key, ORGANISER),
        json={},
    )

    assert response.status_code == 403
    assert fake.get("session-1")["room_layout"] == "theatre"


def test_reject_route_without_a_reason_is_400(client, signing_key, monkeypatch, fake):
    change = request_event_change(_event(fake), ORGANISER, {"changes": {"room_layout": "banquet"}})
    _mock_profile(monkeypatch, ["event_coordinator"])

    response = client.post(
        f"/events/session-1/change-requests/{change['event_change_req_id']}/reject",
        headers=_auth(signing_key, COORDINATOR),
        json={},
    )

    assert response.status_code == 400
    assert _logs(fake)[0]["status"] == "pending"


def test_reject_route_rejects_with_the_reason(client, signing_key, monkeypatch, fake):
    change = request_event_change(_event(fake), ORGANISER, {"changes": {"room_layout": "banquet"}})
    _mock_profile(monkeypatch, ["event_coordinator"])

    response = client.post(
        f"/events/session-1/change-requests/{change['event_change_req_id']}/reject",
        headers=_auth(signing_key, COORDINATOR),
        json={"reason": "Banquet layout doesn't fit the booked room."},
    )

    assert response.status_code == 200
    assert response.get_json()["status"] == "rejected"
    assert fake.get("session-1")["room_layout"] == "theatre"


def test_confirmed_event_changes_only_after_coordinator_approval(client, signing_key, monkeypatch, fake):
    """AC5 end to end: on a confirmed event the organiser's direct edit is
    refused and their change request leaves the event as it was; only the
    assigned coordinator's approval writes the new details."""
    _mock_profile(monkeypatch, ["event_organizer"])
    organiser = _auth(signing_key, ORGANISER)

    direct_edit = client.post(
        "/events/session-1", headers=organiser, json={"name": "Hijacked", "room_layout": "banquet"}
    )
    assert direct_edit.status_code == 403

    requested = client.post(
        "/events/session-1/change-requests", headers=organiser, json={"changes": {"room_layout": "banquet"}}
    )
    assert requested.status_code == 201
    assert fake.get("session-1")["room_layout"] == "theatre"

    _mock_profile(monkeypatch, ["event_coordinator"])
    approve_url = f"/events/session-1/change-requests/{requested.get_json()['event_change_req_id']}/approve"
    coordinator = _auth(signing_key, COORDINATOR)
    # The layout change touches the session's technical support (it has a
    # projector), so the coordinator is stopped until they acknowledge it.
    unacknowledged = client.post(approve_url, headers=coordinator, json={"comment": "Fine."})
    assert unacknowledged.status_code == 409
    assert unacknowledged.get_json()["error"]["code"] == "change_impact_unacknowledged"
    assert fake.get("session-1")["room_layout"] == "theatre"

    approved = client.post(
        approve_url, headers=coordinator, json={"comment": "Fine.", "acknowledge_impacts": ["technical_support"]}
    )

    assert approved.status_code == 200
    assert approved.get_json()["event"]["room_layout"] == "banquet"
    assert fake.get("session-1")["room_layout"] == "banquet"
    assert fake.get("session-1")["status"] == "confirmed"  # a change isn't a status change


# -- impact on arrangements already made ------------------------------------
# Before approving, the coordinator is shown what the change would disturb
# (venue booking, registrations, equipment, technical support), and must
# acknowledge each affected area.


def _book_venue(fake, *, status="confirmed", start="08:30", end="17:30", **venue):
    """A booking for session-1 covering 09:00-17:00 plus the usual 30 min
    setup/turnaround either side (booking_start/end are SGT, +08:00)."""
    fake.tables.setdefault("venue_bookings", []).append(
        {
            "id": "booking-1",
            "event_id": "session-1",
            "status": status,
            "setup_minutes": 30,
            "turnaround_minutes": 30,
            "booking_start": f"{FUTURE}T{start}:00+08:00",
            "booking_end": f"{FUTURE}T{end}:00+08:00",
            "venues": {
                "name": "Hall A",
                "capacity": 200,
                "supported_layouts": ["theatre", "classroom"],
                "accessibility_features": ["wheelchair_access"],
                **venue,
            },
        }
    )


def _register(fake, confirmed=0, waitlisted=0):
    rows = fake.tables.setdefault("registrations", [])
    rows += [{"event_id": "session-1", "status": "confirmed"} for _ in range(confirmed)]
    rows += [{"event_id": "session-1", "status": "waitlisted"} for _ in range(waitlisted)]


def _no_equipment(fake):
    fake.rows[0]["equipment_needed"] = {"equipment": []}


def _assess(fake, changes):
    return impact_module.assess_change_impact(_event(fake), changes)


def _coordinator():
    return make_user(["event_coordinator"], user_id=COORDINATOR)


def test_moving_the_session_outside_its_venue_booking_is_flagged(fake):
    _no_equipment(fake)
    _book_venue(fake)

    [impact] = _assess(fake, {"preferred_end_time": "19:00:00"})

    assert impact["area"] == "venue"
    assert impact["severity"] == "conflict"
    assert impact["booking_id"] == "booking-1"
    assert "Hall A (confirmed)" in impact["title"]
    assert "will not move automatically" in impact["issues"][0]
    assert "19:30" in impact["issues"][0]  # the new end plus turnaround


def test_a_timing_change_that_still_fits_the_booking_is_not_flagged(fake):
    _no_equipment(fake)
    _book_venue(fake)

    assert _assess(fake, {"preferred_start_time": "10:00:00"}) == []


def test_a_pending_booking_counts_but_a_rejected_one_does_not(fake):
    _no_equipment(fake)
    _book_venue(fake, status="pending")
    moved = {"preferred_start_date": LATER, "preferred_end_date": LATER}
    assert [impact["area"] for impact in _assess(fake, moved)] == ["venue"]

    fake.tables["venue_bookings"][0]["status"] = "rejected"
    assert _assess(fake, moved) == []


def test_venue_requirement_changes_are_checked_against_the_booked_venue(fake):
    _no_equipment(fake)
    _book_venue(fake)

    [impact] = _assess(
        fake,
        {
            "expected_attendance": 250,
            "room_layout": "banquet",
            "accessibility_needs": [{"item": "wheelchair_access"}, {"item": "lift_access"}],
        },
    )

    assert impact["issues"] == [
        "250 expected attendees exceeds the venue's capacity of 200.",
        "The venue doesn't support a banquet layout.",
        "The venue doesn't provide: lift access.",
    ]
    assert _assess(fake, {"expected_attendance": 180, "room_layout": "classroom"}) == []


def test_registered_attendees_are_flagged_when_the_timing_or_capacity_changes(fake):
    _no_equipment(fake)
    _register(fake, confirmed=3, waitlisted=1)

    [impact] = _assess(fake, {"preferred_start_time": "10:00:00", "expected_attendance": 2})

    assert impact["area"] == "registration"
    assert (impact["confirmed"], impact["waitlisted"]) == (3, 1)
    assert impact["issues"] == [
        "3 confirmed and 1 waitlisted attendee(s) registered for the current date and time.",
        "3 confirmed registrations exceed the new expected attendance of 2; they stay confirmed.",
    ]


def test_turning_registration_off_with_attendees_registered_is_flagged(fake):
    _no_equipment(fake)
    fake.rows[0]["registration_needs"] = True
    _register(fake, confirmed=2)

    [impact] = _assess(fake, {"registration_needs": False})

    assert "already registered" in impact["issues"][0]


def test_no_registrations_means_no_registration_impact(fake):
    _no_equipment(fake)
    assert _assess(fake, {"preferred_start_time": "10:00:00", "expected_attendance": 2}) == []


def test_equipment_and_technical_support_ask_for_a_manual_check(fake):
    """No allocation/assignment records exist for these yet, so they are
    flagged as "check", never as a conflict."""
    impacts = _assess(fake, {"equipment": [{"item": "microphone", "quantity": 2}]})

    assert [(i["area"], i["severity"]) for i in impacts] == [("equipment", "check"), ("technical_support", "check")]
    assert "microphones" in impacts[0]["issues"][0]


def test_a_session_without_equipment_needs_no_equipment_check(fake):
    _no_equipment(fake)
    assert _assess(fake, {"preferred_start_time": "10:00:00", "room_layout": "classroom"}) == []


def test_details_no_arrangement_depends_on_have_no_impact(fake):
    _book_venue(fake)
    _register(fake, confirmed=5)
    assert _assess(fake, {"name": "Community Summit", "special_requests": "Near the lift."}) == []


def test_nothing_is_arranged_before_approval(fake):
    fake.rows[0]["status"] = "under_review"
    _register(fake, confirmed=5)
    assert _assess(fake, {"equipment": [], "preferred_start_time": "10:00:00"}) == []


def test_pending_changes_are_listed_with_their_impact(fake):
    change = request_event_change(_event(fake), ORGANISER, {"changes": {"preferred_start_time": "10:00"}})
    fake.tables["event_change_requests"].append(
        {
            "event_change_req_id": "old",
            "shared_event_id": "group-1",
            "event_id": "session-1",
            "status": "approved",
            "requested_changes": {"equipment": []},
        }
    )

    listed = {row["event_change_req_id"]: row for row in list_change_requests(_event(fake), _coordinator())}

    assert [impact["area"] for impact in listed[change["event_change_req_id"]]["impact"]] == [
        "equipment",
        "technical_support",
    ]
    assert "impact" not in listed["old"]


def test_approval_waits_until_every_affected_area_is_acknowledged(fake):
    _book_venue(fake)
    change = request_event_change(_event(fake), ORGANISER, {"changes": {"preferred_end_time": "19:00"}})

    for acknowledged in (None, [], ["venue", "equipment"]):
        with pytest.raises(service.ChangeImpactNotAcknowledgedError) as exc_info:
            approve_change_request(
                _event(fake), change["event_change_req_id"], COORDINATOR, acknowledge_impacts=acknowledged
            )
        assert exc_info.value.status_code == 409
    assert "technical support" in exc_info.value.message
    assert fake.get("session-1")["preferred_end_time"] == "17:00:00"
    assert _logs(fake)[0]["status"] == "pending"

    result = approve_change_request(
        _event(fake),
        change["event_change_req_id"],
        COORDINATOR,
        acknowledge_impacts=["venue", "equipment", "technical_support"],
    )

    assert fake.get("session-1")["preferred_end_time"] == "19:00:00"
    recorded = result["change_request"]["acknowledged_impacts"]
    assert [impact["area"] for impact in recorded] == ["venue", "equipment", "technical_support"]


def test_an_impact_that_appears_after_the_page_loaded_must_be_acknowledged_too(fake):
    change = request_event_change(_event(fake), ORGANISER, {"changes": {"preferred_start_time": "10:00"}})
    shown = [impact["area"] for impact in list_change_requests(_event(fake), _coordinator())[0]["impact"]]
    _register(fake, confirmed=1)  # someone registers in the meantime

    with pytest.raises(service.ChangeImpactNotAcknowledgedError, match="registration"):
        approve_change_request(_event(fake), change["event_change_req_id"], COORDINATOR, acknowledge_impacts=shown)
    assert _logs(fake)[0]["status"] == "pending"


def test_a_change_with_no_impact_is_approved_without_acknowledgement(fake):
    _book_venue(fake)
    change = request_event_change(_event(fake), ORGANISER, {"changes": {"name": "Community Summit"}})

    result = approve_change_request(_event(fake), change["event_change_req_id"], COORDINATOR)

    assert result["change_request"]["acknowledged_impacts"] is None


def test_acknowledge_impacts_must_be_a_list_of_areas(fake):
    change = request_event_change(_event(fake), ORGANISER, {"changes": {"room_layout": "banquet"}})
    with pytest.raises(ValidationError, match="list of impact areas"):
        approve_change_request(_event(fake), change["event_change_req_id"], COORDINATOR, acknowledge_impacts=True)
