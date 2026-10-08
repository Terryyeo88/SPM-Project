"""The event audit trail (public.event_logs): each entry records WHAT changed
on an event, WHO changed it and WHEN, linked to the whole request
(shared_event_id).

Separate from change requests (public.event_change_requests): a change
request is what the organiser ASKED for; a log entry is what actually
CHANGED -- from an approved change request or a direct edit.

Unit-level: FakeSupabase stands in for every module that writes.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

import app.auth.context as context_module
import app.events.change_impact as impact_module
import app.events.change_request_service as change_service
import app.events.event_log as event_log
import app.events.event_service as event_service
import app.events.routes as routes_module
from app.events.change_request_service import approve_change_request, reject_change_request, request_event_change
from tests.fake_supabase import FakeSupabase

ORGANISER = "org-1"
COORDINATOR = "coord-1"
FUTURE = (date.today() + timedelta(days=30)).isoformat()


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
    db = FakeSupabase(
        [
            _session(),
            _session(id="session-2"),
            _session(id="other-org-session", organizer_id="org-2", coordinator_id="coord-2"),
        ]
    )
    for module in (change_service, impact_module, event_log, event_service, routes_module):
        monkeypatch.setattr(module, "supabase", db)
    return db


def _event(fake, event_id="session-1"):
    return SimpleNamespace(**dict(fake.get(event_id)))


def _logs(fake):
    return fake.tables.get("event_logs", [])


# -- what a log entry records -------------------------------------------------


def test_diff_keeps_only_changed_fields_as_from_and_to():
    before = {"expected_attendance": 100, "room_layout": "theatre", "special_requests": None}
    after = {"expected_attendance": 150, "room_layout": "theatre", "special_requests": ""}

    assert event_log.diff(before, after) == {"expected_attendance": {"from": 100, "to": 150}}


def test_diff_treats_the_same_instant_in_another_timezone_as_unchanged():
    before = {"registration_end_datetime": "2026-11-01T01:00:00+00:00"}
    after = {"registration_end_datetime": "2026-11-01T09:00:00+08:00"}

    assert event_log.diff(before, after) == {}


def test_entry_records_what_who_and_which_request(fake):
    before = fake.get("session-1")
    after = {**before, "expected_attendance": 150, "equipment_needed": {"equipment": [{"item": "wifi", "quantity": 1}]}}

    entry = event_log.record_event_change(before, after, COORDINATOR)

    assert _logs(fake) == [entry]
    assert entry["event_log_id"]  # its own id, filled in by the database
    assert entry["shared_event_id"] == "group-1"
    assert entry["changed_by"] == COORDINATOR
    # API field names ("equipment", not the equipment_needed column).
    assert entry["changes"] == {
        "expected_attendance": {"from": 100, "to": 150},
        "equipment": {"from": [], "to": [{"item": "wifi", "quantity": 1}]},
    }
    # Exactly the live columns; WHEN is the database's changed_at default
    # (now()), not a client clock.
    assert set(fake.calls[-1]["payload"]) == {"shared_event_id", "changes", "changed_by"}


def test_nothing_is_logged_when_nothing_changed(fake):
    row = fake.get("session-1")
    assert event_log.record_event_change(row, dict(row), COORDINATOR) is None
    assert _logs(fake) == []


def test_a_legacy_event_is_logged_under_its_own_id(fake):
    legacy = _session(id="legacy-1", shared_event_id=None)
    entry = event_log.record_event_change(legacy, {**legacy, "room_layout": "banquet"}, COORDINATOR)
    assert entry["shared_event_id"] == "legacy-1"


# -- change requests vs logs --------------------------------------------------


def _kinds(fake):
    """(kind, changed_by) per entry, oldest first, as list_event_logs labels
    them. Ordered by insertion: the fake's inserts carry no changed_at (the
    database fills it in), so it can't sort them newest-first itself."""
    kinds = {entry["event_log_id"]: entry["kind"] for entry in event_log.list_event_logs(_event(fake))}
    return [(kinds[entry["event_log_id"]], entry["changed_by"]) for entry in _logs(fake)]


def test_requesting_a_change_is_logged_as_a_request_not_a_change(fake):
    """The organiser only ASKS: the entry says what they want changed, and
    the event itself is untouched."""
    change = request_event_change(_event(fake), ORGANISER, {"changes": {"room_layout": "banquet"}})

    [entry] = _logs(fake)
    assert entry["changed_by"] == ORGANISER
    assert entry["changes"] == {"room_layout": {"from": "theatre", "to": "banquet"}}
    assert _kinds(fake) == [("requested", ORGANISER)]
    assert fake.get("session-1")["room_layout"] == "theatre"
    assert len(fake.tables["event_change_requests"]) == 1 and change["status"] == "pending"


def test_a_rejected_change_request_adds_nothing_after_the_request(fake):
    change = request_event_change(_event(fake), ORGANISER, {"changes": {"room_layout": "banquet"}})
    reject_change_request(_event(fake), change["event_change_req_id"], COORDINATOR, "No banquet rooms.")

    assert _kinds(fake) == [("requested", ORGANISER)]


