"""
Event Review and Approval -- the coordinator's Approve / Reject decision,
the rejection reason the organiser then sees, the events list (organiser's
list / coordinator's queue), plus GET /events/coordinators (the Reassign
dropdown's choices).

Unit-level like test_events_routes.py: no real Supabase. Route tests
monkeypatch the loader/service functions to test routing + authz wiring;
the service tests swap event_service's `supabase` for a small fake to
test the status update, the audit-log write and the "still under review"
guard.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.auth.context as context_module
import app.events.event_service as service_module
import app.events.routes as routes_module
import app.events.transitions as transitions_module
from app.authz import actions
from app.authz.policy import can
from app.events.transitions import TransitionConflictError
from app.shared.errors import ValidationError
from tests.factories import FakeEvent, make_user
from tests.fake_supabase import FakeSupabase


def _mock_profile(monkeypatch, roles):
    monkeypatch.setattr(
        context_module,
        "_load_profile_with_roles",
        lambda user_id: ("Test User", "test@example.com", frozenset(roles)),
    )
    monkeypatch.setattr(context_module, "_get_last_active", lambda session_id: None)
    monkeypatch.setattr(context_module, "_touch_session_activity", lambda *a, **k: None)


def _auth(signing_key, user_id="user-1"):
    return {"Authorization": f"Bearer {signing_key.make_token(sub=user_id)}"}


# -- POST /events/<id>/approve --------------------------------------------


def test_approve_route_approves_for_assigned_coordinator(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    event = FakeEvent(id="event-1", coordinator_id="user-1", status="under_review")
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: event)
    calls = []

    def fake_approve(event_id, loaded, approved_by):
        calls.append((event_id, approved_by))
        return {"id": event_id, "status": "approved"}

    monkeypatch.setattr(routes_module, "approve_event_request", fake_approve)

    response = client.post("/events/event-1/approve", headers=_auth(signing_key))

    assert response.status_code == 200
    assert response.get_json()["status"] == "approved"
    assert calls == [("event-1", "user-1")]


def test_approve_route_404_for_coordinator_not_assigned(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    event = FakeEvent(id="event-1", coordinator_id="someone-else", status="under_review")
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: event)
    called = []
    monkeypatch.setattr(routes_module, "approve_event_request", lambda *a: called.append(a))

    response = client.post("/events/event-1/approve", headers=_auth(signing_key))

    assert response.status_code == 404
    assert called == []


def test_approve_route_403_when_not_under_review(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    event = FakeEvent(id="event-1", coordinator_id="user-1", status="approved")
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: event)
    called = []
    monkeypatch.setattr(routes_module, "approve_event_request", lambda *a: called.append(a))

    response = client.post("/events/event-1/approve", headers=_auth(signing_key))

    assert response.status_code == 403
    assert called == []


def test_organiser_cannot_approve_own_event(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_organizer"])
    event = FakeEvent(id="event-1", organizer_id="user-1", status="under_review")
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: event)

    response = client.post("/events/event-1/approve", headers=_auth(signing_key))

    assert response.status_code == 404


# -- POST /events/<id>/reject ---------------------------------------------


def test_reject_route_passes_reason_to_service(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    event = FakeEvent(id="event-1", coordinator_id="user-1", status="under_review")
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: event)
    calls = []

    def fake_reject(event_id, loaded, rejected_by, reason):
        calls.append((event_id, rejected_by, reason))
        return {"id": event_id, "status": "rejected"}

    monkeypatch.setattr(routes_module, "reject_event_request", fake_reject)

    response = client.post(
        "/events/event-1/reject", headers=_auth(signing_key), json={"reason": "No suitable dates"}
    )

    assert response.status_code == 200
    assert calls == [("event-1", "user-1", "No suitable dates")]


def test_reject_route_404_for_coordinator_not_assigned(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    event = FakeEvent(id="event-1", coordinator_id="someone-else", status="under_review")
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: event)

    response = client.post("/events/event-1/reject", headers=_auth(signing_key), json={"reason": "x"})

    assert response.status_code == 404


# -- GET /events/coordinators ---------------------------------------------


def test_coordinators_route_lists_for_coordinator(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_coordinator"])
    coordinators = [{"id": "c1", "name": "Alice", "email": "a@example.com"}]
    monkeypatch.setattr(routes_module, "list_coordinators", lambda: coordinators)

    response = client.get("/events/coordinators", headers=_auth(signing_key))

    assert response.status_code == 200
    assert response.get_json() == coordinators


def test_coordinators_route_forbidden_for_organiser(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_organizer"])

    response = client.get("/events/coordinators", headers=_auth(signing_key))

    assert response.status_code == 403


def test_coordinator_list_rule_allows_only_coordinators():
    assert can(make_user(["event_coordinator"]), actions.COORDINATOR_LIST) is True
    for role in ["event_organizer", "venue_staff", "technical_support_staff", "attendee"]:
        assert can(make_user([role]), actions.COORDINATOR_LIST) is False


# -- service: approve_event_request / reject_event_request ----------------


class _FakeQuery:
    def __init__(self, db, table):
        self.db, self.table, self.filters, self.op = db, table, [], None

    def update(self, values):
        self.op = ("update", values)
        return self

    def insert(self, values):
        self.op = ("insert", values)
        return self

    def eq(self, column, value):
        self.filters.append((column, value))
        return self

    def select(self, *_):
        return self

    def execute(self):
        kind, values = self.op
        if kind == "insert":
            self.db.inserts.append((self.table, values))
            return SimpleNamespace(data=[values])
        matched = [row for row in self.db.events if all(row.get(c) == v for c, v in self.filters)]
        for row in matched:
            row.update(values)
        return SimpleNamespace(data=matched)


class _FakeSupabase:
    def __init__(self, events):
        self.events, self.inserts = events, []

    def table(self, name):
        return _FakeQuery(self, name)


@pytest.fixture
def fake_db(monkeypatch):
    db = _FakeSupabase([{"id": "event-1", "status": "under_review", "coordinator_id": "coord-1"}])
    # approve/reject now write through app.events.transitions, so the fake
    # stands in for transition()'s data layer, not event_service's client.
    monkeypatch.setattr(transitions_module, "supabase", db)
    return db


def _loaded(status="under_review"):
    return SimpleNamespace(id="event-1", status=status, coordinator_id="coord-1")


def test_approve_sets_status_and_logs_who_approved(fake_db):
    result = service_module.approve_event_request("event-1", _loaded(), "coord-1")

    assert result["status"] == "approved"
    assert fake_db.inserts == [
        (
            "event_status_log",
            {
                "event_id": "event-1",
                "from_status": "under_review",
                "to_status": "approved",
                "changed_by": "coord-1",
                "reason": None,
            },
        )
    ]


def test_reject_sets_status_and_logs_trimmed_reason(fake_db):
    result = service_module.reject_event_request("event-1", _loaded(), "coord-1", "  Dates unavailable  ")

    assert result["status"] == "rejected"
    assert fake_db.inserts[0][1]["reason"] == "Dates unavailable"
    assert fake_db.inserts[0][1]["to_status"] == "rejected"


@pytest.mark.parametrize("reason", [None, "", "   ", 42])
def test_reject_requires_a_reason(fake_db, reason):
    with pytest.raises(ValidationError):
        service_module.reject_event_request("event-1", _loaded(), "coord-1", reason)
    assert fake_db.events[0]["status"] == "under_review"
    assert fake_db.inserts == []


def test_second_decision_is_refused_once_no_longer_under_review(fake_db):
    service_module.approve_event_request("event-1", _loaded(), "coord-1")

    with pytest.raises(TransitionConflictError):
        service_module.reject_event_request("event-1", _loaded(), "coord-1", "changed my mind")
    assert fake_db.events[0]["status"] == "approved"
    assert len(fake_db.inserts) == 1


# -- service: a decision on a multi-session request covers every session --------


def _request_rows():
    base = {"shared_event_id": "group-1", "organizer_id": "org-1", "coordinator_id": "coord-1"}
    return [
        {**base, "id": "s1", "status": "under_review"},
        {**base, "id": "s2", "status": "under_review"},
        {**base, "id": "s3", "status": "approved"},  # already decided: left alone
        {**base, "id": "s4", "status": "under_review", "coordinator_id": "coord-2"},  # not this coordinator's
        {**base, "id": "other", "status": "under_review", "shared_event_id": "group-2"},  # another request
    ]


@pytest.fixture
def request_db(monkeypatch):
    db = FakeSupabase(_request_rows())
    monkeypatch.setattr(service_module, "supabase", db)
    monkeypatch.setattr(transitions_module, "supabase", db)
    return db


def _loaded_session(event_id="s1"):
    return SimpleNamespace(
        id=event_id, status="under_review", coordinator_id="coord-1",
        organizer_id="org-1", shared_event_id="group-1",
    )


def test_reject_rejects_every_under_review_session_of_the_request(request_db):
    result = service_module.reject_event_request("s1", _loaded_session(), "coord-1", " Venue clash ")

    assert result["id"] == "s1"
    statuses = {row["id"]: row["status"] for row in request_db.rows}
    assert statuses == {
        "s1": "rejected", "s2": "rejected", "s3": "approved", "s4": "under_review", "other": "under_review",
    }
    logs = request_db.tables["event_status_log"]
    assert sorted(entry["event_id"] for entry in logs) == ["s1", "s2"]
    assert all(entry["reason"] == "Venue clash" and entry["changed_by"] == "coord-1" for entry in logs)


def test_approve_approves_every_under_review_session_of_the_request(request_db):
    result = service_module.approve_event_request("s1", _loaded_session(), "coord-1")

    assert result["id"] == "s1"
    statuses = {row["id"]: row["status"] for row in request_db.rows}
    assert statuses == {
        "s1": "approved", "s2": "approved", "s3": "approved", "s4": "under_review", "other": "under_review",
    }
    logs = request_db.tables["event_status_log"]
    assert sorted(entry["event_id"] for entry in logs) == ["s1", "s2"]
    assert all(entry["to_status"] == "approved" and entry["changed_by"] == "coord-1" for entry in logs)


def test_reject_is_refused_without_a_reason_before_any_session_moves(request_db):
    with pytest.raises(ValidationError):
        service_module.reject_event_request("s1", _loaded_session(), "coord-1", "   ")
    assert request_db.get("s1")["status"] == request_db.get("s2")["status"] == "under_review"


def test_reject_lost_race_on_the_opened_session_touches_no_sibling(request_db):
    request_db.get("s1")["status"] = "approved"  # decided in another tab first

    with pytest.raises(TransitionConflictError):
        service_module.reject_event_request("s1", _loaded_session(), "coord-1", "Venue clash")
    assert request_db.get("s2")["status"] == "under_review"
    assert request_db.tables.get("event_status_log", []) == []


# -- service: list_event_requests (organiser's list / coordinator's queue) --------
# Unit level, with an in-memory client; test_event_list_integration.py checks
# the same scoping against a real database.

_LIST_ROWS = [
    {"id": "org-old", "organizer_id": "org-1", "coordinator_id": None, "status": "draft",
     "created_at": "2026-10-01T00:00:00+00:00"},
    {"id": "org-new", "organizer_id": "org-1", "coordinator_id": "coord-1", "status": "under_review",
     "created_at": "2026-10-04T00:00:00+00:00"},
    {"id": "queue", "organizer_id": "org-2", "coordinator_id": "coord-1", "status": "approved",
     "created_at": "2026-10-03T00:00:00+00:00"},
    {"id": "unrelated", "organizer_id": "org-2", "coordinator_id": "coord-2", "status": "under_review",
     "created_at": "2026-10-05T00:00:00+00:00"},
]


@pytest.fixture
def list_db(monkeypatch):
    db = FakeSupabase(_LIST_ROWS)
    monkeypatch.setattr(service_module, "supabase", db)
    return db


@pytest.mark.parametrize(
    ("roles", "user_id", "expected"),
    [
        (["event_organizer"], "org-1", ["org-new", "org-old"]),
        (["event_coordinator"], "coord-1", ["org-new", "queue"]),
    ],
)
def test_list_shows_only_the_callers_own_events_newest_first(list_db, roles, user_id, expected):
    """An organiser sees the requests they created; a coordinator sees the
    ones assigned to them (their review queue). Newest first."""
    events = service_module.list_event_requests(make_user(roles, user_id=user_id))

    assert [event["id"] for event in events] == expected


def test_list_for_a_user_with_both_roles_is_the_union(list_db):
    """Someone who is both an organiser and a coordinator sees what they
    organised AND what they're assigned, not just one of the two."""
    list_db.rows.append(
        {"id": "both-assigned", "organizer_id": "org-9", "coordinator_id": "org-1", "status": "under_review",
         "created_at": "2026-10-02T00:00:00+00:00"}
    )

    events = service_module.list_event_requests(make_user(["event_organizer", "event_coordinator"], user_id="org-1"))

    assert [event["id"] for event in events] == ["org-new", "both-assigned", "org-old"]


