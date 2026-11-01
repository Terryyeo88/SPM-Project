"""
Notification (Attendees) (IS-76): who each attendee notification goes to,
what it says and links to, and -- for details changes -- when one is sent
at all. In-memory fake, no database. The wiring (which story calls these,
and when) is test_notification_hook_attendees.py's job.

AC numbers are the story's (docs/traceability.md, IS-76).
"""

from __future__ import annotations

import pytest

import app.notifications.notification_service as service
from tests.fake_supabase import FakeSupabase

ORG, COORD = "org-1", "coord-1"

# Timeline for the reconfirmation tests: first confirmed at T1, changed
# (back to planning) at T2, safety check at T3, confirmed again at T4.
T0 = "2026-10-01T00:00:00+00:00"
T1 = "2026-10-02T00:00:00+00:00"
T2 = "2026-10-03T00:00:00+00:00"
T3 = "2026-10-04T00:00:00+00:00"
T4 = "2026-10-05T00:00:00+00:00"


def _session(event_id, start_date, start_time, **extra):
    return {
        "id": event_id,
        "shared_event_id": "req-1",
        "name": "Tech Talk",
        "preferred_start_date": start_date,
        "preferred_start_time": start_time,
        "organizer_id": ORG,
        "coordinator_id": COORD,
        "status": "confirmed",
        **extra,
    }


def _registration(registration_id, event_id, attendee_id, status, at):
    return {"id": registration_id, "event_id": event_id, "attendee_id": attendee_id, "status": status,
            "registered_at": f"2026-10-10T{at}:00"}


R1_CONFIRMED = {"id": "r1", "event_id": "s1", "attendee_id": "a1", "status": "confirmed"}


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase(rows=[_session("s1", "2026-11-12", "14:00:00"), _session("s2", "2026-11-13", "09:30:00")])
    fake.tables["registrations"] = [
        _registration("r1", "s1", "a1", "confirmed", "01:00"),
        _registration("r3", "s1", "a3", "waitlisted", "03:00"),
        _registration("r2", "s1", "a2", "waitlisted", "02:00"),
        _registration("r4", "s2", "a4", "confirmed", "01:00"),
    ]
    monkeypatch.setattr(service, "supabase", fake)
    return fake


def _sent(db):
    return sorted((row["recipient_id"], row["type"]) for row in db.tables.get("notifications", []))


def _only(db):
    (row,) = db.tables["notifications"]
    return row


def _confirmed_twice(db, event_id="s1"):
    db.tables["event_status_log"] = [
        {"event_id": event_id, "to_status": "confirmed", "changed_at": T1},
        {"event_id": event_id, "to_status": "planning", "changed_at": T2},
        {"event_id": event_id, "to_status": "safety_review", "changed_at": T3},
        {"event_id": event_id, "to_status": "confirmed", "changed_at": T4},
    ]


def _logged(db, event_id, changes, changed_by=COORD, changed_at=T2):
    db.tables.setdefault("event_logs", []).append(
        {"shared_event_id": "req-1", "event_id": event_id, "changes": changes, "changed_by": changed_by,
         "changed_at": changed_at}
    )


# -- AC11: names the event and the session --------------------------------------


@pytest.mark.parametrize(
    ("start_date", "start_time", "label"),
    [
        ("2026-11-12", "14:00:00", '"Tech Talk" on 12 Nov 2026, 2:00 PM'),
        ("2026-11-12", "00:05", '"Tech Talk" on 12 Nov 2026, 12:05 AM'),
        ("2026-11-12", "12:00:00", '"Tech Talk" on 12 Nov 2026, 12:00 PM'),
        ("2026-11-12", None, '"Tech Talk" on 12 Nov 2026'),
        ("2026-11-12", "not a time", '"Tech Talk" on 12 Nov 2026'),
        (None, "14:00:00", '"Tech Talk"'),
        ("not a date", None, '"Tech Talk"'),
    ],
)
def test_the_session_is_named_by_the_event_and_its_start(start_date, start_time, label):
    assert service.session_label(_session("s", start_date, start_time)) == label


def test_a_session_without_a_name_still_reads(db):
    assert service.session_label({"preferred_start_date": None}) == '"Your event"'


