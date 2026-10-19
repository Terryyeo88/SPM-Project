"""IS-9 Update Event Information During Planning.

"As an Event Coordinator, I want to update an event's information while it
is being planned so that the record stays the single accurate version
everyone works from."

Through the routes (POST /events/<id>, POST /events/<id>/update-preview)
where the acceptance criterion is about who may do what, and against
app.events.event_update directly otherwise. Unit-level: FakeSupabase stands
in for every module that reads or writes.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

import app.auth.context as context_module
import app.events.change_impact as impact_module
import app.events.event_log as event_log
import app.events.event_service as event_service
import app.events.event_update as event_update
import app.events.routes as routes_module
import app.events.transitions as transitions
from app.events.change_impact import ChangeImpactNotAcknowledgedError
from app.events.event_update import EventUpdateConflictError, preview_event_update, update_event
from app.shared.errors import ValidationError
from tests.fake_supabase import FakeSupabase

ORGANISER = "org-1"
COORDINATOR = "coord-1"
LEAD = "lead-1"
FUTURE = (date.today() + timedelta(days=30)).isoformat()
LATER = (date.today() + timedelta(days=31)).isoformat()


def _session(**overrides) -> dict:
    row = {
        "id": "session-1",
        "shared_event_id": "group-1",
        "organizer_id": ORGANISER,
        "coordinator_id": COORDINATOR,
        "status": "planning",
        "name": "Community Conference",
        "description": "A community conference.",
        "purpose": "Knowledge sharing.",
        "preferred_start_date": FUTURE,
        "preferred_end_date": FUTURE,
        "preferred_start_time": "09:00:00",
        "preferred_end_time": "17:00:00",
        "expected_attendance": 100,
        "accessibility_needs": [],
        "room_layout": "theatre",
        "equipment_needed": {"equipment": []},
        "registration_needs": False,
        "registration_start_datetime": None,
        "registration_end_datetime": None,
        "special_requests": None,
    }
    row.update(overrides)
    return row


@pytest.fixture
def fake(monkeypatch):
    db = FakeSupabase([_session(), _session(id="session-2", preferred_start_date=LATER, preferred_end_date=LATER)])
    for module in (impact_module, event_log, event_service, event_update, transitions, routes_module):
        monkeypatch.setattr(module, "supabase", db)
    return db


def _event(fake, event_id="session-1") -> SimpleNamespace:
    return SimpleNamespace(**dict(fake.get(event_id)))


def _logs(fake) -> list[dict]:
    return fake.tables.get("event_logs", [])


def _status_log(fake) -> list[dict]:
    return fake.tables.get("event_status_log", [])


def _writes(fake, table="events") -> list[dict]:
    return [call for call in fake.calls if call["table"] == table and call["op"] != "select"]


def _mock_profile(monkeypatch, roles):
    monkeypatch.setattr(
        context_module, "_load_profile_with_roles", lambda user_id: ("Test User", "t@example.com", frozenset(roles))
    )
    monkeypatch.setattr(context_module, "_get_last_active", lambda session_id: None)
    monkeypatch.setattr(context_module, "_touch_session_activity", lambda *a, **k: None)


def _auth(signing_key, user_id):
    return {"Authorization": f"Bearer {signing_key.make_token(sub=user_id)}"}


def _book_venue(fake, booking_id="booking-1", *, status="confirmed", capacity=200, start="08:30", end="17:30"):
    fake.tables.setdefault("venue_bookings", []).append(
        {
            "id": booking_id,
            "event_id": "session-1",
            "status": status,
            "setup_minutes": 30,
            "turnaround_minutes": 30,
            "booking_start": f"{FUTURE}T{start}:00+08:00",
            "booking_end": f"{FUTURE}T{end}:00+08:00",
            "venues": {
                "name": f"Hall {booking_id}",
                "capacity": capacity,
                "supported_layouts": ["theatre", "classroom"],
                "accessibility_features": [],
            },
        }
    )


def _request_equipment(fake, *, status="confirmed"):
    fake.tables.setdefault("equipment_requests", []).append(
        {
            "id": "equipment-request-1",
            "event_id": "session-1",
            "status": status,
            "needed_start": f"{FUTURE}T09:00:00+08:00",
            "needed_end": f"{FUTURE}T17:00:00+08:00",
        }
    )


# -- AC1: what can be updated during planning ------------------------------------


@pytest.mark.parametrize(
    "field,value",
    [
        ("name", "Community Summit"),
        ("description", "A bigger community conference."),
        ("purpose", "Networking."),
        ("preferred_start_date", LATER),
        ("preferred_end_date", LATER),
        ("preferred_start_time", "10:00:00"),
        ("preferred_end_time", "18:00:00"),
        ("expected_attendance", 150),
        ("room_layout", "classroom"),
        ("accessibility_needs", [{"item": "wheelchair_access"}]),
    ],
)
def test_ac1_the_coordinator_updates_each_detail_during_planning(client, signing_key, monkeypatch, fake, field, value):
    """AC1: name, description, category (purpose), preferred dates and
    times, expected attendance, venue requirements (room layout) and
    accessibility needs can each be updated while the event is in planning."""
    _mock_profile(monkeypatch, ["event_coordinator"])
    body = {field: value}
    if field == "preferred_start_date":
        body["preferred_end_date"] = LATER  # the end can't be before the start

    response = client.post("/events/session-1", headers=_auth(signing_key, COORDINATOR), json=body)

    assert response.status_code == 200, response.get_json()
    assert fake.get("session-1")[field] == value
    assert response.get_json()[field] == value


@pytest.mark.parametrize("status", ["under_review", "approved", "planning", "confirmed"])
def test_ac1_updates_are_open_until_the_event_is_finished(fake, status):
    """The coordinator can keep the record accurate at every stage before
    the event is completed or cancelled."""
    fake.rows[0]["status"] = status
    update_event(_event(fake), {"special_requests": "Vegetarian lunch."}, COORDINATOR)
    assert fake.get("session-1")["special_requests"] == "Vegetarian lunch."


# -- AC2: significant vs ordinary --------------------------------------------------


@pytest.mark.parametrize(
    "changes,expected",
    [
        ({"preferred_start_date": LATER, "preferred_end_date": LATER}, "significant"),
        ({"preferred_start_time": "10:00:00"}, "significant"),
        ({"preferred_end_time": "18:00:00"}, "significant"),
        ({"expected_attendance": 150}, "significant"),
        ({"room_layout": "classroom"}, "significant"),
        ({"equipment": [{"item": "microphone", "quantity": 2}]}, "significant"),
        ({"name": "Community Summit"}, "ordinary"),
        ({"description": "Updated."}, "ordinary"),
        ({"purpose": "Networking."}, "ordinary"),
        ({"accessibility_needs": [{"item": "lift_access"}]}, "ordinary"),
        ({"special_requests": "Vegetarian lunch."}, "ordinary"),
        ({"name": "Community Summit", "expected_attendance": 150}, "significant"),  # any one makes it significant
    ],
)
def test_ac2_each_update_is_recorded_as_significant_or_ordinary(fake, changes, expected):
    """AC2: changes to date, time, expected attendance, venue requirements
    or equipment requirements are recorded as significant; anything else as
    ordinary."""
    # Adding equipment is a "check manually" for equipment and technical support.
    update_event(_event(fake), changes, COORDINATOR, ["equipment", "technical_support"])

    [entry] = _logs(fake)
    assert entry["significance"] == expected


def test_ac2_the_history_reports_significance_even_for_older_entries(fake):
    """Entries written before significance was stored are still labelled,
    from the fields they changed."""
    fake.tables["event_logs"] = [
        {"event_log_id": "old", "shared_event_id": "group-1", "changes": {"expected_attendance": {"from": 1, "to": 2}}},
        {"event_log_id": "new", "shared_event_id": "group-1", "changes": {"name": {"from": "a", "to": "b"}}},
    ]
    listed = {entry["event_log_id"]: entry["significance"] for entry in event_log.list_event_logs(_event(fake))}
    assert listed == {"old": "significant", "new": "ordinary"}


# -- AC3: arrangements are presented before a significant change is committed -----


def test_ac3_the_preview_presents_every_arrangement_the_change_touches(fake):
    """AC3: before committing, the coordinator sees which already-made
    arrangements the change touches -- venue, equipment, technical support,
    registration -- and nothing is written by looking."""
    fake.rows[0]["equipment_needed"] = {"equipment": [{"item": "projector", "quantity": 1}]}
    _book_venue(fake)
    _request_equipment(fake)
    fake.tables["registrations"] = [{"event_id": "session-1", "status": "confirmed"}]

    preview = preview_event_update(_event(fake), {"preferred_end_time": "20:00"})

    assert preview["significance"] == "significant"
    assert preview["significant_fields"] == ["preferred_end_time"]
    assert preview["changes"] == {"preferred_end_time": {"from": "17:00:00", "to": "20:00:00"}}
    assert [impact["area"] for impact in preview["impacts"]] == [
        "venue",
        "registration",
        "equipment",
        "technical_support",
    ]
    assert _writes(fake) == [] and _logs(fake) == []


def test_ac3_a_significant_change_is_not_committed_until_its_impacts_are_acknowledged(fake):
    """AC3: saving a change that touches arrangements without naming each
    affected area is refused (409), and the event is left as it was."""
    _book_venue(fake, capacity=120)

    with pytest.raises(ChangeImpactNotAcknowledgedError, match="venue"):
        update_event(_event(fake), {"expected_attendance": 150}, COORDINATOR)
    with pytest.raises(ChangeImpactNotAcknowledgedError):
        update_event(_event(fake), {"expected_attendance": 150}, COORDINATOR, ["registration"])

    assert fake.get("session-1")["expected_attendance"] == 100
    assert _writes(fake) == [] and _logs(fake) == []


def test_ac3_once_acknowledged_the_change_is_saved_with_what_was_acknowledged(fake):
    """With every area acknowledged the change is saved, and the log keeps
    which arrangements the coordinator accepted it would disturb."""
    _book_venue(fake, capacity=120)

    update_event(_event(fake), {"expected_attendance": 150}, COORDINATOR, ["venue"])

    assert fake.get("session-1")["expected_attendance"] == 150
    [entry] = _logs(fake)
    assert [impact["area"] for impact in entry["acknowledged_impacts"]] == ["venue"]


def test_ac3_a_change_that_touches_nothing_arranged_needs_no_acknowledgement(fake):
    """A significant change with no arrangement in its way is saved straight
    away -- the preview says there is nothing to review."""
    assert preview_event_update(_event(fake), {"expected_attendance": 150})["impacts"] == []
    update_event(_event(fake), {"expected_attendance": 150}, COORDINATOR)
    assert fake.get("session-1")["expected_attendance"] == 150


def test_ac3_equipment_requests_already_made_are_checked_against_the_new_timing(fake):
    """An equipment request made for the old timing is a conflict, not just
    a manual check, now that requests are recorded."""
    _request_equipment(fake)

    [impact] = preview_event_update(_event(fake), {"preferred_end_time": "20:00"})["impacts"]

    assert (impact["area"], impact["severity"]) == ("equipment", "conflict")
    assert "will not move automatically" in impact["issues"][0]


def test_ac3_impacts_are_checked_through_the_route_too(client, signing_key, monkeypatch, fake):
    """End to end: the preview route lists the impact, the save without
    acknowledgement is a 409, and the save with it a 200."""
    _mock_profile(monkeypatch, ["event_coordinator"])
    _book_venue(fake, capacity=120)
    headers = _auth(signing_key, COORDINATOR)

    preview = client.post("/events/session-1/update-preview", headers=headers, json={"expected_attendance": 150})
    refused = client.post("/events/session-1", headers=headers, json={"expected_attendance": 150})
    saved = client.post(
        "/events/session-1", headers=headers, json={"expected_attendance": 150, "acknowledge_impacts": ["venue"]}
    )

    assert preview.status_code == 200
    assert [impact["area"] for impact in preview.get_json()["impacts"]] == ["venue"]
    assert refused.status_code == 409
    assert refused.get_json()["error"]["code"] == "change_impact_unacknowledged"
    assert saved.status_code == 200
    assert fake.get("session-1")["expected_attendance"] == 150



@pytest.mark.parametrize("status", ["under_review", "approved"])
def test_ac3_before_planning_the_coordinator_edits_freely(fake, status):
    """Before planning the details are still being settled: a significant
    change is saved straight away, even past an existing booking, with
    nothing to acknowledge -- but it is still logged as significant."""
    fake.rows[0]["status"] = status
    _book_venue(fake, capacity=120)
    fake.tables["registrations"] = [{"event_id": "session-1", "status": "confirmed"}]

    preview = preview_event_update(_event(fake), {"expected_attendance": 150, "preferred_end_time": "20:00"})
    update_event(_event(fake), {"expected_attendance": 150, "preferred_end_time": "20:00"}, COORDINATOR)

    assert preview["impacts"] == [] and preview["impacts_checked"] is False
    assert preview["significance"] == "significant"
    assert fake.get("session-1")["expected_attendance"] == 150
    [entry] = _logs(fake)
    assert entry["significance"] == "significant"
    assert not entry.get("acknowledged_impacts")


@pytest.mark.parametrize("status", ["planning", "confirmed"])
def test_ac3_from_planning_on_impacts_are_checked(fake, status):
    fake.rows[0]["status"] = status
    _book_venue(fake, capacity=120)

    preview = preview_event_update(_event(fake), {"expected_attendance": 150})

    assert preview["impacts_checked"] is True
    assert [impact["area"] for impact in preview["impacts"]] == ["venue"]
    with pytest.raises(ChangeImpactNotAcknowledgedError):
        update_event(_event(fake), {"expected_attendance": 150}, COORDINATOR)


def test_ac3_identical_equipment_requests_are_reported_once_not_once_each(fake):
    """Two pending requests for the same window would each produce the same
    sentence; they're reported once, with how many requests it covers."""
    _request_equipment(fake, status="pending")
    _request_equipment(fake, status="pending")
    fake.tables["equipment_requests"][1]["id"] = "equipment-request-2"

    impacts = preview_event_update(
        _event(fake),
        {
            "preferred_start_date": LATER,
            "preferred_end_date": LATER,
            "equipment": [{"item": "projector", "quantity": 1}],
        },
    )["impacts"]

    issues = next(impact for impact in impacts if impact["area"] == "equipment")["issues"]
    assert len(issues) == 2
    assert len(set(issues)) == 2
    assert issues[0].startswith("The 2 pending equipment requests cover ")
    assert issues[0].endswith("They will not move automatically.")
    assert issues[1].startswith("The 2 pending equipment requests were made for the previous equipment list")


