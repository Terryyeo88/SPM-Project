"""
app.safety.safety_service -- the Operational Feasibility Check (Week 7
change #6) at unit level, no database. FakeSupabase stands in for both the
service's client and transitions' client, so each test sees exactly which
rows were written and how the session's status moved.

What a unit test can't prove -- the one-pending-per-session unique index,
the profiles/events embeds -- is covered against real Postgres in
test_safety_reviews_integration.py.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from postgrest.exceptions import APIError

import app.events.transitions as transitions
import app.safety.safety_service as safety_service
import app.venues.booking_release as booking_release_module
from app.events.transitions import TransitionConflictError
from app.shared.errors import ValidationError
from tests.factories import make_user
from tests.fake_supabase import FakeSupabase

COORD = "coord-1"
OFFICER = "officer-1"


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase([{"id": "event-1", "status": "planning", "coordinator_id": COORD}])
    monkeypatch.setattr(safety_service, "supabase", fake)
    monkeypatch.setattr(transitions, "supabase", fake)
    # arrangement_problems/review_detail touch expired tentative holds
    # through app.venues.booking_release, which holds its own
    # module-level `supabase` reference -- same fake.
    monkeypatch.setattr(booking_release_module, "supabase", fake)
    monkeypatch.setattr(safety_service, "list_requests_for_event", lambda event_id: [])
    return fake


def _ready(db):
    """A confirmed venue booking and nothing pending: ready to submit."""
    db.tables["venue_bookings"] = [{"id": "b-1", "event_id": "event-1", "status": "confirmed"}]


def _event(status="planning"):
    return SimpleNamespace(id="event-1", status=status, coordinator_id=COORD)


def _pending_review(db, review_id="review-1", event_status="safety_review"):
    db.get("event-1")["status"] = event_status
    db.tables["safety_reviews"] = [
        {
            "id": review_id,
            "event_id": "event-1",
            "status": "pending",
            "submitted_by": COORD,
            "submitted_at": "2026-10-18T01:00:00+00:00",
        }
    ]
    return SimpleNamespace(id=review_id, event_id="event-1", status="pending")


# -- readiness -------------------------------------------------------------------


def test_a_session_with_a_confirmed_venue_and_nothing_pending_is_ready(db):
    _ready(db)
    db.tables["equipment_requests"] = [{"id": "r-1", "event_id": "event-1", "status": "confirmed"}]
    assert safety_service.arrangement_problems("event-1") == []


def test_no_venue_at_all_is_not_ready(db):
    assert safety_service.arrangement_problems("event-1") == [
        "No venue booking has been confirmed for this session yet."
    ]


def test_a_pending_venue_booking_blocks_even_with_another_confirmed(db):
    db.tables["venue_bookings"] = [
        {"id": "b-1", "event_id": "event-1", "status": "confirmed"},
        {"id": "b-2", "event_id": "event-1", "status": "pending"},
    ]
    assert safety_service.arrangement_problems("event-1") == ["A venue booking is still waiting on Venue Staff."]


def test_a_pending_equipment_request_blocks(db):
    _ready(db)
    db.tables["equipment_requests"] = [{"id": "r-1", "event_id": "event-1", "status": "pending"}]
    assert safety_service.arrangement_problems("event-1") == [
        "An equipment request is still waiting on Technical Support Staff."
    ]


def test_rejected_bookings_and_requests_are_history_and_do_not_block(db):
    db.tables["venue_bookings"] = [
        {"id": "b-1", "event_id": "event-1", "status": "rejected"},
        {"id": "b-2", "event_id": "event-1", "status": "confirmed"},
    ]
    db.tables["equipment_requests"] = [{"id": "r-1", "event_id": "event-1", "status": "rejected"}]
    assert safety_service.arrangement_problems("event-1") == []


def test_other_sessions_arrangements_do_not_count(db):
    db.tables["venue_bookings"] = [{"id": "b-1", "event_id": "event-2", "status": "confirmed"}]
    assert safety_service.arrangement_problems("event-1") != []


def test_an_expired_tentative_hold_is_not_a_confirmed_arrangement(db):
    """Sprint 3: a confirmed booking whose hold silently expired while
    this session sat in planning must not count as "ready"."""
    db.tables["venue_bookings"] = [
        {
            "id": "b-1",
            "event_id": "event-1",
            "status": "confirmed",
            "confirmed_at": "2020-01-01T00:00:00+00:00",
            "hold_minutes": 60,
        }
    ]

    assert safety_service.arrangement_problems("event-1") == [
        "No venue booking has been confirmed for this session yet."
    ]
    assert db.tables["venue_bookings"][0]["status"] == "released"


# -- submit ----------------------------------------------------------------------


def test_submit_writes_a_pending_review_and_moves_the_session_to_safety_review(db):
    _ready(db)
    result = safety_service.submit_for_safety_check(_event(), COORD)

    assert result["review"]["status"] == "pending"
    assert result["review"]["submitted_by"] == COORD
    assert result["event"]["status"] == "safety_review"
    assert db.get("event-1")["status"] == "safety_review"
    [history] = db.tables["event_status_log"]
    assert (history["from_status"], history["to_status"], history["changed_by"]) == ("planning", "safety_review", COORD)


def test_submit_refused_when_arrangements_are_not_ready(db):
    with pytest.raises(ValidationError) as exc_info:
        safety_service.submit_for_safety_check(_event(), COORD)

    assert "No venue booking has been confirmed" in exc_info.value.message
    assert db.tables.get("safety_reviews", []) == []
    assert db.get("event-1")["status"] == "planning"


def test_a_second_pending_review_is_refused_clearly(db, monkeypatch):
    """The one-pending-per-session unique index refuses the insert (23505)."""
    _ready(db)

    def refuse(_payload):
        raise APIError({"message": "duplicate key", "code": "23505", "hint": None, "details": None})

    real_table = db.table

    def table(name):
        query = real_table(name)
        if name == "safety_reviews":
            query.insert = refuse
        return query

    monkeypatch.setattr(db, "table", table)
    with pytest.raises(ValidationError) as exc_info:
        safety_service.submit_for_safety_check(_event(), COORD)
    assert exc_info.value.message == "This session is already waiting for a safety check."
    assert db.get("event-1")["status"] == "planning"


def test_a_submit_whose_status_change_fails_leaves_no_review_behind(db):
    """The session moved on between authz and the write (it was cancelled):
    the 409 reaches the caller and the pending review just written is
    deleted again."""
    _ready(db)
    db.get("event-1")["status"] = "cancelled"
    with pytest.raises(TransitionConflictError):
        safety_service.submit_for_safety_check(_event("planning"), COORD)
    assert db.tables["safety_reviews"] == []


# -- decide ----------------------------------------------------------------------


def test_approve_records_the_decision_and_leaves_the_status_for_the_coordinator(db):
    review = _pending_review(db)
    decided = safety_service.decide_review("review-1", review, "approved", OFFICER, None)

    assert decided["status"] == "approved"
    assert decided["reviewed_by"] == OFFICER
    assert decided["reviewed_at"]
    assert decided["comment"] is None
    assert db.get("event-1")["status"] == "safety_review"
    assert db.tables.get("event_status_log", []) == []


def test_approve_keeps_an_optional_comment(db):
    review = _pending_review(db)
    decided = safety_service.decide_review("review-1", review, "approved", OFFICER, "  Exits clear.  ")
    assert decided["comment"] == "Exits clear."


@pytest.mark.parametrize("decision", ["rejected", "changes_requested"])
def test_reject_or_request_changes_sends_the_session_back_to_planning_with_the_comment(db, decision):
    review = _pending_review(db)
    decided = safety_service.decide_review("review-1", review, decision, OFFICER, "Fire exit blocked by stage.")

    assert decided["status"] == decision
    assert decided["comment"] == "Fire exit blocked by stage."
    assert db.get("event-1")["status"] == "planning"
    [history] = db.tables["event_status_log"]
    assert (history["from_status"], history["to_status"], history["changed_by"], history["reason"]) == (
        "safety_review",
        "planning",
        OFFICER,
        "Fire exit blocked by stage.",
    )


@pytest.mark.parametrize("decision", ["rejected", "changes_requested"])
@pytest.mark.parametrize("comment", [None, "", "   "])
def test_reject_or_request_changes_needs_a_comment(db, decision, comment):
    review = _pending_review(db)
    with pytest.raises(ValidationError):
        safety_service.decide_review("review-1", review, decision, OFFICER, comment)
    assert db.tables["safety_reviews"][0]["status"] == "pending"
    assert db.get("event-1")["status"] == "safety_review"


def test_a_non_text_comment_is_refused(db):
    review = _pending_review(db)
    with pytest.raises(ValidationError):
        safety_service.decide_review("review-1", review, "approved", OFFICER, 42)


def test_an_unknown_decision_is_refused(db):
    review = _pending_review(db)
    with pytest.raises(ValidationError):
        safety_service.decide_review("review-1", review, "pending", OFFICER, "x")


def test_a_session_no_longer_in_safety_review_cannot_be_decided(db):
    """The coordinator cancelled it while it was waiting."""
    review = _pending_review(db, event_status="cancelled")
    with pytest.raises(ValidationError) as exc_info:
        safety_service.decide_review("review-1", review, "approved", OFFICER, None)
    assert "no longer waiting" in exc_info.value.message
    assert db.tables["safety_reviews"][0]["status"] == "pending"


def test_a_second_decision_racing_the_first_is_refused(db):
    """Loaded as pending, but decided by someone else before this write:
    the conditional update matches nothing."""
    review = _pending_review(db)
    db.tables["safety_reviews"][0]["status"] = "approved"
    with pytest.raises(ValidationError) as exc_info:
        safety_service.decide_review("review-1", review, "rejected", OFFICER, "Too crowded.")
    assert "no longer pending" in exc_info.value.message
    assert db.get("event-1")["status"] == "safety_review"


def test_the_decision_stands_if_the_session_moves_on_between_the_two_writes(db, monkeypatch):
    review = _pending_review(db)

    def conflict(*args, **kwargs):
        raise TransitionConflictError("moved")

    monkeypatch.setattr(safety_service, "transition", conflict)
    decided = safety_service.decide_review("review-1", review, "rejected", OFFICER, "Too crowded.")
    assert decided["status"] == "rejected"


# -- review_detail: expired holds are never shown as live arrangements --------------


def test_review_detail_excludes_an_expired_tentative_hold(db):
    db.tables["safety_reviews"] = [
        {"id": "review-1", "event_id": "event-1", "status": "pending", "submitted_at": "2026-10-18T01:00:00+00:00"}
    ]
    db.tables["venue_bookings"] = [
        {
            "id": "b-1",
            "event_id": "event-1",
            "venue_id": "venue-1",
            "status": "confirmed",
            "confirmed_at": "2020-01-01T00:00:00+00:00",
            "hold_minutes": 60,
        }
    ]
    review = SimpleNamespace(id="review-1", event_id="event-1", status="pending")

    detail = safety_service.review_detail(review)

    assert detail["venue_bookings"] == []
    assert db.tables["venue_bookings"][0]["status"] == "released"


def test_review_detail_includes_a_still_live_confirmed_booking(db):
    db.tables["safety_reviews"] = [
        {"id": "review-1", "event_id": "event-1", "status": "pending", "submitted_at": "2026-10-18T01:00:00+00:00"}
    ]
    db.tables["venue_bookings"] = [
        {"id": "b-1", "event_id": "event-1", "venue_id": "venue-1", "status": "confirmed"}
    ]
    review = SimpleNamespace(id="review-1", event_id="event-1", status="pending")

    detail = safety_service.review_detail(review)

    assert [b["id"] for b in detail["venue_bookings"]] == ["b-1"]


# -- is_approved (confirm's gate) --------------------------------------------------


def _reviews(db, *statuses):
    db.tables["safety_reviews"] = [
        {"id": f"r-{i}", "event_id": "event-1", "status": status, "submitted_at": f"2026-10-1{i}T00:00:00+00:00"}
        for i, status in enumerate(statuses)
    ]


def test_is_approved_reads_the_latest_review_only(db):
    _reviews(db, "approved", "changes_requested")  # approved once, then resubmitted and sent back
    assert safety_service.is_approved("event-1") is False
    _reviews(db, "changes_requested", "approved")
    assert safety_service.is_approved("event-1") is True


def test_is_approved_is_false_with_no_review_or_a_pending_one(db):
    assert safety_service.is_approved("event-1") is False
    _reviews(db, "pending")
    assert safety_service.is_approved("event-1") is False


# -- the dashboard list ------------------------------------------------------------


def test_list_is_empty_for_anyone_but_a_safety_officer(db):
    db.tables["safety_reviews"] = [{"id": "r-1", "event_id": "event-1", "status": "pending", "events": {}}]
    assert safety_service.list_reviews(make_user(["event_coordinator"])) == []


def test_list_embeds_each_session_and_hides_pending_reviews_of_sessions_that_moved_on(db):
    db.tables["safety_reviews"] = [
        {
            "id": "r-1",
            "event_id": "e-1",
            "status": "pending",
            "submitted_at": "2",
            "events": {"id": "e-1", "status": "safety_review"},
        },
        {
            "id": "r-2",
            "event_id": "e-2",
            "status": "pending",
            "submitted_at": "3",
            "events": {"id": "e-2", "status": "cancelled"},
        },
        {
            "id": "r-3",
            "event_id": "e-3",
            "status": "approved",
            "submitted_at": "1",
            "events": {"id": "e-3", "status": "confirmed"},
            "reviewer": {"name": "Hannah Lee"},
        },
    ]
    reviews = safety_service.list_reviews(make_user(["safety_officer"]))

    assert [r["id"] for r in reviews] == ["r-1", "r-3"]  # newest first; r-2's session was cancelled
    assert reviews[0]["event"] == {"id": "e-1", "status": "safety_review"}
    assert reviews[1]["reviewed_by_name"] == "Hannah Lee"
    assert "events" not in reviews[0]


def test_list_rejects_an_unknown_status_filter(db):
    with pytest.raises(ValidationError):
        safety_service.list_reviews(make_user(["safety_officer"]), "maybe")