# -- AC1 / AC2: registering -----------------------------------------------------------


def test_ac1_a_confirmed_registration_is_confirmed_to_the_attendee_with_a_link(db):
    service.registration_recorded(R1_CONFIRMED)

    row = _only(db)
    assert (row["recipient_id"], row["type"]) == ("a1", service.REGISTRATION_CONFIRMED)
    assert row["message"] == 'Your registration for "Tech Talk" on 12 Nov 2026, 2:00 PM is confirmed.'
    assert (row["entity_type"], row["entity_id"]) == (service.ENTITY_ATTENDEE_EVENT, "s1")


def test_ac2_a_waitlisted_registration_says_so_with_the_place_in_the_queue(db):
    # r2 registered before r3, so r3 is second in line.
    service.registration_recorded({"id": "r3", "event_id": "s1", "attendee_id": "a3", "status": "waitlisted"})

    row = _only(db)
    assert (row["recipient_id"], row["type"]) == ("a3", service.REGISTRATION_WAITLISTED)
    assert "is full" in row["message"]
    assert row["message"].endswith("You are number 2 on the waiting list.")
    assert (row["entity_type"], row["entity_id"]) == (service.ENTITY_ATTENDEE_EVENT, "s1")


def test_ac2_without_a_known_place_the_waitlist_notice_still_goes(db):
    service.registration_recorded({"id": "gone", "event_id": "s1", "attendee_id": "a9", "status": "waitlisted"})

    assert _only(db)["message"].endswith("placed on the waiting list.")


def test_a_registration_for_a_missing_session_or_odd_status_tells_nobody(db):
    service.registration_recorded({"id": "x", "event_id": "missing", "attendee_id": "a1", "status": "confirmed"})
    service.registration_recorded({"id": "x", "event_id": "s1", "attendee_id": "a1", "status": "something"})

    assert _sent(db) == []


# -- AC3 / AC4: withdrawing -----------------------------------------------------------


def test_ac3_ac4_the_withdrawer_and_the_attendee_moved_up_are_both_told(db):
    service.registration_withdrawn("s1", "a1", "r2")

    assert _sent(db) == [("a1", service.REGISTRATION_WITHDRAWN), ("a2", service.REGISTRATION_PROMOTED)]
    by_type = {row["type"]: row for row in db.tables["notifications"]}
    assert by_type[service.REGISTRATION_WITHDRAWN]["message"] == (
        'You have withdrawn from "Tech Talk" on 12 Nov 2026, 2:00 PM.'
    )
    assert "is now confirmed" in by_type[service.REGISTRATION_PROMOTED]["message"]
    assert {(row["entity_type"], row["entity_id"]) for row in db.tables["notifications"]} == {
        (service.ENTITY_ATTENDEE_EVENT, "s1")
    }


def test_ac4_with_nobody_moved_up_only_the_withdrawer_is_told(db):
    service.registration_withdrawn("s1", "a2", None)

    assert _sent(db) == [("a2", service.REGISTRATION_WITHDRAWN)]


def test_ac3_a_promoted_registration_that_no_longer_exists_tells_only_the_withdrawer(db):
    service.registration_withdrawn("s1", "a1", "vanished")

    assert _sent(db) == [("a1", service.REGISTRATION_WITHDRAWN)]


def test_a_withdrawal_from_a_missing_session_tells_nobody(db):
    service.registration_withdrawn("missing", "a1", "r2")

    assert _sent(db) == []


# -- AC8 / AC9 / AC10: cancellation ------------------------------------------------------


def test_ac8_ac9_ac10_cancelling_tells_only_that_sessions_attendees(db):
    service.event_cancelled("s1")

    # a1 confirmed, a2/a3 waitlisted on s1; a4 (s2) and everyone else: nothing.
    assert _sent(db) == [
        ("a1", service.EVENT_CANCELLED),
        ("a2", service.EVENT_CANCELLED),
        ("a3", service.EVENT_CANCELLED),
    ]
    assert {row["message"] for row in db.tables["notifications"]} == {
        '"Tech Talk" on 12 Nov 2026, 2:00 PM has been cancelled.'
    }


