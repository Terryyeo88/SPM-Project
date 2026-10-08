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


def _change_requests(fake: FakeSupabase) -> list[dict]:
    return fake.tables.get("event_change_requests", [])


# -- authz: who may request, who may review ---------------------------------


@pytest.mark.parametrize("status", CHANGE_REQUEST_STATUSES)
def test_organiser_may_request_a_change_once_submitted(status):
    """AC1: the owning organiser is allowed to request a change at every
    stage from submitted through confirmed (one run per status)."""
    organiser = make_user(["event_organizer"], user_id=ORGANISER)
    assert can(organiser, actions.EVENT_REQUEST_CHANGE, FakeEvent(organizer_id=ORGANISER, status=status))


@pytest.mark.parametrize("status", ["draft", "rejected", "completed", "cancelled"])
def test_request_change_refused_outside_the_submitted_window(status):
    """AC1: the organiser is refused (403) in every other status. Drafts and
    rejected sessions are edited directly instead; completed and cancelled
    events have nothing left to change."""
    organiser = make_user(["event_organizer"], user_id=ORGANISER)
    with pytest.raises(AuthorisationError):
        authorise(organiser, actions.EVENT_REQUEST_CHANGE, FakeEvent(organizer_id=ORGANISER, status=status))


def test_request_change_hidden_from_another_organiser():
    """An organiser who doesn't own the event gets a 404, so they can't even
    tell it exists."""
    other = make_user(["event_organizer"], user_id="org-2")
    with pytest.raises(NotFoundError):
        authorise(other, actions.EVENT_REQUEST_CHANGE, FakeEvent(organizer_id=ORGANISER, status="confirmed"))


def test_coordinator_cannot_request_a_change_on_the_organisers_behalf():
    """Only the organiser requests changes. The assigned coordinator is
    refused with a 403 (not a 404) because they can already see the event."""
    coordinator = make_user(["event_coordinator"], user_id=COORDINATOR)
    event = FakeEvent(organizer_id=ORGANISER, coordinator_id=COORDINATOR, status="planning")
    with pytest.raises(AuthorisationError):  # 403: they can already see it
        authorise(coordinator, actions.EVENT_REQUEST_CHANGE, event)


@pytest.mark.parametrize("status", CHANGE_REQUEST_STATUSES)
def test_assigned_coordinator_may_review_a_change(status):
    """AC4: the assigned coordinator is allowed to review a change request at
    every stage a change can be requested in."""
    coordinator = make_user(["event_coordinator"], user_id=COORDINATOR)
    event = FakeEvent(organizer_id=ORGANISER, coordinator_id=COORDINATOR, status=status)
    assert can(coordinator, actions.EVENT_REVIEW_CHANGE, event)


@pytest.mark.parametrize("status", ["completed", "cancelled", "rejected"])
def test_review_refused_once_the_event_has_moved_on(status):
    """Once the event is completed, cancelled or rejected, even the assigned
    coordinator can no longer review a change on it."""
    coordinator = make_user(["event_coordinator"], user_id=COORDINATOR)
    event = FakeEvent(organizer_id=ORGANISER, coordinator_id=COORDINATOR, status=status)
    with pytest.raises(AuthorisationError):
        authorise(coordinator, actions.EVENT_REVIEW_CHANGE, event)


def test_only_the_assigned_coordinator_reviews():
    """AC4: only the ASSIGNED coordinator reviews. Another coordinator gets a
    404; the organiser and the Coordinator Lead can see the event, so they get
    a 403 instead."""
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
    """AC3: a request is saved as a pending row linked to both the whole event
    request (shared_event_id) and the session to change (event_id), with
    who asked, the new and old values, and the trimmed reason."""
    change = request_event_change(
        _event(fake), ORGANISER, {"changes": {"expected_attendance": 150}, "reason": "  More sign-ups.  "}
    )

    assert _change_requests(fake) == [change]
    assert change["shared_event_id"] == "group-1"
    assert change["event_id"] == "session-1"
    assert change["status"] == "pending"
    assert change["requested_by"] == ORGANISER
    assert change["requested_changes"] == {"expected_attendance": 150}
    assert change["previous_values"] == {"expected_attendance": 100}
    assert change["reason"] == "More sign-ups."