def test_ac3_a_single_equipment_request_is_described_in_the_singular(fake):
    _request_equipment(fake, status="pending")

    impacts = preview_event_update(_event(fake), {"preferred_start_date": LATER, "preferred_end_date": LATER})[
        "impacts"
    ]

    issues = next(impact for impact in impacts if impact["area"] == "equipment")["issues"]
    assert len(issues) == 1
    assert issues[0].startswith("The pending equipment request covers ")
    assert issues[0].endswith("It will not move automatically.")


def test_ac3_arrangements_that_still_fit_are_presented_too(fake):
    """AC3: a significant change is shown against every arrangement it
    touches, even one it doesn't break -- a later finish that still falls
    inside the venue booking and equipment window is "touched", not "fine
    to ignore"."""
    _book_venue(fake, end="18:30")
    _request_equipment(fake)
    fake.tables["equipment_requests"][0]["needed_end"] = f"{FUTURE}T18:30:00+08:00"

    preview = preview_event_update(_event(fake), {"preferred_end_time": "18:00"})

    assert preview["impacts"] == []
    assert preview["arrangements"] == [
        {
            "area": "venue",
            "id": "booking-1",
            "title": "Venue booking: Hall booking-1",
            "status": "confirmed",
            "fields": ["preferred_end_time"],
        },
        {
            "area": "equipment",
            "id": "equipment-request-1",
            "title": "Equipment request",
            "status": "confirmed",
            "fields": ["preferred_end_time"],
        },
    ]
    assert _writes(fake) == [] and _logs(fake) == []