def test_ac8_the_cancellation_has_no_link_and_no_reason(db):
    service.event_cancelled("s1")

    for row in db.tables["notifications"]:
        assert (row["entity_type"], row["entity_id"]) == (None, None)


def test_cancelling_a_session_nobody_registered_for_writes_nothing(db):
    db.tables["registrations"] = []
    service.event_cancelled("s1")

    assert _sent(db) == []


def test_cancelling_a_missing_session_writes_nothing(db):
    service.event_cancelled("missing")

    assert _sent(db) == []


# -- AC5 / AC7: confirmed again -----------------------------------------------------------


def test_the_first_confirmation_tells_nobody(db, caplog):
    db.tables["event_status_log"] = [{"event_id": "s1", "to_status": "confirmed", "changed_at": T1}]
    _logged(db, "s1", {"preferred_start_time": {"from": "13:00", "to": "14:00"}}, changed_at=T0)

    service.event_reconfirmed("s1")

    assert _sent(db) == []
    # Deliberately nothing to tell -- not a failure swallowed by _best_effort.
    assert "Notification not sent" not in caplog.text


@pytest.mark.parametrize(
    "field", ["preferred_start_date", "preferred_end_date", "preferred_start_time", "preferred_end_time"]
)
def test_ac5_a_date_or_time_change_is_told_once_reconfirmed(db, field):
    _confirmed_twice(db)
    _logged(db, "s1", {field: {"from": "a", "to": "b"}})

    service.event_reconfirmed("s1")

    assert _sent(db) == [
        ("a1", service.EVENT_DETAILS_UPDATED),
        ("a2", service.EVENT_DETAILS_UPDATED),
        ("a3", service.EVENT_DETAILS_UPDATED),
    ]
    row = db.tables["notifications"][0]
    assert row["message"] == (
        'The details of "Tech Talk" on 12 Nov 2026, 2:00 PM have been updated. View the event for the latest details.'
    )
    assert (row["entity_type"], row["entity_id"]) == (service.ENTITY_ATTENDEE_EVENT, "s1")


def test_ac5_a_name_change_counts_for_every_session_wherever_it_was_logged(db):
    _confirmed_twice(db)
    _logged(db, "s2", {"name": {"from": "Talk", "to": "Tech Talk"}})

    service.event_reconfirmed("s1")

    assert {recipient for recipient, _ in _sent(db)} == {"a1", "a2", "a3"}


def test_ac9_another_sessions_date_change_is_not_this_sessions_change(db):
    _confirmed_twice(db)
    _logged(db, "s2", {"preferred_start_date": {"from": "2026-11-13", "to": "2026-11-14"}})

    service.event_reconfirmed("s1")

    assert _sent(db) == []


@pytest.mark.parametrize(
    "changes",
    [
        {"equipment": {"from": [], "to": ["mic"]}},
        {"description": {"from": "a", "to": "b"}},
        {"expected_attendance": {"from": 50, "to": 80}},
    ],
)
def test_ac7_no_relevant_change_means_no_notice(db, changes):
    _confirmed_twice(db)
    _logged(db, "s1", changes)

    service.event_reconfirmed("s1")

    assert _sent(db) == []


def test_ac7_a_change_from_before_the_last_confirmation_is_old_news(db):
    _confirmed_twice(db)
    _logged(db, "s1", {"preferred_start_time": {"from": "a", "to": "b"}}, changed_at=T0)

    service.event_reconfirmed("s1")

    assert _sent(db) == []


def test_ac7_a_change_the_organiser_only_asked_for_changed_nothing(db):
    _confirmed_twice(db)
    _logged(db, "s1", {"preferred_start_time": {"from": "a", "to": "b"}}, changed_by=ORG)

    service.event_reconfirmed("s1")

    assert _sent(db) == []


def test_an_organiser_who_is_also_the_coordinator_makes_changes_that_count(db):
    db.rows[0]["coordinator_id"] = ORG
    _confirmed_twice(db)
    _logged(db, "s1", {"preferred_start_time": {"from": "a", "to": "b"}}, changed_by=ORG)

    service.event_reconfirmed("s1")

    assert len(_sent(db)) == 3


