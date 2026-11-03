"""
IS-24 Notification (Event Coordinator): WHEN the two new notifications are
triggered. Each hook runs only once its own change has been written, and
hands its arguments, untouched, to notification_service. Who is told what is
test_notification_event_coordinator.py's job.
"""

from __future__ import annotations

import pytest

import app.events.change_request_service as change_service
import app.notifications.notification_service as notification_service
import app.venues.block_service as block_service
from app.shared.errors import ValidationError
from tests.test_block_service import _block_body, _booking
from tests.test_block_service import fake_db as block_db  # noqa: F401 -- fixture
from tests.test_event_change_requests import ORGANISER, _event, request_event_change
from tests.test_event_change_requests import fake as change_fake  # noqa: F401 -- fixture


@pytest.fixture
def news(monkeypatch):
    seen = []
    monkeypatch.setattr(notification_service, "venue_booking_blocked", lambda *a: seen.append(("blocked", a)))
    monkeypatch.setattr(notification_service, "event_change_requested", lambda *a: seen.append(("change", a)))
    return seen


def test_the_hooks_pass_their_arguments_to_the_notification_service(news):
    block_service._notify_coordinator_venue_blocked({"id": "b1", "event_id": "s1"})
    change_service._notify_change_requested("s1")

    assert news == [("blocked", ({"id": "b1", "event_id": "s1"},)), ("change", ("s1",))]


# -- AC3: a significant change request -------------------------------------------------------


@pytest.mark.parametrize(
    "changes",
    [
        {"expected_attendance": 150},
        {"room_layout": "classroom"},
        {"expected_attendance": 150, "special_requests": "Vegetarian lunch."},
    ],
)
def test_a_significant_change_request_triggers_the_hook(change_fake, news, changes):  # noqa: F811
    request_event_change(_event(change_fake), ORGANISER, {"changes": changes})

    assert news == [("change", ("session-1",))]


@pytest.mark.parametrize("changes", [{"name": "Community Summit"}, {"special_requests": "Vegetarian lunch."}])
def test_an_ordinary_change_request_triggers_nothing(change_fake, news, changes):  # noqa: F811
    request_event_change(_event(change_fake), ORGANISER, {"changes": changes})

    assert news == []


def test_a_refused_change_request_triggers_nothing(change_fake, news):  # noqa: F811
    with pytest.raises(ValidationError):
        request_event_change(_event(change_fake), ORGANISER, {"changes": {"room_layout": "theatre"}})
    request_event_change(_event(change_fake), ORGANISER, {"changes": {"expected_attendance": 150}})
    news.clear()

    with pytest.raises(Exception, match="already has a change request"):
        request_event_change(_event(change_fake), ORGANISER, {"changes": {"expected_attendance": 160}})

    assert news == []


# -- AC4: a venue blocked under a booking ----------------------------------------------------


def test_a_block_triggers_the_hook_once_for_each_booking_it_released(block_db, news):  # noqa: F811
    block_db.tables["venues"] = [{"id": "venue-1"}]
    block_db.tables["venue_bookings"] = [
        _booking("booking-1", event_id="event-1"),
        _booking("booking-2", event_id="event-2"),
        _booking("booking-3", event_id="event-3", status="pending"),
    ]

    block_service.create_venue_block("venue-1", _block_body(), "staff-1")

    assert [(kind, args[0]["id"], args[0]["event_id"]) for kind, args in news] == [
        ("blocked", "booking-1", "event-1"),
        ("blocked", "booking-2", "event-2"),
    ]


def test_a_block_that_releases_nothing_triggers_nothing(block_db, news):  # noqa: F811
    block_db.tables["venues"] = [{"id": "venue-1"}]

    block_service.create_venue_block("venue-1", _block_body(), "staff-1")

    assert news == []


def test_a_refused_block_triggers_nothing(block_db, news):  # noqa: F811
    block_db.tables["venues"] = [{"id": "venue-1"}]
    block_db.tables["venue_bookings"] = [_booking("booking-1")]

    with pytest.raises(ValidationError):
        block_service.create_venue_block("venue-1", _block_body(reason="nonsense"), "staff-1")

    assert news == []