def test_ac3_registrations_are_presented_when_attendance_changes(fake):
    """AC3 (registration): a change to expected attendance touches the
    venue booking (capacity) and the registrations already taken."""
    _book_venue(fake)
    fake.tables["registrations"] = [
        {"event_id": "session-1", "status": "confirmed"},
        {"event_id": "session-1", "status": "confirmed"},
        {"event_id": "session-1", "status": "waitlisted"},
    ]

    arrangements = preview_event_update(_event(fake), {"expected_attendance": 150})["arrangements"]

    assert [(item["area"], item["fields"]) for item in arrangements] == [
        ("venue", ["expected_attendance"]),
        ("registration", ["expected_attendance"]),
    ]
    assert arrangements[1]["title"] == "Attendee registrations (2 confirmed, 1 waitlisted)"


def test_ac3_an_equipment_change_touches_equipment_requests_not_the_venue(fake):
    _book_venue(fake)
    _request_equipment(fake, status="pending")

    arrangements = preview_event_update(_event(fake), {"equipment": [{"item": "microphone", "quantity": 2}]})[
        "arrangements"
    ]

    assert [(item["area"], item["status"]) for item in arrangements] == [("equipment", "pending")]


def test_ac3_an_ordinary_change_touches_no_arrangement(fake):
    _book_venue(fake)
    _request_equipment(fake)
    fake.tables["registrations"] = [{"event_id": "session-1", "status": "confirmed"}]

    assert preview_event_update(_event(fake), {"name": "Community Summit"})["arrangements"] == []


