"""
Unit tests for IS-11 AC5's booking half (Nawaz, 6 Nov): a new venue booking
request must fit inside the venue's daily operating hours, setup and
turnaround included (booking_service._check_operating_hours).

Agreed with Aaralyn (product owner) on 6 Nov: hours are optional, one
window per venue that is the same every day, and existing bookings stay as
they are when the hours change -- only new requests are checked.

Reuses test_booking_service.py's fake client and row builders.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.venues.booking_service as service_module
from app.shared.errors import ValidationError
from tests.test_booking_service import _booking, _event, _venue, fake_db  # noqa: F401


def _hours(opens="08:00:00", closes="20:00:00", **overrides):
    # The database returns time columns with seconds.
    return _venue(operating_hours_start=opens, operating_hours_end=closes, **overrides)


def _request(fake_db, **event_overrides):  # noqa: F811
    return service_module.create_booking_request(_event(**event_overrides), "venue-1", "coord-1")


def _booking_rows(fake_db):  # noqa: F811
    return [row for table, row in fake_db.inserts if table == "venue_bookings"]


def test_a_request_inside_operating_hours_is_accepted(fake_db):  # noqa: F811
    fake_db.tables["venues"] = [_hours()]

    booking = _request(fake_db, preferred_start_time="09:00", preferred_end_time="17:00")

    assert booking["status"] == "pending"


def test_a_request_filling_the_hours_exactly_is_accepted(fake_db):  # noqa: F811
    # 08:30-19:30 plus 30 minutes either side is exactly 08:00-20:00.
    fake_db.tables["venues"] = [_hours()]

    booking = _request(fake_db, preferred_start_time="08:30", preferred_end_time="19:30")

    assert (booking["booking_start"], booking["booking_end"]) == (
        "2026-11-01T08:00:00+08:00",
        "2026-11-01T20:00:00+08:00",
    )


def test_setup_time_before_opening_is_refused(fake_db):  # noqa: F811
    """The event starts after opening, but its setup doesn't."""
    fake_db.tables["venues"] = [_hours()]

    with pytest.raises(ValidationError) as refused:
        _request(fake_db, preferred_start_time="08:15", preferred_end_time="12:00")

    assert str(refused.value) == (
        "Test Venue is open 08:00-20:00 daily. This booking, including 30 minutes of setup and "
        "30 minutes of turnaround, runs from 01 Nov 07:45 to 01 Nov 12:30, which is outside those hours."
    )
    assert _booking_rows(fake_db) == []


def test_turnaround_time_after_closing_is_refused(fake_db):  # noqa: F811
    fake_db.tables["venues"] = [_hours(turnaround=60)]

    with pytest.raises(ValidationError, match="outside those hours"):
        _request(fake_db, preferred_start_time="15:00", preferred_end_time="19:30")
    assert _booking_rows(fake_db) == []


def test_an_event_starting_before_opening_is_refused(fake_db):  # noqa: F811
    fake_db.tables["venues"] = [_hours()]

    with pytest.raises(ValidationError, match="outside those hours"):
        _request(fake_db, preferred_start_time="06:00", preferred_end_time="10:00")


def test_a_booking_running_past_midnight_is_refused(fake_db):  # noqa: F811
    """Turnaround after a late session ends at 00:00 the next day, past a
    23:59 closing time."""
    fake_db.tables["venues"] = [_hours(opens="07:00:00", closes="23:59:00")]

    with pytest.raises(ValidationError, match="runs from 01 Nov 21:30 to 02 Nov 00:00"):
        _request(fake_db, preferred_start_time="22:00", preferred_end_time="23:30")


def test_a_venue_open_until_midnight_takes_a_booking_ending_at_midnight(fake_db):  # noqa: F811
    """08:00-00:00 is "open until midnight": turnaround may end at 00:00."""
    fake_db.tables["venues"] = [_hours(opens="08:00:00", closes="00:00:00")]

    booking = _request(fake_db, preferred_start_time="22:00", preferred_end_time="23:30")

    assert booking["booking_end"] == "2026-11-02T00:00:00+08:00"


def test_an_overnight_venue_takes_a_booking_running_past_midnight(fake_db):  # noqa: F811
    """20:00-01:00: a 21:00-00:30 session plus 30 minutes either side is
    20:30 to 01:00 the next day, inside the window."""
    fake_db.tables["venues"] = [_hours(opens="20:00:00", closes="01:00:00")]

    booking = _request(
        fake_db,
        preferred_start_date="2026-11-01",
        preferred_end_date="2026-11-02",
        preferred_start_time="21:00",
        preferred_end_time="00:30",
    )

    assert (booking["booking_start"], booking["booking_end"]) == (
        "2026-11-01T20:30:00+08:00",
        "2026-11-02T01:00:00+08:00",
    )


