"""Overwrite Venue Booking: "As a Venue Staff, I want to overwrite the
previously approved venue booking, so that the event will not have an
unsuitable venue."

POST /venues/bookings/<booking_id>/overwrite (app.venues.routes) ->
app.venues.booking_release.release_booking + an in-route event-revert
step, gated by venue_booking.overwrite (rule_venue_booking_overwrite).
Unit-level: the shared FakeSupabase stands in for the booking release
module and the route's event lookup, so these run the real route, loader,
authz rule and release logic together -- same style as
test_venue_booking_cancel.py.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

import app.auth.context as context_module
import app.events.transitions as transitions
import app.safety.safety_service as safety_service
import app.venues.booking_release as booking_release
import app.venues.booking_service as booking_service
import app.venues.routes as venues_routes
from app.authz import actions
from app.authz.policy import authorise, can
from app.notifications import notification_service
from app.shared.errors import AuthorisationError, NotFoundError
from app.venues.booking_release import release_booking
from tests.factories import make_user
from tests.fake_supabase import FakeSupabase

VENUE_STAFF = "staff-1"
DAY = (date.today() + timedelta(days=30)).isoformat()


def _booking(booking_id, *, event_id="session-1", status="confirmed", venue_id=None, requested_by="coord-1"):
    return {
        "id": booking_id,
        "event_id": event_id,
        "venue_id": venue_id or f"venue-{booking_id}",
        "status": status,
        "requested_by": requested_by,
        "setup_minutes": 30,
        "turnaround_minutes": 30,
        "booking_start": f"{DAY}T08:30:00+08:00",
        "booking_end": f"{DAY}T17:30:00+08:00",
    }


@pytest.fixture
def fake(monkeypatch):
    db = FakeSupabase(
        [
            {"id": "session-1", "coordinator_id": "coord-1", "status": "planning"},
            {"id": "session-2", "coordinator_id": "coord-1", "status": "planning"},
        ]
    )
    db.tables["venue_bookings"] = [
        _booking("main-hall"),
        _booking("breakout-room"),
        _booking("overflow-room", status="pending"),
        _booking("other-session", event_id="session-2"),
    ]
    monkeypatch.setattr(booking_release, "supabase", db)
    monkeypatch.setattr(booking_service, "supabase", db)
    monkeypatch.setattr(venues_routes, "supabase", db)
    monkeypatch.setattr(transitions, "supabase", db)
    monkeypatch.setattr(safety_service, "supabase", db)
    return db


def _row(fake, booking_id):
    return next(row for row in fake.tables["venue_bookings"] if row["id"] == booking_id)


def _ns(fake, booking_id):
    return SimpleNamespace(**dict(_row(fake, booking_id)))


def _ns_with_event(fake, booking_id):
    booking = _ns(fake, booking_id)
    booking.event_status = fake.get(booking.event_id)["status"]
    return booking


def _status_log(fake):
    return fake.tables.get("venue_booking_status_log", [])


def _mock_profile(monkeypatch, roles):
    monkeypatch.setattr(
        context_module, "_load_profile_with_roles", lambda user_id: ("Test User", "t@example.com", frozenset(roles))
    )
    monkeypatch.setattr(context_module, "_get_last_active", lambda session_id: None)
    monkeypatch.setattr(context_module, "_touch_session_activity", lambda *a, **k: None)


def _auth(signing_key, user_id=VENUE_STAFF):
    return {"Authorization": f"Bearer {signing_key.make_token(sub=user_id)}"}


# -- the service half: release_booking is the actual write -------------------


def test_overwriting_releases_the_booking_and_leaves_every_other_booking_untouched(fake):
    others_before = [dict(row) for row in fake.tables["venue_bookings"] if row["id"] != "main-hall"]

    overwritten = release_booking("main-hall", dict(_row(fake, "main-hall")), "Burst pipe.", changed_by=VENUE_STAFF)

    assert overwritten["status"] == "released"
    assert _row(fake, "main-hall")["status"] == "released"
    assert [row for row in fake.tables["venue_bookings"] if row["id"] != "main-hall"] == others_before


def test_overwriting_is_recorded_with_who_when_and_why(fake):
    release_booking("main-hall", dict(_row(fake, "main-hall")), "Burst pipe in the ceiling.", changed_by=VENUE_STAFF)

    assert len(_status_log(fake)) == 1
    entry = _status_log(fake)[0]
    assert entry["booking_id"] == "main-hall"
    assert entry["from_status"] == "confirmed"
    assert entry["to_status"] == "released"
    assert entry["changed_by"] == VENUE_STAFF
    assert entry["reason"] == "Burst pipe in the ceiling."


# -- authz: venue_booking.overwrite -------------------------------------------


def _resource(status="confirmed"):
    return SimpleNamespace(id="booking-1", status=status)


def test_venue_staff_may_overwrite_a_confirmed_booking():
    user = make_user(["venue_staff"], user_id=VENUE_STAFF)
    assert can(user, actions.VENUE_BOOKING_OVERWRITE, _resource()) is True


@pytest.mark.parametrize("status", ["pending", "rejected", "released", "cancelled"])
def test_only_a_confirmed_booking_can_be_overwritten(status):
    user = make_user(["venue_staff"], user_id=VENUE_STAFF)
    with pytest.raises(AuthorisationError):
        authorise(user, actions.VENUE_BOOKING_OVERWRITE, _resource(status=status))


@pytest.mark.parametrize(
    "roles",
    [["event_coordinator"], ["event_organizer"], ["event_coordinator_lead"], ["safety_officer"]],
)
def test_nobody_but_venue_staff_may_overwrite_a_booking(roles):
    user = make_user(roles, user_id="someone-else")
    with pytest.raises(NotFoundError):
        authorise(user, actions.VENUE_BOOKING_OVERWRITE, _resource())


# -- the route: event-revert behaviour ----------------------------------------


def test_the_route_overwrites_the_booking(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch, ["venue_staff"])

    response = client.post(
        "/venues/bookings/main-hall/overwrite", headers=_auth(signing_key), json={"reason": "Burst pipe."}
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["status"] == "released"
    assert _row(fake, "main-hall")["status"] == "released"


def test_the_route_reverts_a_confirmed_event_to_planning(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch, ["venue_staff"])
    fake.get("session-1")["status"] = "confirmed"

    response = client.post(
        "/venues/bookings/main-hall/overwrite", headers=_auth(signing_key), json={"reason": "Burst pipe."}
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["event_reverted_to_planning"] is True
    assert fake.get("session-1")["status"] == "planning"
    log = fake.tables["event_status_log"]
    assert len(log) == 1
    assert (log[0]["from_status"], log[0]["to_status"], log[0]["changed_by"]) == ("confirmed", "planning", VENUE_STAFF)
    assert "Burst pipe." in log[0]["reason"]


def test_the_route_reverts_a_safety_review_event_to_planning(client, signing_key, monkeypatch, fake):
    """Team decision (2026-11-03): don't waste a Safety Officer's time
    reviewing a session whose venue was just overwritten -- same
    REVERT_TO_PLANNING scope as venue_service.delete_venue, not
    cancel_booking's narrower "confirmed only"."""
    _mock_profile(monkeypatch, ["venue_staff"])
    fake.get("session-1")["status"] = "safety_review"

    response = client.post(
        "/venues/bookings/main-hall/overwrite", headers=_auth(signing_key), json={"reason": "Burst pipe."}
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["event_reverted_to_planning"] is True
    assert fake.get("session-1")["status"] == "planning"
    log = fake.tables["event_status_log"]
    assert len(log) == 1
    assert (log[0]["from_status"], log[0]["to_status"]) == ("safety_review", "planning")


def test_overwriting_withdraws_a_pending_safety_review(client, signing_key, monkeypatch, fake):
    fake.get("session-1")["status"] = "safety_review"
    fake.tables["safety_reviews"] = [{"id": "review-1", "event_id": "session-1", "status": "pending"}]
    _mock_profile(monkeypatch, ["venue_staff"])

    client.post(
        "/venues/bookings/main-hall/overwrite", headers=_auth(signing_key), json={"reason": "Burst pipe."}
    )

    [review] = fake.tables["safety_reviews"]
    assert review["status"] == "changes_requested"
    assert review["reviewed_by"] == VENUE_STAFF


def test_overwriting_with_no_pending_review_does_not_error(client, signing_key, monkeypatch, fake):
    fake.get("session-1")["status"] = "safety_review"
    _mock_profile(monkeypatch, ["venue_staff"])

    response = client.post(
        "/venues/bookings/main-hall/overwrite", headers=_auth(signing_key), json={"reason": "Burst pipe."}
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["event_reverted_to_planning"] is True


def test_an_event_in_planning_keeps_its_status(client, signing_key, monkeypatch, fake):
    """planning is the one status this route never reverts from -- there's
    nothing to revert, the event never left planning."""
    _mock_profile(monkeypatch, ["venue_staff"])

    response = client.post(
        "/venues/bookings/main-hall/overwrite", headers=_auth(signing_key), json={"reason": "Burst pipe."}
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["event_reverted_to_planning"] is False
    assert fake.get("session-1")["status"] == "planning"
    assert fake.tables.get("event_status_log", []) == []


def test_transition_is_never_attempted_for_a_planning_event(client, signing_key, monkeypatch, fake):
    """Proves the route's own event_status-in-scope guard is what skips the
    revert, not just transition()'s own expected_from race-guard happening
    to refuse it -- the two are redundant defense-in-depth, and this
    isolates the first one specifically, so removing it is still caught
    even though the observable outcome would otherwise be identical
    either way."""
    _mock_profile(monkeypatch, ["venue_staff"])
    calls = []
    monkeypatch.setattr(venues_routes, "transition", lambda *a, **k: calls.append((a, k)))

    client.post("/venues/bookings/main-hall/overwrite", headers=_auth(signing_key), json={"reason": "Burst pipe."})

    assert calls == []


def test_the_overwrite_stands_if_the_event_moved_on_since_it_was_loaded(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch, ["venue_staff"])
    fake.get("session-1")["status"] = "confirmed"
    # Simulate a race: the loader already saw "confirmed", but the event
    # moved on (e.g. was cancelled) by the time the route's own
    # transition() call runs.
    original_transition = transitions.transition

    def racing_transition(event_id, *args, **kwargs):
        fake.get("session-1")["status"] = "cancelled"
        return original_transition(event_id, *args, **kwargs)

    monkeypatch.setattr(venues_routes, "transition", racing_transition)

    response = client.post(
        "/venues/bookings/main-hall/overwrite", headers=_auth(signing_key), json={"reason": "Burst pipe."}
    )

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["event_reverted_to_planning"] is False
    assert _row(fake, "main-hall")["status"] == "released"
    assert fake.get("session-1")["status"] == "cancelled"


# -- the route: validation and authz --------------------------------------------


def test_the_route_needs_a_reason(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch, ["venue_staff"])

    response = client.post("/venues/bookings/main-hall/overwrite", headers=_auth(signing_key), json={})

    assert response.status_code == 400
    assert _row(fake, "main-hall")["status"] == "confirmed"


@pytest.mark.parametrize("reason", ["", "   "])
def test_the_route_refuses_a_blank_reason(client, signing_key, monkeypatch, fake, reason):
    _mock_profile(monkeypatch, ["venue_staff"])

    response = client.post(
        "/venues/bookings/main-hall/overwrite", headers=_auth(signing_key), json={"reason": reason}
    )

    assert response.status_code == 400
    assert _row(fake, "main-hall")["status"] == "confirmed"


def test_the_route_refuses_a_pending_booking(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch, ["venue_staff"])

    response = client.post(
        "/venues/bookings/overflow-room/overwrite", headers=_auth(signing_key), json={"reason": "x"}
    )

    assert response.status_code == 403
    assert _row(fake, "overflow-room")["status"] == "pending"


def test_the_route_refuses_a_non_venue_staff_caller_with_a_404(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch, ["event_coordinator"])

    response = client.post(
        "/venues/bookings/main-hall/overwrite", headers=_auth(signing_key, "coord-1"), json={"reason": "x"}
    )

    assert response.status_code == 404
    assert _row(fake, "main-hall")["status"] == "confirmed"


def test_the_route_404s_for_an_unknown_booking(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch, ["venue_staff"])

    response = client.post("/venues/bookings/nope/overwrite", headers=_auth(signing_key), json={"reason": "x"})

    assert response.status_code == 404


# -- the route: notification (AC3) --------------------------------------------


def test_the_route_notifies_the_coordinator(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch, ["venue_staff"])
    seen = []
    monkeypatch.setattr(notification_service, "venue_booking_overwritten", lambda *a: seen.append(a))

    client.post("/venues/bookings/main-hall/overwrite", headers=_auth(signing_key), json={"reason": "Burst pipe."})

    assert len(seen) == 1
    booking_arg, reason_arg = seen[0]
    assert booking_arg["id"] == "main-hall"
    assert reason_arg == "Burst pipe."


def test_a_refused_overwrite_notifies_nobody(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch, ["venue_staff"])
    seen = []
    monkeypatch.setattr(notification_service, "venue_booking_overwritten", lambda *a: seen.append(a))

    client.post("/venues/bookings/main-hall/overwrite", headers=_auth(signing_key), json={})

    assert seen == []