def test_requesting_a_change_does_not_touch_the_event(fake):
    """AC5: filing a request never writes to the events table -- the event
    keeps its current details until a coordinator approves."""
    before = dict(fake.get("session-1"))

    request_event_change(_event(fake), ORGANISER, {"changes": {"expected_attendance": 150, "room_layout": "banquet"}})

    assert fake.get("session-1") == before
    assert not [call for call in fake.calls if call["table"] == "events" and call["op"] != "select"]


def test_legacy_event_without_shared_event_id_is_a_group_of_one(fake):
    """An old event created before sessions existed has no shared_event_id,
    so the request is grouped under the event's own id instead."""
    fake.rows.append(_session(id="legacy-1", shared_event_id=None))

    change = request_event_change(_event(fake, "legacy-1"), ORGANISER, {"changes": {"room_layout": "classroom"}})

    assert change["shared_event_id"] == "legacy-1"


def test_request_records_only_the_details_that_change(fake):
    """AC2: fields sent with their current value (attendance 100, a 09:00
    start written differently) are dropped -- only the real change, the
    room layout, is recorded."""
    change = request_event_change(
        _event(fake),
        ORGANISER,
        {"changes": {"expected_attendance": 100, "room_layout": "banquet", "preferred_start_time": "09:00"}},
    )

    assert change["requested_changes"] == {"room_layout": "banquet"}
    assert change["previous_values"] == {"room_layout": "theatre"}


def test_several_details_can_be_changed_in_one_request(fake):
    """AC2: one request can change several details at once (name, equipment,
    special requests), each recorded with its old value."""
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
    """Turning registration off also clears the registration window, so the
    request records those two knock-on changes as well."""
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
    """The same moment written in another timezone (01:00 UTC vs 09:00
    Singapore time) is not a change, so the request is refused as changing
    nothing."""
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
        ({"changes": {"organizer_id": "someone-else"}}, "can't be changed: organizer_id"),
        ({"changes": {"shared_event_id": "group-9"}}, "can't be changed: shared_event_id"),
        ({"changes": {"id": "session-9"}}, "can't be changed: id"),
        ({"changes": {"expected_attendance": 0}}, "expected_attendance must be a positive integer"),
        ({"changes": {"room_layout": "stadium"}}, "room_layout must be one of"),
        ({"changes": {"preferred_end_date": "2000-01-01"}}, "preferred_end_date must be on or after"),
        ({"changes": {"name": ""}}, "name is required"),
        ({"changes": {"room_layout": "banquet"}, "reason": 5}, "reason must be a string"),
    ],
)
def test_invalid_change_requests_are_refused_and_nothing_is_recorded(fake, payload, message):
    """AC1/AC2: each malformed or forbidden request is refused with a clear
    message and nothing is saved -- e.g. no changes given, fields the
    organiser may never change (status, coordinator, owner, ids), or values
    that fail the normal event rules."""
    with pytest.raises(ValidationError, match=message):
        request_event_change(_event(fake), ORGANISER, payload)
    assert _change_requests(fake) == []


def test_a_change_to_nothing_new_is_refused(fake):
    """Asking to "change" a field to the value it already has is refused."""
    with pytest.raises(ValidationError, match="same as the current"):
        request_event_change(_event(fake), ORGANISER, {"changes": {"room_layout": "theatre"}})


def test_only_one_change_request_waits_for_review_per_session(fake):
    """A session can have only one pending request at a time (a second is a
    409), but another session of the same event has its own queue."""
    request_event_change(_event(fake), ORGANISER, {"changes": {"room_layout": "banquet"}})

    with pytest.raises(ChangeRequestConflictError) as exc_info:
        request_event_change(_event(fake), ORGANISER, {"changes": {"expected_attendance": 120}})
    assert exc_info.value.status_code == 409
    assert len(_change_requests(fake)) == 1

    # Another session of the same request has its own queue.
    request_event_change(_event(fake, "session-2"), ORGANISER, {"changes": {"expected_attendance": 120}})
    assert len(_change_requests(fake)) == 2