def test_ac3_cancelled_and_rejected_arrangements_are_not_presented(fake):
    """Only arrangements still in place count: a cancelled or rejected
    booking holds nothing the change could touch."""
    _book_venue(fake, "booking-cancelled", status="cancelled")
    _book_venue(fake, "booking-rejected", status="rejected")
    _book_venue(fake, "booking-live")

    arrangements = preview_event_update(_event(fake), {"preferred_start_time": "09:30"})["arrangements"]

    assert [item["id"] for item in arrangements] == ["booking-live"]


@pytest.mark.parametrize("status", ["under_review", "approved"])
def test_ac3_no_arrangements_are_presented_before_planning(fake, status):
    fake.rows[0]["status"] = status
    _book_venue(fake)

    assert preview_event_update(_event(fake), {"expected_attendance": 150})["arrangements"] == []


def test_ac3_arrangements_are_presented_through_the_preview_route(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch, ["event_coordinator"])
    _book_venue(fake)

    response = client.post(
        "/events/session-1/update-preview", headers=_auth(signing_key, COORDINATOR), json={"expected_attendance": 150}
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.get_json()["arrangements"]] == ["booking-1"]
    assert fake.get("session-1")["expected_attendance"] == 100


# -- AC4: what, who, when ---------------------------------------------------------