def test_an_overnight_venue_takes_a_booking_after_midnight(fake_db):  # noqa: F811
    """The window that opened at 20:00 the night before is still open at 00:30."""
    fake_db.tables["venues"] = [_hours(opens="20:00:00", closes="02:00:00")]

    booking = _request(fake_db, preferred_start_time="00:30", preferred_end_time="01:00")

    assert booking["status"] == "pending"


def test_an_overnight_venue_refuses_a_booking_past_closing(fake_db):  # noqa: F811
    fake_db.tables["venues"] = [_hours(opens="20:00:00", closes="01:00:00")]

    with pytest.raises(ValidationError) as refused:
        _request(
            fake_db,
            preferred_start_date="2026-11-01",
            preferred_end_date="2026-11-02",
            preferred_start_time="22:00",
            preferred_end_time="01:00",
        )

    assert str(refused.value).startswith("Test Venue is open 20:00-01:00 (next day) daily.")
    assert _booking_rows(fake_db) == []


def test_an_overnight_venue_refuses_a_booking_in_its_daytime_gap(fake_db):  # noqa: F811
    fake_db.tables["venues"] = [_hours(opens="20:00:00", closes="01:00:00")]

    with pytest.raises(ValidationError, match="outside those hours"):
        _request(fake_db, preferred_start_time="12:00", preferred_end_time="14:00")


def test_a_multi_day_session_is_refused_at_a_venue_with_hours(fake_db):  # noqa: F811
    """One window per day: a session running over several days would be in
    the venue overnight. See docs/open-questions.md."""
    fake_db.tables["venues"] = [_hours()]

    with pytest.raises(ValidationError, match="outside those hours"):
        _request(
            fake_db,
            preferred_start_date="2026-11-01",
            preferred_end_date="2026-11-02",
            preferred_start_time="09:00",
            preferred_end_time="17:00",
        )


def test_a_venue_without_operating_hours_takes_any_time(fake_db):  # noqa: F811
    fake_db.tables["venues"] = [_venue(operating_hours_start=None, operating_hours_end=None)]

    booking = _request(
        fake_db,
        preferred_start_date="2026-11-01",
        preferred_end_date="2026-11-02",
        preferred_start_time="02:00",
        preferred_end_time="05:00",
    )

    assert booking["status"] == "pending"


def test_a_venue_row_without_the_hours_columns_takes_any_time(fake_db):  # noqa: F811
    fake_db.tables["venues"] = [_venue()]

    booking = _request(fake_db, preferred_start_time="02:00", preferred_end_time="05:00")

    assert booking["status"] == "pending"


def test_hours_without_seconds_are_read_too(fake_db):  # noqa: F811
    fake_db.tables["venues"] = [_hours(opens="08:00", closes="20:00")]

    with pytest.raises(ValidationError, match="open 08:00-20:00 daily"):
        _request(fake_db, preferred_start_time="19:00", preferred_end_time="20:00")


def test_a_refused_request_notifies_no_one(fake_db, monkeypatch):  # noqa: F811
    fake_db.tables["venues"] = [_hours()]
    notified = []
    monkeypatch.setattr(service_module, "_notify_venue_staff", lambda *args, **kwargs: notified.append(args))

    with pytest.raises(ValidationError):
        _request(fake_db, preferred_start_time="06:00", preferred_end_time="10:00")

    assert notified == []


def test_an_existing_pending_request_outside_new_hours_can_still_be_confirmed(fake_db):  # noqa: F811
    """Existing bookings stay as they are when the hours change (Aaralyn,
    6 Nov): only a NEW request is checked, so Venue Staff can still approve
    one made before the hours were set."""
    fake_db.tables["venues"] = [_hours()]
    early = {"booking_start": "2026-11-01T06:00:00+08:00", "booking_end": "2026-11-01T10:00:00+08:00"}
    fake_db.tables["venue_bookings"] = [_booking(status="pending", **early)]

    result = service_module.confirm_booking(
        "booking-1", SimpleNamespace(**_booking(status="pending", **early)), "staff-1"
    )

    assert result["status"] == "confirmed"