def test_a_new_change_may_be_requested_once_the_last_one_is_reviewed(fake):
    """Once the pending request has been reviewed (here, rejected) the
    organiser can file a new one for the same session."""
    first = request_event_change(_event(fake), ORGANISER, {"changes": {"room_layout": "banquet"}})
    reject_change_request(_event(fake), first["event_change_req_id"], COORDINATOR, "No banquet rooms that day.")

    second = request_event_change(_event(fake), ORGANISER, {"changes": {"room_layout": "classroom"}})

    assert second["status"] == "pending"
    assert [row["status"] for row in _change_requests(fake)] == ["rejected", "pending"]


# -- viewing -------------------------------------------------------------------


def test_list_is_every_change_for_the_request_newest_first(fake):
    """The list covers every session of the event request, newest first, and
    leaves out requests belonging to other events."""
    first = request_event_change(_event(fake), ORGANISER, {"changes": {"room_layout": "banquet"}})
    second = request_event_change(_event(fake, "session-2"), ORGANISER, {"changes": {"expected_attendance": 80}})
    first_row = next(
        row for row in _change_requests(fake) if row["event_change_req_id"] == first["event_change_req_id"]
    )
    second_row = next(
        row for row in _change_requests(fake) if row["event_change_req_id"] == second["event_change_req_id"]
    )
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
    """The person asking for the list -- here organiser org-1 -- only gets
    change requests on sessions THEY are allowed to view.

    The fixture's "other-org-session" shares org-1's event request
    (group-1) but belongs to a different organiser (org-2) and coordinator
    (coord-2). The request filed on it ("theirs") is dropped, so org-1 sees
    only "mine". In practice every session of a request has the same
    organiser (the server generates shared_event_id), so this is a
    safety check that the list can never leak another organiser's data."""
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
    """AC4: approving writes the requested value to that session only (not
    its sibling sessions) and records the decision: approved, by whom,
    when, and the trimmed comment."""
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
    """The name is shared by every session, so approving a name change renames
    all of the organiser's sessions -- but never another organiser's row."""
    change = request_event_change(_event(fake), ORGANISER, {"changes": {"name": "Community Summit"}})

    approve_change_request(_event(fake), change["event_change_req_id"], COORDINATOR)

    assert fake.get("session-1")["name"] == "Community Summit"
    assert fake.get("session-2")["name"] == "Community Summit"
    # Scoped to the organiser's own sessions, never someone else's row.
    assert fake.get("other-org-session")["name"] == "Community Conference"


def test_approved_equipment_change_lands_in_equipment_needed(fake):
    """An approved "equipment" change is stored in the event's
    equipment_needed column, in the shape the rest of the app reads."""
    change = request_event_change(
        _event(fake), ORGANISER, {"changes": {"equipment": [{"item": "screen", "quantity": 2}]}}
    )

    approve_change_request(
        _event(fake), change["event_change_req_id"], COORDINATOR, acknowledge_impacts=["equipment", "technical_support"]
    )

    assert fake.get("session-1")["equipment_needed"] == {"equipment": [{"item": "screen", "quantity": 2}]}


def test_rejecting_keeps_the_event_as_it_was_and_records_the_reason(fake):
    """AC4: rejecting leaves the event exactly as it was and records the
    decision with the coordinator's trimmed reason."""
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
    """Rejecting without a reason (missing, empty or blank) is refused and the
    request stays pending."""
    change = request_event_change(_event(fake), ORGANISER, {"changes": {"room_layout": "banquet"}})

    with pytest.raises(ValidationError, match="reason is required"):
        reject_change_request(_event(fake), change["event_change_req_id"], COORDINATOR, reason)
    assert _change_requests(fake)[0]["status"] == "pending"