def test_ac4_every_update_records_what_changed_who_changed_it_and_when(fake):
    """AC4: one event_logs entry per update -- each changed field from/to,
    the coordinator, and the time (the database's changed_at default)."""
    update_event(_event(fake), {"expected_attendance": 150, "special_requests": "Lunch."}, COORDINATOR)

    [entry] = _logs(fake)
    assert entry["changes"] == {
        "expected_attendance": {"from": 100, "to": 150},
        "special_requests": {"from": None, "to": "Lunch."},
    }
    assert entry["changed_by"] == COORDINATOR
    assert entry["shared_event_id"] == "group-1"
    insert = next(call for call in fake.calls if call["table"] == "event_logs" and call["op"] == "insert")
    assert "changed_at" not in insert["payload"]  # WHEN is set by the database, not a client clock


def test_ac4_an_update_that_changes_nothing_writes_nothing(fake):
    """Saving the form unchanged writes nothing and logs nothing."""
    result = update_event(_event(fake), {"name": "Community Conference", "preferred_start_time": "09:00"}, COORDINATOR)

    assert result["id"] == "session-1"
    assert _writes(fake) == [] and _logs(fake) == []


# -- AC5: only the coordinator edits; others can view ----------------------------


@pytest.mark.parametrize(
    "user,roles",
    [(ORGANISER, ["event_organizer"]), (LEAD, ["event_coordinator_lead"])],
)
def test_ac5_others_who_can_view_the_event_cannot_update_it(client, signing_key, monkeypatch, fake, user, roles):
    """AC5: the organiser and the Event Coordinator Lead can view the event
    but an update from them is refused (403, with the reason) and changes
    nothing."""
    _mock_profile(monkeypatch, roles)
    headers = _auth(signing_key, user)

    viewed = client.get("/events/session-1", headers=headers)
    refused = client.post("/events/session-1", headers=headers, json={"name": "Hijacked"})
    previewed = client.post("/events/session-1/update-preview", headers=headers, json={"name": "Hijacked"})

    assert viewed.status_code == 200
    assert refused.status_code == 403 and previewed.status_code == 403
    assert "can update it" in refused.get_json()["error"]["message"]
    assert fake.get("session-1")["name"] == "Community Conference"
    assert _logs(fake) == []


