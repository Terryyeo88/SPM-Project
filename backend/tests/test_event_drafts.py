"""Tests for saving incomplete event requests as drafts."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

import app.events.event_service as service
from app.events.event_service import (
    DRAFT_NAME,
    _draft_payload,
    create_draft_request,
    delete_draft_request,
    save_draft_request,
)
from app.shared.errors import ValidationError
from tests.fake_supabase import FakeSupabase


def test_draft_payload_accepts_one_partial_field():
    """A draft may be saved with only one meaningful field filled in."""
    payload = _draft_payload({"description": "A conference draft."})

    assert payload["name"] == DRAFT_NAME
    assert payload["description"] == "A conference draft."


def test_draft_payload_preserves_partial_updates():
    """Saving a draft update preserves fields that were already stored."""
    payload = _draft_payload(
        {"description": "Updated description."},
        {
            "name": "Existing event",
            "purpose": "Existing purpose",
            "equipment": [],
        },
    )

    assert payload["name"] == "Existing event"
    assert payload["purpose"] == "Existing purpose"
    assert payload["description"] == "Updated description."
    assert payload["equipment_needed"] == {"equipment": []}


def test_draft_payload_normalizes_blank_date_and_time_fields_to_null():
    """Blank strings for the date/time fields (as an emptied HTML date/time
    input would submit) are normalized to None, not stored as empty
    strings -- same treatment as room_layout."""
    payload = _draft_payload(
        {
            "description": "A conference draft.",
            "preferred_start_date": "",
            "preferred_end_date": "",
            "preferred_start_time": "",
            "preferred_end_time": "",
        }
    )

    assert payload["preferred_start_date"] is None
    assert payload["preferred_end_date"] is None
    assert payload["preferred_start_time"] is None
    assert payload["preferred_end_time"] is None


# -- Registration window on drafts ---------------------------------------------


def test_draft_payload_normalizes_blank_registration_window_to_null():
    """An emptied datetime-local input arrives as "" -- stored as NULL, the
    same treatment as the date/time fields above."""
    payload = _draft_payload(
        {
            "registration_needs": True,
            "registration_start_datetime": "",
            "registration_end_datetime": "",
        }
    )

    assert payload["registration_start_datetime"] is None
    assert payload["registration_end_datetime"] is None


def test_draft_payload_clears_registration_window_when_registration_not_needed():
    """Unticking "Registration needed" drops a window entered earlier, so a
    stale one isn't left stored against a session with no registration."""
    payload = _draft_payload(
        {
            "registration_needs": False,
            "registration_start_datetime": "2026-11-01T01:00:00Z",
            "registration_end_datetime": "2026-11-05T01:00:00Z",
        }
    )

    assert payload["registration_start_datetime"] is None
    assert payload["registration_end_datetime"] is None


def test_draft_payload_keeps_a_half_filled_registration_window():
    """A draft may have the opening time without the closing time yet."""
    payload = _draft_payload({"registration_needs": True, "registration_start_datetime": "2026-11-01T01:00:00Z"})

    assert payload["registration_start_datetime"] == "2026-11-01T09:00:00+08:00"
    assert payload.get("registration_end_datetime") is None


def test_draft_payload_stores_registration_window_in_singapore_time():
    """The browser sends UTC; the timestamptz column gets the same instant
    written with Singapore's +08:00 offset."""
    payload = _draft_payload({"registration_needs": True, "registration_end_datetime": "2026-11-05T10:30:00.000Z"})

    assert payload["registration_end_datetime"] == "2026-11-05T18:30:00+08:00"


def test_draft_payload_rejects_registration_datetime_without_offset():
    """Even a draft can't store a naive value -- Postgres would read it as
    UTC and silently shift it by eight hours."""
    with pytest.raises(ValidationError, match="timezone offset"):
        _draft_payload({"registration_start_datetime": "2026-11-01T09:00"})


# -- Creating a multi-session draft --------------------------------------------