@pytest.mark.parametrize("first", ["approve", "reject"])
def test_a_change_is_reviewed_once(fake, first):
    """Once a request is approved or rejected it can't be decided again --
    a second approve or reject is a 409 conflict."""
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
    """A request can only be reviewed through the session it was filed
    against; using another session's URL (or an unknown id) is a 404."""
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
    assert _change_requests(fake)[0]["status"] == "pending"


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
    """AC1/AC3 through the API: POST /change-requests returns 201, saves the
    request against this session and its event request, and the organiser
    can then see it in the list."""
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
    assert body["previous_values"] == {"room_layout": "theatre"}
    assert body["reason"] == "Dinner added."
    # Recorded for the relevant event: the session and its whole request.
    assert (body["event_id"], body["shared_event_id"]) == ("session-1", "group-1")
    assert _change_requests(fake) == [body]

    # ...and the organiser can follow it afterwards.
    listed = client.get("/events/session-1/change-requests", headers=_auth(signing_key, ORGANISER))
    assert [row["event_change_req_id"] for row in listed.get_json()] == [body["event_change_req_id"]]


def test_create_route_refuses_a_draft(client, signing_key, monkeypatch, fake):
    """Through the API, a request on a draft is a 403 and nothing is saved."""
    _mock_profile(monkeypatch, ["event_organizer"])
    fake.rows[0]["status"] = "draft"

    response = client.post(
        "/events/session-1/change-requests",
        headers=_auth(signing_key, ORGANISER),
        json={"changes": {"room_layout": "banquet"}},
    )

    assert response.status_code == 403
    assert _change_requests(fake) == []


def test_create_route_hides_another_organisers_event(client, signing_key, monkeypatch, fake):
    """Through the API, another organiser trying to request a change gets a
    404."""
    _mock_profile(monkeypatch, ["event_organizer"])

    response = client.post(
        "/events/session-1/change-requests",
        headers=_auth(signing_key, "org-2"),
        json={"changes": {"room_layout": "banquet"}},
    )

    assert response.status_code == 404


def test_create_route_reports_a_second_pending_change_as_409(client, signing_key, monkeypatch, fake):
    """Through the API, a second request while one is pending comes back as a
    409 with the change_request_conflict error code."""
    _mock_profile(monkeypatch, ["event_organizer"])
    headers = _auth(signing_key, ORGANISER)
    client.post("/events/session-1/change-requests", headers=headers, json={"changes": {"room_layout": "banquet"}})

    response = client.post(
        "/events/session-1/change-requests", headers=headers, json={"changes": {"expected_attendance": 99}}
    )

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "change_request_conflict"


def test_assigned_coordinator_lists_the_change_requests(client, signing_key, monkeypatch, fake):
    """AC4: the assigned coordinator can view the request with everything
    needed to review it -- what was asked, the before/after values, who
    asked, why, and its impact."""
    request_event_change(_event(fake), ORGANISER, {"changes": {"room_layout": "banquet"}, "reason": "Dinner added."})
    _mock_profile(monkeypatch, ["event_coordinator"])

    response = client.get("/events/session-1/change-requests", headers=_auth(signing_key, COORDINATOR))

    assert response.status_code == 200
    [change] = response.get_json()
    # Everything the coordinator needs to review it: what, before/after, who, why.
    assert change["requested_changes"] == {"room_layout": "banquet"}
    assert change["previous_values"] == {"room_layout": "theatre"}
    assert change["requested_by"] == ORGANISER
    assert change["reason"] == "Dinner added."
    assert change["status"] == "pending"
    assert "impact" in change


def test_unrelated_coordinator_cannot_list_the_change_requests(client, signing_key, monkeypatch, fake):
    """A coordinator not assigned to the event gets a 404 when listing its
    requests."""
    _mock_profile(monkeypatch, ["event_coordinator"])

    response = client.get("/events/session-1/change-requests", headers=_auth(signing_key, "coord-2"))

    assert response.status_code == 404


def test_organiser_cannot_approve_their_own_change(client, signing_key, monkeypatch, fake):
    """AC5: the organiser can't approve their own request (403), so the event
    is unchanged."""
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
    """Through the API, rejecting without a reason is a 400 and the request
    stays pending."""
    change = request_event_change(_event(fake), ORGANISER, {"changes": {"room_layout": "banquet"}})
    _mock_profile(monkeypatch, ["event_coordinator"])

    response = client.post(
        f"/events/session-1/change-requests/{change['event_change_req_id']}/reject",
        headers=_auth(signing_key, COORDINATOR),
        json={},
    )

    assert response.status_code == 400
    assert _change_requests(fake)[0]["status"] == "pending"