def test_ac5_another_coordinator_cannot_see_or_update_the_event(client, signing_key, monkeypatch, fake):
    """A coordinator who isn't assigned to the event gets a 404 -- they
    aren't entitled to know it exists."""
    _mock_profile(monkeypatch, ["event_coordinator"])
    response = client.post("/events/session-1", headers=_auth(signing_key, "coord-2"), json={"name": "Hijacked"})
    assert response.status_code == 404
    assert fake.get("session-1")["name"] == "Community Conference"


# -- AC6: a failed update leaves the event unchanged ------------------------------


@pytest.mark.parametrize(
    "body,message",
    [
        ({"expected_attendance": 0}, "expected_attendance must be a positive integer"),
        ({"name": ""}, "name is required"),
        ({"preferred_start_date": date.today().isoformat()}, "preferred_start_date must be after today"),
        ({"preferred_end_time": "08:00"}, "preferred_end_time must be after preferred_start_time"),
        ({"room_layout": "stadium"}, "no longer exists"),
        ({"status": "completed"}, "Unknown event fields: status"),
    ],
)
def test_ac6_an_update_that_fails_validation_leaves_the_event_unchanged(fake, body, message):
    """AC6: nothing is written -- not the event, not the log -- when the
    update doesn't validate. A partial update is checked against the details
    it didn't send (an end time before the stored start time is refused)."""
    before = dict(fake.get("session-1"))

    with pytest.raises(ValidationError, match=message):
        update_event(_event(fake), body, COORDINATOR)

    assert fake.get("session-1") == before
    assert _writes(fake) == [] and _logs(fake) == []


def test_ac6_a_failed_update_through_the_route_is_a_400(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch, ["event_coordinator"])
    headers = _auth(signing_key, COORDINATOR)
    response = client.post("/events/session-1", headers=headers, json={"expected_attendance": -5})
    assert response.status_code == 400
    assert fake.get("session-1")["expected_attendance"] == 100