def _bookings(db, bookings, history):
    db.tables["venue_bookings"] = [{"event_id": "s1", "venue_name": None, **booking} for booking in bookings]
    db.tables["venue_booking_status_log"] = history


def test_ac5_a_new_venue_is_a_relevant_change(db):
    _confirmed_twice(db)
    _bookings(
        db,
        [{"id": "b1", "venue_id": "v1", "status": "cancelled"}, {"id": "b2", "venue_id": "v2", "status": "confirmed"}],
        [
            {"booking_id": "b1", "to_status": "confirmed", "changed_at": T0},
            {"booking_id": "b1", "to_status": "cancelled", "changed_at": T2},
            {"booking_id": "b2", "to_status": "pending", "changed_at": T2},
            {"booking_id": "b2", "to_status": "confirmed", "changed_at": T3},
        ],
    )

    service.event_reconfirmed("s1")

    assert len(_sent(db)) == 3


def test_ac5_dropping_one_of_several_venues_is_a_relevant_change(db):
    _confirmed_twice(db)
    _bookings(
        db,
        [{"id": "b1", "venue_id": "v1", "status": "confirmed"}, {"id": "b2", "venue_id": "v2", "status": "cancelled"}],
        [
            {"booking_id": "b1", "to_status": "confirmed", "changed_at": T0},
            {"booking_id": "b2", "to_status": "confirmed", "changed_at": T0},
            {"booking_id": "b2", "to_status": "cancelled", "changed_at": T2},
        ],
    )

    service.event_reconfirmed("s1")

    assert len(_sent(db)) == 3


def test_ac7_rebooking_the_same_venue_is_no_change(db):
    _confirmed_twice(db)
    _bookings(
        db,
        [{"id": "b1", "venue_id": "v1", "status": "cancelled"}, {"id": "b2", "venue_id": "v1", "status": "confirmed"}],
        [
            {"booking_id": "b1", "to_status": "confirmed", "changed_at": T0},
            {"booking_id": "b1", "to_status": "cancelled", "changed_at": T2},
            {"booking_id": "b2", "to_status": "confirmed", "changed_at": T3},
        ],
    )

    service.event_reconfirmed("s1")

    assert _sent(db) == []


def test_a_deleted_venue_is_still_told_apart_by_its_kept_name(db):
    _confirmed_twice(db)
    _bookings(
        db,
        [{"id": "b1", "venue_id": None, "venue_name": "Hall A", "status": "cancelled"},
         {"id": "b2", "venue_id": "v2", "status": "confirmed"}],
        [
            {"booking_id": "b1", "to_status": "confirmed", "changed_at": T0},
            {"booking_id": "b1", "to_status": "cancelled", "changed_at": T2},
            {"booking_id": "b2", "to_status": "confirmed", "changed_at": T3},
        ],
    )

    service.event_reconfirmed("s1")

    assert len(_sent(db)) == 3


def test_reconfirming_a_missing_session_writes_nothing(db):
    service.event_reconfirmed("missing")

    assert _sent(db) == []


def test_timestamps_without_a_zone_or_with_z_are_compared_as_utc(db):
    db.tables["event_status_log"] = [
        {"event_id": "s1", "to_status": "confirmed", "changed_at": "2026-10-02T00:00:00Z"},
        {"event_id": "s1", "to_status": "confirmed", "changed_at": "2026-10-05T00:00:00"},
    ]
    _logged(db, "s1", {"preferred_start_time": {"from": "a", "to": "b"}}, changed_at="2026-10-03T00:00:00Z")

    service.event_reconfirmed("s1")

    assert len(_sent(db)) == 3


# -- best effort ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "call",
    [
        lambda: service.registration_recorded(R1_CONFIRMED),
        lambda: service.registration_withdrawn("s1", "a1", "r2"),
        lambda: service.event_cancelled("s1"),
        lambda: service.event_reconfirmed("s1"),
    ],
)
def test_a_failed_attendee_notification_is_logged_and_swallowed(monkeypatch, caplog, call):
    class Broken:
        def table(self, name):
            raise RuntimeError("database down")

    monkeypatch.setattr(service, "supabase", Broken())

    assert call() is None
    assert "Notification not sent" in caplog.text