def test_reject_route_rejects_with_the_reason(client, signing_key, monkeypatch, fake):
    """Through the API, rejecting with a reason marks the request rejected and
    leaves the event unchanged."""
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
    """Moving the end time past what the venue booking holds is flagged as a
    venue conflict that names the booking and the new period needed
    (including turnaround), and warns the booking won't move by itself."""
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
    """A new time that still fits inside the booked period raises no
    warning."""
    _no_equipment(fake)
    _book_venue(fake)

    assert _assess(fake, {"preferred_start_time": "10:00:00"}) == []


def test_a_pending_booking_counts_but_a_rejected_one_does_not(fake):
    """A pending venue booking counts as an arrangement to warn about; a
    rejected booking doesn't."""
    _no_equipment(fake)
    _book_venue(fake, status="pending")
    moved = {"preferred_start_date": LATER, "preferred_end_date": LATER}
    assert [impact["area"] for impact in _assess(fake, moved)] == ["venue"]

    fake.tables["venue_bookings"][0]["status"] = "rejected"
    assert _assess(fake, moved) == []


def test_venue_requirement_changes_are_checked_against_the_booked_venue(fake):
    """New attendance, layout and accessibility needs are checked against the
    booked venue -- over capacity, unsupported layout and missing features
    are each flagged; values the venue supports are not."""
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
    """With attendees registered, changing the time is flagged, and so is
    lowering expected attendance below the confirmed registrations."""
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
    """Turning registration off while people are already registered is
    flagged."""
    _no_equipment(fake)
    fake.rows[0]["registration_needs"] = True
    _register(fake, confirmed=2)

    [impact] = _assess(fake, {"registration_needs": False})

    assert "already registered" in impact["issues"][0]


def test_no_registrations_means_no_registration_impact(fake):
    """With nobody registered, timing and attendance changes raise no
    registration warning."""
    _no_equipment(fake)
    assert _assess(fake, {"preferred_start_time": "10:00:00", "expected_attendance": 2}) == []


def test_equipment_and_technical_support_ask_for_a_manual_check(fake):
    """No allocation/assignment records exist for these yet, so they are
    flagged as "check", never as a conflict."""
    impacts = _assess(fake, {"equipment": [{"item": "microphone", "quantity": 2}]})

    assert [(i["area"], i["severity"]) for i in impacts] == [("equipment", "check"), ("technical_support", "check")]
    assert "microphones" in impacts[0]["issues"][0]


def test_a_session_without_equipment_needs_no_equipment_check(fake):
    """A session that needs no equipment gets no equipment or technical
    support check."""
    _no_equipment(fake)
    assert _assess(fake, {"preferred_start_time": "10:00:00", "room_layout": "classroom"}) == []


def test_details_no_arrangement_depends_on_have_no_impact(fake):
    """Changing details no arrangement depends on (name, special requests)
    raises no warning, even with a venue booked and attendees registered."""
    _book_venue(fake)
    _register(fake, confirmed=5)
    assert _assess(fake, {"name": "Community Summit", "special_requests": "Near the lift."}) == []


def test_nothing_is_arranged_before_approval(fake):
    """Before the event is approved nothing has been arranged yet, so no
    warnings are raised."""
    fake.rows[0]["status"] = "under_review"
    _register(fake, confirmed=5)
    assert _assess(fake, {"equipment": [], "preferred_start_time": "10:00:00"}) == []


def test_pending_changes_are_listed_with_their_impact(fake):
    """The list attaches the impact to pending requests only, so the
    coordinator sees it before deciding; decided ones carry none."""
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
    """Approval is refused (409) until the coordinator acknowledges EVERY
    affected area; nothing is written meanwhile. With all acknowledged it
    goes through and the acknowledged impacts are saved on the request."""
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
    assert _change_requests(fake)[0]["status"] == "pending"

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
    """If something new is affected after the coordinator loaded the page
    (here, someone registers), approving with only the areas they saw is
    refused."""
    change = request_event_change(_event(fake), ORGANISER, {"changes": {"preferred_start_time": "10:00"}})
    shown = [impact["area"] for impact in list_change_requests(_event(fake), _coordinator())[0]["impact"]]
    _register(fake, confirmed=1)  # someone registers in the meantime

    with pytest.raises(service.ChangeImpactNotAcknowledgedError, match="registration"):
        approve_change_request(_event(fake), change["event_change_req_id"], COORDINATOR, acknowledge_impacts=shown)
    assert _change_requests(fake)[0]["status"] == "pending"