@pytest.fixture
def fake_db(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(service, "supabase", fake)
    return fake


def test_create_draft_request_links_every_session_with_one_new_shared_id(fake_db):
    """Saving a new multi-session draft writes one events row per session, all
    sharing one shared_event_id generated on the server (a real uuid). Every
    row is a draft owned by the organiser with the shared name, the rows are
    created by a single insert, and the response lists sessions in date
    order."""

    group = create_draft_request(
        "organizer-1",
        {
            "name": "Workshop",
            "sessions": [
                {"preferred_start_date": "2026-11-12", "room_layout": "classroom"},
                {"preferred_start_date": "2026-11-10", "room_layout": "theatre"},
            ],
        },
    )

    shared_ids = {row["shared_event_id"] for row in fake_db.rows}
    assert len(fake_db.rows) == 2
    assert len(shared_ids) == 1
    uuid.UUID(shared_ids.pop())  # generated server-side, and a real uuid
    assert all(row["status"] == "draft" for row in fake_db.rows)
    assert all(row["organizer_id"] == "organizer-1" for row in fake_db.rows)
    assert all(row["name"] == "Workshop" for row in fake_db.rows)
    # One insert statement, so the sessions are created all-or-nothing.
    assert [call["op"] for call in fake_db.calls] == ["insert"]
    # The response lists sessions chronologically, whatever order they were sent in.
    assert [s["preferred_start_date"] for s in group["sessions"]] == ["2026-11-10", "2026-11-12"]
    assert group["shared_event_id"] == fake_db.rows[0]["shared_event_id"]


def test_create_draft_request_gives_each_request_its_own_shared_id(fake_db):
    """Two separate draft requests never share a shared_event_id -- each new
    request gets its own."""

    first = create_draft_request("organizer-1", {"name": "First", "sessions": [{}]})
    second = create_draft_request("organizer-1", {"name": "Second", "sessions": [{}]})

    assert first["shared_event_id"] != second["shared_event_id"]


def test_create_draft_request_stores_each_sessions_own_requirements(fake_db):
    """Per-session fields (attendance, equipment, registration needed) are stored
    on that session's own row, not copied across sessions."""

    create_draft_request(
        "organizer-1",
        {
            "name": "Workshop",
            "sessions": [
                {"expected_attendance": 80, "equipment": [{"item": "projector", "quantity": 2}]},
                {"expected_attendance": 20, "registration_needs": True},
            ],
        },
    )

    first, second = fake_db.rows
    assert first["expected_attendance"] == 80
    assert first["equipment_needed"] == {"equipment": [{"item": "projector", "quantity": 2}]}
    assert second["expected_attendance"] == 20
    assert second["equipment_needed"] == {"equipment": []}
    assert second["registration_needs"] is True


def test_create_draft_request_requires_sessions_list(fake_db):
    """A draft body without a sessions list is rejected before anything is written
    to the database."""

    with pytest.raises(ValidationError, match="sessions must be a non-empty list"):
        create_draft_request("organizer-1", {"name": "Workshop"})
    assert fake_db.calls == []


# -- Saving an existing draft --------------------------------------------------


def _row(event_id, **overrides):
    row = {
        "id": event_id,
        "organizer_id": "organizer-1",
        "coordinator_id": None,
        "status": "draft",
        "shared_event_id": "group-1",
        "name": "Workshop",
        "description": "d",
        "purpose": "p",
        "preferred_start_date": "2026-11-10",
        "preferred_end_date": "2026-11-10",
        "preferred_start_time": None,
        "preferred_end_time": None,
        "expected_attendance": 50,
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


def test_save_draft_updates_adds_and_removes_sessions(fake_db):
    """The body is the whole request: sessions with an id are updated,
    sessions without one are added, and drafts left out are removed."""
    fake_db.rows = [_row("a"), _row("b", preferred_start_date="2026-11-11")]

    group = save_draft_request(
        "a",
        SimpleNamespace(**fake_db.get("a")),
        {
            "name": "Renamed workshop",
            "sessions": [
                {"id": "a", "expected_attendance": 75},
                {"preferred_start_date": "2026-11-20", "room_layout": "banquet"},
            ],
        },
    )

    assert fake_db.get("a")["expected_attendance"] == 75
    assert fake_db.get("b") is None
    added = [row for row in fake_db.rows if row["id"] not in ("a", "b")]
    assert len(added) == 1
    assert added[0]["shared_event_id"] == "group-1"
    assert added[0]["status"] == "draft"
    assert added[0]["room_layout"] == "banquet"
    # The shared name is written to every session, not just the first.
    assert {row["name"] for row in fake_db.rows} == {"Renamed workshop"}
    assert [s["id"] for s in group["sessions"]] == ["a", added[0]["id"]]


def test_save_draft_keeps_fields_not_sent_for_an_existing_session(fake_db):
    """Updating an existing session keeps any of its stored fields the body didn't
    include, rather than blanking them."""

    fake_db.rows = [_row("a", room_layout="boardroom", special_requests="Near lifts")]

    save_draft_request("a", SimpleNamespace(**fake_db.get("a")), {"sessions": [{"id": "a", "expected_attendance": 10}]})

    assert fake_db.get("a")["room_layout"] == "boardroom"
    assert fake_db.get("a")["special_requests"] == "Near lifts"


def test_save_draft_removes_sessions_last(fake_db):
    """No transaction is available, so removals go after the writes: a
    failure part-way leaves an extra session behind, never a lost one."""
    fake_db.rows = [_row("a"), _row("b")]

    save_draft_request(
        "a",
        SimpleNamespace(**fake_db.get("a")),
        {"sessions": [{"id": "a", "expected_attendance": 40}, {"room_layout": "seminar"}]},
    )

    ops = [call["op"] for call in fake_db.calls]
    assert ops.index("delete") > ops.index("update")
    assert ops.index("delete") > ops.index("insert")


def test_save_draft_never_touches_another_requests_or_submitted_sessions(fake_db):
    """Saving a draft only affects that request's still-draft sessions: a sibling
    session that's already submitted keeps its status, and sessions of a
    different request are left alone."""

    fake_db.rows = [
        _row("a"),
        _row("submitted-sibling", status="submitted"),
        _row("other-request", shared_event_id="group-2"),
    ]

    save_draft_request("a", SimpleNamespace(**fake_db.get("a")), {"sessions": [{"id": "a", "expected_attendance": 40}]})

    assert fake_db.get("submitted-sibling")["status"] == "submitted"
    assert fake_db.get("other-request") is not None


def test_save_draft_rejects_a_session_id_from_another_request(fake_db):
    """A session id in the body that belongs to a different request is rejected
    (naming which session), and nothing is written."""

    fake_db.rows = [_row("a"), _row("foreign", shared_event_id="group-2")]

    with pytest.raises(ValidationError, match="Session 2 does not belong"):
        save_draft_request(
            "a",
            SimpleNamespace(**fake_db.get("a")),
            {"sessions": [{"id": "a", "expected_attendance": 40}, {"id": "foreign"}]},
        )
    assert [call["op"] for call in fake_db.calls] == ["select"]  # nothing written


def test_save_draft_gives_a_legacy_single_row_draft_a_shared_id(fake_db):
    """Drafts created before sessions existed have no shared_event_id; the
    first save gives them one, so sessions added alongside are linked."""
    fake_db.rows = [_row("legacy", shared_event_id=None)]

    group = save_draft_request(
        "legacy",
        SimpleNamespace(**fake_db.get("legacy")),
        {"sessions": [{"id": "legacy", "expected_attendance": 40}, {"room_layout": "seminar"}]},
    )

    shared_ids = {row["shared_event_id"] for row in fake_db.rows}
    assert len(fake_db.rows) == 2
    assert len(shared_ids) == 1
    uuid.UUID(shared_ids.pop())
    assert len(group["sessions"]) == 2


def test_save_rejected_session_edits_only_that_session(fake_db):
    """Editing a rejected session updates only that one row (including the shared
    name); its approved sibling keeps its own values."""

    fake_db.rows = [
        _row("rejected", status="rejected"),
        _row("approved-sibling", status="approved"),
    ]

    group = save_draft_request(
        "rejected",
        SimpleNamespace(**fake_db.get("rejected")),
        {"name": "Fixed name", "sessions": [{"id": "rejected", "expected_attendance": 30}]},
    )

    assert fake_db.get("rejected")["expected_attendance"] == 30
    assert fake_db.get("rejected")["name"] == "Fixed name"
    assert fake_db.get("approved-sibling")["name"] == "Workshop"
    assert [s["id"] for s in group["sessions"]] == ["rejected"]


@pytest.mark.parametrize(
    "sessions",
    [
        [{"id": "rejected", "expected_attendance": 40}, {"room_layout": "seminar"}],  # adding a session
        [{"id": "approved-sibling", "expected_attendance": 40}],  # editing a sibling instead
    ],
)
def test_save_rejected_session_cannot_change_the_request_shape(fake_db, sessions):
    """A rejected session can't add a new session or edit a sibling session instead
    -- both are refused before anything is written."""

    fake_db.rows = [_row("rejected", status="rejected"), _row("approved-sibling", status="approved")]

    with pytest.raises(ValidationError, match="one session at a time"):
        save_draft_request("rejected", SimpleNamespace(**fake_db.get("rejected")), {"sessions": sessions})
    assert fake_db.calls == []


def test_save_draft_requires_some_data_across_the_request(fake_db):
    """Saving a draft with no meaningful value anywhere in the request (shared
    fields or any session) is rejected."""

    fake_db.rows = [_row("a")]

    with pytest.raises(ValidationError, match="At least one event field"):
        save_draft_request("a", SimpleNamespace(**fake_db.get("a")), {"name": "", "sessions": [{"id": "a"}]})


# -- Deleting a draft ----------------------------------------------------------


def test_delete_draft_removes_every_draft_session_of_the_request(fake_db):
    """Deleting a draft removes every draft session of that request, but not
    another request's sessions or another organiser's. The delete is
    filtered by organiser and draft status, not only by shared_event_id."""

    fake_db.rows = [
        _row("a"),
        _row("b"),
        _row("other-request", shared_event_id="group-2"),
        _row("someone-elses", organizer_id="organizer-2"),
    ]

    delete_draft_request("a", SimpleNamespace(**fake_db.get("a")))

    assert [row["id"] for row in fake_db.rows] == ["other-request", "someone-elses"]
    # Scoped by request, organiser AND status -- not by shared_event_id alone.
    assert ("eq", "organizer_id", "organizer-1") in fake_db.calls[0]["filters"]
    assert ("eq", "status", "draft") in fake_db.calls[0]["filters"]


def test_delete_legacy_draft_without_shared_id_removes_only_that_row(fake_db):
    """A draft created before sessions existed (no shared_event_id) is deleted by
    its own id only -- other ungrouped drafts are untouched."""

    fake_db.rows = [_row("legacy", shared_event_id=None), _row("unrelated", shared_event_id=None)]

    delete_draft_request("legacy", SimpleNamespace(**fake_db.get("legacy")))

    assert [row["id"] for row in fake_db.rows] == ["unrelated"]