def test_an_approved_change_request_reads_requested_then_changed(fake):
    change = request_event_change(_event(fake), ORGANISER, {"changes": {"expected_attendance": 150}})

    approve_change_request(_event(fake), change["event_change_req_id"], COORDINATOR)

    assert _kinds(fake) == [("requested", ORGANISER), ("changed", COORDINATOR)]
    applied = _logs(fake)[-1]
    assert applied["shared_event_id"] == "group-1"
    assert applied["changes"] == {"expected_attendance": {"from": 100, "to": 150}}


def test_a_shared_detail_is_written_to_every_session_but_logged_once(fake):
    change = request_event_change(_event(fake), ORGANISER, {"changes": {"name": "Community Summit"}})

    approve_change_request(_event(fake), change["event_change_req_id"], COORDINATOR)

    assert fake.get("session-2")["name"] == "Community Summit"
    applied = [entry for entry in _logs(fake) if entry["changed_by"] == COORDINATOR]
    assert [entry["changes"] for entry in applied] == [
        {"name": {"from": "Community Conference", "to": "Community Summit"}}
    ]


def test_someone_who_is_both_organiser_and_coordinator_makes_changes():
    both = SimpleNamespace(organizer_id="user-1", coordinator_id="user-1")
    assert event_log.entry_kind({"changed_by": "user-1"}, both) == "changed"
    assert event_log.entry_kind({"changed_by": None}, both) == "changed"


# -- direct edits, through the routes -------------------------------------------


def _mock_profile(monkeypatch, roles):
    monkeypatch.setattr(
        context_module, "_load_profile_with_roles", lambda user_id: ("Test User", "t@example.com", frozenset(roles))
    )
    monkeypatch.setattr(context_module, "_get_last_active", lambda session_id: None)
    monkeypatch.setattr(context_module, "_touch_session_activity", lambda *a, **k: None)


def _auth(signing_key, user_id):
    return {"Authorization": f"Bearer {signing_key.make_token(sub=user_id)}"}


def test_coordinator_edit_is_logged(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch, ["event_coordinator"])

    response = client.post(
        "/events/session-1",
        headers=_auth(signing_key, COORDINATOR),
        json={"name": "Community Conference", "expected_attendance": 120},
    )

    assert response.status_code == 200
    [entry] = _logs(fake)
    assert entry["changed_by"] == COORDINATOR
    assert entry["changes"] == {"expected_attendance": {"from": 100, "to": 120}}
    assert _kinds(fake) == [("changed", COORDINATOR)]


def test_organiser_fixing_a_rejected_session_is_logged(client, signing_key, monkeypatch, fake):
    fake.rows[0]["status"] = "rejected"
    _mock_profile(monkeypatch, ["event_organizer"])

    response = client.post(
        "/events/session-1/draft",
        headers=_auth(signing_key, ORGANISER),
        json={"name": "Community Conference", "sessions": [{"id": "session-1", "room_layout": "classroom"}]},
    )

    assert response.status_code == 200
    [entry] = _logs(fake)
    assert entry["changed_by"] == ORGANISER
    assert entry["changes"] == {"room_layout": {"from": "theatre", "to": "classroom"}}
    # Waiting on the coordinator's review again once resubmitted -- a request.
    assert _kinds(fake) == [("requested", ORGANISER)]


def test_draft_edits_are_not_logged(client, signing_key, monkeypatch, fake):
    fake.rows[0]["status"] = "draft"
    _mock_profile(monkeypatch, ["event_organizer"])

    response = client.post("/events/session-1", headers=_auth(signing_key, ORGANISER), json={"name": "Renamed draft"})

    assert response.status_code == 200
    assert _logs(fake) == []


# -- reading the log --------------------------------------------------------------


def test_log_is_the_whole_request_newest_first(client, signing_key, monkeypatch, fake):
    fake.tables["event_logs"] = [
        {"event_log_id": "old", "shared_event_id": "group-1", "changed_at": "2026-10-01T00:00:00Z"},
        {"event_log_id": "new", "shared_event_id": "group-1", "changed_at": "2026-10-02T00:00:00Z"},
        {"event_log_id": "elsewhere", "shared_event_id": "group-2", "changed_at": "2026-10-04T00:00:00Z"},
    ]
    _mock_profile(monkeypatch, ["event_organizer"])

    response = client.get("/events/session-2/logs", headers=_auth(signing_key, ORGANISER))

    assert response.status_code == 200
    assert [entry["event_log_id"] for entry in response.get_json()] == ["new", "old"]


def test_log_includes_who_made_each_change(fake):
    event_log.list_event_logs(_event(fake))
    select = next(call for call in fake.calls if call["table"] == "event_logs")
    # The changer's name, through the changed_by -> profiles foreign key.
    assert select["columns"] == "*, profiles(name)"


def test_log_is_hidden_from_unrelated_users(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch, ["event_coordinator"])
    response = client.get("/events/session-1/logs", headers=_auth(signing_key, "coord-2"))
    assert response.status_code == 404


def test_list_for_a_legacy_event_reads_its_own_id(fake):
    fake.rows.append(_session(id="legacy-1", shared_event_id=None))
    fake.tables["event_logs"] = [{"event_log_id": "a", "shared_event_id": "legacy-1"}]

    listed = event_log.list_event_logs(_event(fake, "legacy-1"))

    assert [entry["event_log_id"] for entry in listed] == ["a"]