def test_a_change_with_no_impact_is_approved_without_acknowledgement(fake):
    """A change that affects no arrangement is approved without any
    acknowledgement, and none is recorded."""
    _book_venue(fake)
    change = request_event_change(_event(fake), ORGANISER, {"changes": {"name": "Community Summit"}})

    result = approve_change_request(_event(fake), change["event_change_req_id"], COORDINATOR)

    assert result["change_request"]["acknowledged_impacts"] is None


def test_acknowledge_impacts_must_be_a_list_of_areas(fake):
    """acknowledge_impacts must be a list of area names -- a plain true is
    refused."""
    change = request_event_change(_event(fake), ORGANISER, {"changes": {"room_layout": "banquet"}})
    with pytest.raises(ValidationError, match="list of impact areas"):
        approve_change_request(_event(fake), change["event_change_req_id"], COORDINATOR, acknowledge_impacts=True)


# -- acceptance criteria, end to end through the routes ------------------------


@pytest.mark.parametrize("status", CHANGE_REQUEST_STATUSES)
def test_ac1_a_change_can_be_requested_at_every_stage_after_submission(client, signing_key, monkeypatch, fake, status):
    """AC1: "request permitted changes for an event that has been submitted"
    -- from submitted (no coordinator yet) through to confirmed."""
    fake.rows[0].update(status=status, coordinator_id=None if status == "submitted" else COORDINATOR)
    _mock_profile(monkeypatch, ["event_organizer"])

    response = client.post(
        "/events/session-1/change-requests",
        headers=_auth(signing_key, ORGANISER),
        json={"changes": {"expected_attendance": 120}},
    )

    assert response.status_code == 201
    assert response.get_json()["status"] == "pending"


@pytest.mark.parametrize("status", ["draft", "rejected", "completed", "cancelled"])
def test_ac1_no_change_request_outside_the_submitted_window(client, signing_key, monkeypatch, fake, status):
    """Drafts and rejected sessions are edited directly instead; completed
    and cancelled events can't change. Refused, and nothing is recorded."""
    fake.rows[0]["status"] = status
    _mock_profile(monkeypatch, ["event_organizer"])

    response = client.post(
        "/events/session-1/change-requests",
        headers=_auth(signing_key, ORGANISER),
        json={"changes": {"expected_attendance": 120}},
    )

    assert response.status_code == 403
    assert _change_requests(fake) == []


def test_ac4_a_request_waiting_for_a_coordinator_is_reviewable_by_nobody_yet(client, signing_key, monkeypatch, fake):
    """Submitted but not yet assigned: the request is recorded, but only an
    ASSIGNED coordinator reviews -- not any coordinator, and not the Lead
    (who can still see it)."""
    fake.rows[0].update(status="submitted", coordinator_id=None)
    change = request_event_change(_event(fake), ORGANISER, {"changes": {"expected_attendance": 120}})
    approve_url = f"/events/session-1/change-requests/{change['event_change_req_id']}/approve"

    _mock_profile(monkeypatch, ["event_coordinator"])
    assert client.post(approve_url, headers=_auth(signing_key, COORDINATOR), json={}).status_code == 404

    _mock_profile(monkeypatch, ["event_coordinator_lead"])
    lead = _auth(signing_key, "lead-1")
    assert client.get("/events/session-1/change-requests", headers=lead).status_code == 200
    assert client.post(approve_url, headers=lead, json={}).status_code == 403

    assert _change_requests(fake)[0]["status"] == "pending"
    assert fake.get("session-1")["expected_attendance"] == 100