def test_list_status_filter_narrows_within_the_callers_events(list_db):
    """The status filter applies on top of the role scoping -- it never
    widens what the caller can see."""
    events = service_module.list_event_requests(make_user(["event_coordinator"], user_id="coord-1"), "approved")

    assert [event["id"] for event in events] == ["queue"]


def test_list_rejects_an_unknown_status_filter(list_db):
    with pytest.raises(ValidationError, match="status must be one of"):
        service_module.list_event_requests(make_user(["event_organizer"], user_id="org-1"), "archived")


def test_list_for_a_user_without_a_listing_role_is_empty_and_never_queries(list_db):
    """Defence in depth behind rule_event_list: a caller with neither role
    gets an empty list, and the database is never queried."""
    assert service_module.list_event_requests(make_user(["attendee"], user_id="someone")) == []
    assert list_db.calls == []


# -- service: rejection reason shown to the organiser ----------------------------
# reject_event_request records the reason in event_status_log; the organiser
# sees it on their event page through list_event_sessions.


@pytest.fixture
def rejection_db(monkeypatch):
    db = FakeSupabase()
    monkeypatch.setattr(service_module, "supabase", db)
    return db


def _session(event_id, status, shared_event_id="group-1"):
    return {
        "id": event_id,
        "shared_event_id": shared_event_id,
        "organizer_id": "user-1",
        "coordinator_id": "coord-1",
        "status": status,
        "name": "Community Conference",
    }