def test_ac6_an_update_racing_a_status_change_is_refused_not_overwritten(fake):
    """The write is conditional on the status the coordinator was authorised
    against: if the event was cancelled meanwhile, it's a 409 and nothing
    is written."""
    loaded = _event(fake)
    fake.rows[0]["status"] = "cancelled"

    with pytest.raises(EventUpdateConflictError):
        update_event(loaded, {"expected_attendance": 150}, COORDINATOR)

    assert fake.get("session-1")["expected_attendance"] == 100
    assert _logs(fake) == []


# -- AC7: no editing once completed or cancelled ---------------------------------


@pytest.mark.parametrize("status", ["completed", "cancelled"])
def test_ac7_a_finished_event_refuses_updates_with_the_reason(client, signing_key, monkeypatch, fake, status):
    """AC7: once completed or cancelled, the assigned coordinator's update
    is refused (403) with a reason naming the status, and nothing changes."""
    fake.rows[0]["status"] = status
    _mock_profile(monkeypatch, ["event_coordinator"])

    response = client.post("/events/session-1", headers=_auth(signing_key, COORDINATOR), json={"name": "Too late"})

    assert response.status_code == 403
    assert response.get_json()["error"]["message"] == (
        f"This event is {status}, so its details can no longer be updated."
    )
    assert fake.get("session-1")["name"] == "Community Conference"


# -- AC8 / AC10: confirmed goes back to planning, and that is audited -----------


def test_ac10_a_change_to_a_confirmed_event_sends_it_back_to_planning(fake):
    """AC10: any change after confirmation reverts the event to planning;
    AC8: the status change is in event_status_log, who made it and why."""
    fake.rows[0]["status"] = "confirmed"

    updated = update_event(_event(fake), {"special_requests": "Vegetarian lunch."}, COORDINATOR)

    assert updated["status"] == "planning"
    assert fake.get("session-1")["status"] == "planning"
    [history] = _status_log(fake)
    assert (history["from_status"], history["to_status"]) == ("confirmed", "planning")
    assert history["changed_by"] == COORDINATOR
    assert history["reason"] == "Event details changed after confirmation (special requests)."


def test_ac10_the_preview_warns_that_a_confirmed_event_will_go_back_to_planning(fake):
    fake.rows[0]["status"] = "confirmed"
    assert preview_event_update(_event(fake), {"name": "Community Summit"})["reverts_to_planning"] is True
    assert preview_event_update(_event(fake), {"name": "Community Conference"})["reverts_to_planning"] is False


@pytest.mark.parametrize("status", ["approved", "planning"])
def test_ac10_only_a_confirmed_event_changes_status(fake, status):
    """Before confirmation an update leaves the status alone."""
    fake.rows[0]["status"] = status
    update_event(_event(fake), {"expected_attendance": 150}, COORDINATOR)
    assert fake.get("session-1")["status"] == status
    assert _status_log(fake) == []


def test_ac10_saving_a_confirmed_event_unchanged_keeps_it_confirmed(fake):
    fake.rows[0]["status"] = "confirmed"
    update_event(_event(fake), {"name": "Community Conference"}, COORDINATOR)
    assert fake.get("session-1")["status"] == "confirmed"


# -- AC9: one venue arrangement doesn't remove another ----------------------------


def test_ac9_a_change_affecting_one_venue_booking_leaves_every_booking_in_place(fake):
    """AC9: when a change conflicts with one of the session's bookings, each
    booking is reported on its own and none is changed or removed."""
    _book_venue(fake, "booking-small", capacity=120)
    _book_venue(fake, "booking-large", capacity=500, status="pending")
    bookings_before = [dict(row) for row in fake.tables["venue_bookings"]]

    impacts = preview_event_update(_event(fake), {"expected_attendance": 150})["impacts"]
    update_event(_event(fake), {"expected_attendance": 150}, COORDINATOR, ["venue"])

    assert [impact["booking_id"] for impact in impacts] == ["booking-small"]
    assert fake.tables["venue_bookings"] == bookings_before
    assert _writes(fake, "venue_bookings") == []