def test_ac4_the_assigned_coordinator_reviews_through_the_routes(client, signing_key, monkeypatch, fake):
    """View, then review: one change approved (applied), another rejected
    (not applied, reason kept) -- each by the assigned coordinator."""
    first = request_event_change(_event(fake), ORGANISER, {"changes": {"expected_attendance": 120}})
    second = request_event_change(_event(fake, "session-2"), ORGANISER, {"changes": {"room_layout": "banquet"}})
    _mock_profile(monkeypatch, ["event_coordinator"])
    coordinator = _auth(signing_key, COORDINATOR)

    listed = client.get("/events/session-1/change-requests", headers=coordinator).get_json()
    assert {row["event_change_req_id"] for row in listed} == {
        first["event_change_req_id"],
        second["event_change_req_id"],
    }

    approved = client.post(
        f"/events/session-1/change-requests/{first['event_change_req_id']}/approve", headers=coordinator, json={}
    )
    rejected = client.post(
        f"/events/session-2/change-requests/{second['event_change_req_id']}/reject",
        headers=coordinator,
        json={"reason": "No banquet rooms free that day."},
    )

    assert approved.status_code == 200 and rejected.status_code == 200
    assert fake.get("session-1")["expected_attendance"] == 120
    assert fake.get("session-2")["room_layout"] == "theatre"
    statuses = {row["event_change_req_id"]: row for row in _change_requests(fake)}
    assert statuses[first["event_change_req_id"]]["status"] == "approved"
    assert statuses[second["event_change_req_id"]]["review_comment"] == "No banquet rooms free that day."
    assert all(row["reviewed_by"] == COORDINATOR and row["reviewed_at"] for row in statuses.values())


def test_ac5_the_organiser_cannot_save_over_a_confirmed_event_either_way(client, signing_key, monkeypatch, fake):
    """Both organiser edit routes refuse a confirmed event -- the details
    edit and the draft/rejected save -- and nothing is written."""
    _mock_profile(monkeypatch, ["event_organizer"])
    organiser = _auth(signing_key, ORGANISER)
    before = dict(fake.get("session-1"))

    edit = client.post("/events/session-1", headers=organiser, json={"name": "Overwritten", "room_layout": "banquet"})
    save = client.post(
        "/events/session-1/draft",
        headers=organiser,
        json={"name": "Overwritten", "sessions": [{"id": "session-1", "room_layout": "banquet"}]},
    )

    assert (edit.status_code, save.status_code) == (403, 403)
    assert fake.get("session-1") == before


def test_ac5_a_pending_change_does_not_show_on_the_confirmed_event(client, signing_key, monkeypatch, fake):
    """Until it's reviewed, everyone reading the event still sees the
    confirmed details -- the requested values exist only on the request."""
    _mock_profile(monkeypatch, ["event_organizer"])
    organiser = _auth(signing_key, ORGANISER)
    client.post("/events/session-1/change-requests", headers=organiser, json={"changes": {"room_layout": "banquet"}})

    event = client.get("/events/session-1", headers=organiser).get_json()

    assert event["status"] == "confirmed"
    assert event["room_layout"] == "theatre"


def test_list_for_a_legacy_event_reads_only_its_own_requests(fake):
    """Listing requests for an old event without a shared_event_id returns
    just that event's own requests."""
    fake.rows.append(_session(id="legacy-1", shared_event_id=None))
    change = request_event_change(_event(fake, "legacy-1"), ORGANISER, {"changes": {"room_layout": "classroom"}})

    listed = list_change_requests(_event(fake, "legacy-1"), make_user(["event_organizer"], user_id=ORGANISER))

    assert [row["event_change_req_id"] for row in listed] == [change["event_change_req_id"]]


def test_a_new_registration_period_is_flagged_when_attendees_are_registered(fake):
    """Changing the registration period while attendees are registered is
    flagged."""
    _no_equipment(fake)
    fake.rows[0].update(
        registration_needs=True,
        registration_start_datetime=f"{FUTURE}T00:00:00+08:00",
        registration_end_datetime=f"{FUTURE}T08:00:00+08:00",
    )
    _register(fake, confirmed=2)

    [impact] = _assess(fake, {"registration_end_datetime": f"{FUTURE}T08:30:00+08:00"})

    assert impact["area"] == "registration"
    assert impact["issues"] == ["The registration period changes while 2 confirmed attendee(s) are registered."]