def _log_entry(event_id, reason, changed_at, to_status="rejected", by="Alice Tan"):
    return {
        "event_id": event_id,
        "to_status": to_status,
        "reason": reason,
        "changed_at": changed_at,
        "profiles": {"name": by},
    }


def test_rejected_sessions_carry_the_coordinators_latest_rejection(rejection_db):
    """A rejected session comes back with the coordinator's reason, who
    rejected it and when -- the MOST RECENT rejection, since a session can
    be rejected, fixed, resubmitted and rejected again. A session that
    isn't rejected gets no rejection, even if it was rejected in the past."""
    rejection_db.rows = [_session("r", "rejected"), _session("ok", "under_review")]
    rejection_db.tables["event_status_log"] = [
        _log_entry("r", "Venue too small.", "2026-10-01T09:00:00+00:00"),
        _log_entry("r", "Please add an accessible entrance.", "2026-10-03T09:00:00+00:00"),
        _log_entry("r", None, "2026-10-02T09:00:00+00:00", to_status="under_review", by="Organiser"),
        _log_entry("ok", "Old reason, since fixed.", "2026-10-01T09:00:00+00:00"),
    ]

    group = service_module.list_event_sessions(
        SimpleNamespace(**rejection_db.get("r")), make_user(["event_organizer"])
    )

    sessions = {s["id"]: s for s in group["sessions"]}
    assert sessions["r"]["rejection"] == {
        "reason": "Please add an accessible entrance.",
        "rejected_at": "2026-10-03T09:00:00+00:00",
        "rejected_by": "Alice Tan",
    }
    assert "rejection" not in sessions["ok"]


def test_no_rejection_lookup_when_nothing_is_rejected(rejection_db):
    """Requests with no rejected session don't query the status log at all."""
    rejection_db.rows = [_session("a", "under_review")]

    service_module.list_event_sessions(SimpleNamespace(**rejection_db.get("a")), make_user(["event_organizer"]))

    assert {call["table"] for call in rejection_db.calls} == {"events"}


def test_legacy_rejected_request_is_a_group_of_one_with_its_reason(rejection_db):
    """A request created before sessions existed (no shared_event_id) is
    listed as a single session -- itself -- and still shows the
    coordinator's rejection reason."""
    legacy = _session("legacy", "rejected", shared_event_id=None)
    rejection_db.tables["event_status_log"] = [_log_entry("legacy", "Dates clash.", "2026-10-01T09:00:00+00:00")]

    group = service_module.list_event_sessions(SimpleNamespace(**legacy), make_user(["event_organizer"]))

    assert [s["id"] for s in group["sessions"]] == ["legacy"]
    assert group["sessions"][0]["rejection"]["reason"] == "Dates clash."
    assert group["name"] == "Community Conference"