# -- shared details stay one version across sessions ------------------------------


def test_a_new_name_reaches_every_open_session_of_the_request(fake):
    """Name, description and purpose are shared by every session, so the
    coordinator's change reaches the others -- logged once. A cancelled
    session is read-only and keeps its name; a confirmed one is renamed and
    goes back to planning."""
    fake.rows[1]["status"] = "confirmed"
    fake.rows.append(_session(id="session-3", status="cancelled"))

    update_event(_event(fake), {"name": "Community Summit"}, COORDINATOR)

    assert fake.get("session-2")["name"] == "Community Summit"
    assert fake.get("session-2")["status"] == "planning"
    assert fake.get("session-3")["name"] == "Community Conference"
    assert len(_logs(fake)) == 1


def test_an_organiser_fixing_a_rejected_session_changes_only_that_session(fake):
    """Only the coordinator's update reaches the other sessions."""
    fake.rows[0]["status"] = "rejected"
    update_event(_event(fake), {"name": "Community Summit"}, ORGANISER)
    assert fake.get("session-1")["name"] == "Community Summit"
    assert fake.get("session-2")["name"] == "Community Conference"


# -- the coordinator's form ------------------------------------------------------


def test_the_coordinator_edit_form_payload_is_saved(fake):
    """The "Edit Details" form (CoordinatorEventReview) sends the whole
    session in one body -- shared fields plus every session field, with the
    registration window in UTC -- and it's written to the event's own row,
    leaving the status and the assigned coordinator as they were."""
    fake.rows[0]["status"] = "under_review"
    form_body = {
        "name": "Community Conference (revised)",
        "description": "Updated by the coordinator.",
        "purpose": "Knowledge sharing.",
        "preferred_start_date": FUTURE,
        "preferred_start_time": "10:00",
        "preferred_end_date": FUTURE,
        "preferred_end_time": "16:00",
        "expected_attendance": 120,
        "accessibility_needs": [{"item": "lift_access"}],
        "room_layout": "banquet",
        "equipment": [{"item": "screen", "quantity": 2}],
        "registration_needs": True,
        "registration_start_datetime": "2026-01-01T01:00:00.000Z",
        "registration_end_datetime": f"{FUTURE}T00:00:00.000Z",
        "special_requests": "",
    }

    update_event(_event(fake), form_body, COORDINATOR)

    row = fake.get("session-1")
    assert row["name"] == "Community Conference (revised)"
    assert row["expected_attendance"] == 120
    assert row["room_layout"] == "banquet"
    assert row["equipment_needed"] == {"equipment": [{"item": "screen", "quantity": 2}]}
    assert row["registration_end_datetime"] == f"{FUTURE}T08:00:00+08:00"
    assert row["status"] == "under_review"
    assert row["coordinator_id"] == COORDINATOR


def test_an_update_to_a_session_that_no_longer_exists_is_refused(fake):
    """A session deleted in the meantime: nothing is written, and the
    coordinator is told to refresh."""
    stale = SimpleNamespace(**_session(id="gone"))
    with pytest.raises(EventUpdateConflictError, match="refresh"):
        update_event(stale, {"expected_attendance": 50}, COORDINATOR)


def test_a_draft_is_updated_without_being_logged(client, signing_key, monkeypatch, fake):
    """The organiser's own draft can still be edited here, half-filled, and
    isn't logged -- it hasn't been submitted to anyone yet."""
    fake.rows[0].update(status="draft", coordinator_id=None, expected_attendance=None)
    _mock_profile(monkeypatch, ["event_organizer"])

    response = client.post("/events/session-1", headers=_auth(signing_key, ORGANISER), json={"name": "Renamed draft"})

    assert response.status_code == 200
    assert fake.get("session-1")["name"] == "Renamed draft"
    assert _logs(fake) == []
