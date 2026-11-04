"""Clarification thread on an event request (Event Review and Approval).

Unit-level: no real Supabase. The service's `supabase` is swapped for
FakeSupabase so the tests see exactly what is written to
event_clarifications; the notification hook is replaced with a recorder
(what each notification SAYS is tested at the bottom, against the
notification service itself).

Acceptance criteria, and the tests that prove each one (permissions --
who may post/reply/view, and in which status -- are in
test_authz_policy.py's event.clarification_* sections):
  coordinator enters free-text comments
      -> test_coordinator_message_is_recorded_against_the_request
  blank / over 1000 characters refused
      -> test_blank_message_refused, test_message_over_limit_refused, ...
  status stays under review
      -> test_posting_never_touches_the_event
  organizer notified / coordinator notified of the reply
      -> test_coordinator_message_notifies_*, test_organizer_reply_notifies_*
  organizer can answer (but not start a thread)
      -> test_organizer_can_reply_once_coordinator_has_asked,
         test_organizer_cannot_start_a_thread
  more than one round
      -> test_thread_can_go_back_and_forth
  who sent it and when, in order
      -> test_thread_lists_oldest_first_with_author_names
  one thread per request (shared by every session)
      -> test_sessions_of_one_request_share_a_thread, ..._other_request_excluded
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.auth.context as context_module
import app.events.clarification_service as service
import app.events.routes as routes_module
import app.notifications.notification_service as notification_service
from app.shared.errors import ValidationError
from tests.fake_supabase import FakeSupabase
from tests.test_notification_service import NotificationsFake

ORGANIZER = "org-1"
COORDINATOR = "coord-1"


def _event(**overrides) -> SimpleNamespace:
    fields = {
        "id": "session-1",
        "shared_event_id": "group-1",
        "organizer_id": ORGANIZER,
        "coordinator_id": COORDINATOR,
        "status": "under_review",
        "name": "Tech Symposium",
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


@pytest.fixture
def db(monkeypatch):
    fake = FakeSupabase()
    fake.tables["profiles"] = [
        {"id": ORGANIZER, "name": "Derek Ong"},
        {"id": COORDINATOR, "name": "Alice Tan"},
    ]
    fake.tables["event_clarifications"] = []
    monkeypatch.setattr(service, "supabase", fake)
    return fake


@pytest.fixture
def notified(monkeypatch):
    sent = []
    monkeypatch.setattr(
        service.notification_service,
        "clarification_posted",
        lambda event_id, author_role: sent.append((event_id, author_role)),
    )
    return sent


def _thread(db):
    return db.tables["event_clarifications"]


# -- posting ---------------------------------------------------------------------


def test_coordinator_message_is_recorded_against_the_request(db, notified):
    created = service.post_clarification(_event(), COORDINATOR, "coordinator", "  Is the date flexible?  ")

    [row] = _thread(db)
    assert row["shared_event_id"] == "group-1"
    assert row["event_id"] == "session-1"
    assert row["author_id"] == COORDINATOR
    assert row["author_role"] == "coordinator"
    assert row["message"] == "Is the date flexible?"  # trimmed
    assert created["author_name"] == "Alice Tan"


@pytest.mark.parametrize("message", ["", "   ", "\n\t", None])
def test_blank_message_refused(db, notified, message):
    with pytest.raises(ValidationError, match="Enter a message"):
        service.post_clarification(_event(), COORDINATOR, "coordinator", message)
    assert _thread(db) == []
    assert notified == []


def test_message_at_limit_accepted(db, notified):
    service.post_clarification(_event(), COORDINATOR, "coordinator", "x" * 1000)
    assert len(_thread(db)[0]["message"]) == 1000


def test_message_over_limit_refused(db, notified):
    with pytest.raises(ValidationError, match="1000 characters"):
        service.post_clarification(_event(), COORDINATOR, "coordinator", "x" * 1001)
    assert _thread(db) == []


def test_limit_counts_the_trimmed_message(db, notified):
    """Surrounding whitespace isn't stored, so it doesn't count."""
    service.post_clarification(_event(), COORDINATOR, "coordinator", "  " + "x" * 1000 + "  ")
    assert len(_thread(db)[0]["message"]) == 1000


def test_non_text_message_refused(db, notified):
    with pytest.raises(ValidationError, match="must be text"):
        service.post_clarification(_event(), COORDINATOR, "coordinator", 42)


def test_unknown_author_role_is_a_programming_error(db, notified):
    with pytest.raises(ValueError):
        service.post_clarification(_event(), COORDINATOR, "lead", "Hello")


def test_posting_never_touches_the_event(db, notified):
    """AC: status stays "under review" -- the service writes only the message."""
    service.post_clarification(_event(), COORDINATOR, "coordinator", "Is the date flexible?")
    service.post_clarification(_event(), ORGANIZER, "organizer", "Yes, any weekday works.")
    writes = [call for call in db.calls if call["op"] != "select"]
    assert {call["table"] for call in writes} == {"event_clarifications"}


# -- the organizer only answers ------------------------------------------------


def test_organizer_cannot_start_a_thread(db, notified):
    with pytest.raises(ValidationError, match="hasn't sent a clarification request yet"):
        service.post_clarification(_event(), ORGANIZER, "organizer", "Hello?")
    assert _thread(db) == []
    assert notified == []


def test_organizer_can_reply_once_coordinator_has_asked(db, notified):
    service.post_clarification(_event(), COORDINATOR, "coordinator", "Is the date flexible?")
    created = service.post_clarification(_event(), ORGANIZER, "organizer", "Yes, any weekday works.")

    assert created["author_role"] == "organizer"
    assert created["author_name"] == "Derek Ong"
    assert len(_thread(db)) == 2


def test_coordinator_question_on_another_request_doesnt_open_this_one(db, notified):
    service.post_clarification(_event(id="other-1", shared_event_id="group-2"), COORDINATOR, "coordinator", "Hi")
    with pytest.raises(ValidationError):
        service.post_clarification(_event(), ORGANIZER, "organizer", "Hello?")


def test_thread_can_go_back_and_forth(db, notified):
    """AC: more than one message each way while under review."""
    service.post_clarification(_event(), COORDINATOR, "coordinator", "Is the date flexible?")
    service.post_clarification(_event(), ORGANIZER, "organizer", "Yes.")
    service.post_clarification(_event(), COORDINATOR, "coordinator", "Which weekdays?")
    service.post_clarification(_event(), ORGANIZER, "organizer", "Tuesday or Thursday.")
    assert [row["author_role"] for row in _thread(db)] == ["coordinator", "organizer", "coordinator", "organizer"]


# -- notifications are triggered ---------------------------------------------------


def test_coordinator_message_notifies_the_organizer_side(db, notified):
    service.post_clarification(_event(), COORDINATOR, "coordinator", "Is the date flexible?")
    assert notified == [("session-1", "coordinator")]


def test_organizer_reply_notifies_the_coordinator_side(db, notified):
    service.post_clarification(_event(), COORDINATOR, "coordinator", "Is the date flexible?")
    service.post_clarification(_event(), ORGANIZER, "organizer", "Yes.")
    assert notified[-1] == ("session-1", "organizer")


# -- listing -------------------------------------------------------------------------


def test_thread_lists_oldest_first_with_author_names(db):
    _thread(db).extend(
        [
            {"clarification_id": "c2", "shared_event_id": "group-1", "event_id": "session-1",
             "author_id": ORGANIZER, "author_role": "organizer", "message": "Yes.",
             "created_at": "2026-11-04T10:05:00+00:00"},
            {"clarification_id": "c1", "shared_event_id": "group-1", "event_id": "session-1",
             "author_id": COORDINATOR, "author_role": "coordinator", "message": "Flexible?",
             "created_at": "2026-11-04T10:00:00+00:00"},
        ]
    )
    thread = service.list_clarifications(_event())
    assert [row["clarification_id"] for row in thread] == ["c1", "c2"]
    assert [row["author_name"] for row in thread] == ["Alice Tan", "Derek Ong"]


def test_sessions_of_one_request_share_a_thread(db, notified):
    """A message sent from session 2's page shows on session 1's."""
    service.post_clarification(_event(id="session-2"), COORDINATOR, "coordinator", "About session 2...")
    [row] = service.list_clarifications(_event(id="session-1"))
    assert row["event_id"] == "session-2"


def test_thread_of_other_request_excluded(db, notified):
    service.post_clarification(_event(id="other-1", shared_event_id="group-2"), COORDINATOR, "coordinator", "Hi")
    assert service.list_clarifications(_event()) == []


def test_legacy_event_without_shared_id_is_its_own_thread(db, notified):
    legacy = _event(id="legacy-1", shared_event_id=None)
    service.post_clarification(legacy, COORDINATOR, "coordinator", "Hi")
    assert _thread(db)[0]["shared_event_id"] == "legacy-1"
    assert len(service.list_clarifications(legacy)) == 1


def test_empty_thread(db):
    assert service.list_clarifications(_event()) == []


# -- what the notifications say (notification_service.clarification_posted) ------------


@pytest.fixture
def notifications_db(monkeypatch):
    fake = NotificationsFake(
        rows=[
            {
                "id": "session-1",
                "shared_event_id": "group-1",
                "name": "Tech Symposium",
                "preferred_start_date": "2026-11-12",
                "preferred_start_time": "14:00:00",
                "organizer_id": ORGANIZER,
                "coordinator_id": COORDINATOR,
            }
        ]
    )
    monkeypatch.setattr(notification_service, "supabase", fake)
    return fake


def test_clarification_request_notification_goes_to_the_organizer(notifications_db):
    notification_service.clarification_posted("session-1", "coordinator")
    [row] = notifications_db.notifications
    assert row["recipient_id"] == ORGANIZER
    assert row["type"] == notification_service.CLARIFICATION_REQUESTED
    assert row["message"] == (
        'The Event Coordinator sent a clarification request about "Tech Symposium". Open it to reply.'
    )
    assert (row["entity_type"], row["entity_id"]) == ("event", "session-1")


def test_clarification_reply_notification_goes_to_the_coordinator(notifications_db):
    notification_service.clarification_posted("session-1", "organizer")
    [row] = notifications_db.notifications
    assert row["recipient_id"] == COORDINATOR
    assert row["type"] == notification_service.CLARIFICATION_REPLIED
    assert row["message"] == 'The Event Organizer replied to your clarification request about "Tech Symposium".'


def test_clarification_notification_for_missing_session_sends_nothing(notifications_db):
    notification_service.clarification_posted("no-such-session", "coordinator")
    assert notifications_db.notifications == []


# -- routes (through the API, with real JWTs and @require) ---------------------------


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


@pytest.fixture
def api_db(monkeypatch, db):
    """`db` (the service's fake) with the session in it, shared with the
    routes' event loader."""
    db.rows.append(
        {"id": "session-1", "shared_event_id": "group-1", "organizer_id": ORGANIZER,
         "coordinator_id": COORDINATOR, "status": "under_review", "name": "Tech Symposium"}
    )
    monkeypatch.setattr(routes_module, "supabase", db)
    return db


def test_route_coordinator_asks_and_organizer_answers(client, signing_key, monkeypatch, api_db, notified):
    _mock_profile(monkeypatch, ["event_coordinator"])
    asked = client.post(
        "/events/session-1/clarifications/request",
        headers=_auth(signing_key, COORDINATOR),
        json={"message": "Is the date flexible?"},
    )
    assert asked.status_code == 201
    assert asked.get_json()["author_role"] == "coordinator"

    _mock_profile(monkeypatch, ["event_organizer"])
    answered = client.post(
        "/events/session-1/clarifications/reply",
        headers=_auth(signing_key, ORGANIZER),
        json={"message": "Yes, any weekday."},
    )
    assert answered.status_code == 201
    assert answered.get_json()["author_role"] == "organizer"

    listed = client.get("/events/session-1/clarifications", headers=_auth(signing_key, ORGANIZER))
    assert listed.status_code == 200
    assert [row["message"] for row in listed.get_json()] == ["Is the date flexible?", "Yes, any weekday."]
    # Status untouched.
    assert api_db.get("session-1")["status"] == "under_review"


def test_route_organizer_reply_before_any_question_is_400(client, signing_key, monkeypatch, api_db, notified):
    _mock_profile(monkeypatch, ["event_organizer"])
    response = client.post(
        "/events/session-1/clarifications/reply",
        headers=_auth(signing_key, ORGANIZER),
        json={"message": "Hello?"},
    )
    assert response.status_code == 400
    assert _thread(api_db) == []


def test_route_organizer_cannot_post_as_coordinator(client, signing_key, monkeypatch, api_db, notified):
    """The side is decided by the route: the organizer calling the
    coordinator's route is refused, whatever the body says."""
    _mock_profile(monkeypatch, ["event_organizer"])
    response = client.post(
        "/events/session-1/clarifications/request",
        headers=_auth(signing_key, ORGANIZER),
        json={"message": "Pretending to be the coordinator", "author_role": "coordinator"},
    )
    assert response.status_code in (403, 404)
    assert _thread(api_db) == []


def test_route_coordinator_cannot_use_the_reply_route(client, signing_key, monkeypatch, api_db, notified):
    _mock_profile(monkeypatch, ["event_coordinator"])
    response = client.post(
        "/events/session-1/clarifications/reply",
        headers=_auth(signing_key, COORDINATOR),
        json={"message": "Hi"},
    )
    assert response.status_code == 403
    assert _thread(api_db) == []


def test_route_blank_message_is_400(client, signing_key, monkeypatch, api_db, notified):
    _mock_profile(monkeypatch, ["event_coordinator"])
    response = client.post(
        "/events/session-1/clarifications/request",
        headers=_auth(signing_key, COORDINATOR),
        json={"message": "   "},
    )
    assert response.status_code == 400


def test_route_no_new_messages_once_approved_but_thread_still_readable(
    client, signing_key, monkeypatch, api_db, notified
):
    service.post_clarification(_event(), COORDINATOR, "coordinator", "Is the date flexible?")
    api_db.get("session-1")["status"] = "approved"

    _mock_profile(monkeypatch, ["event_coordinator"])
    asked = client.post(
        "/events/session-1/clarifications/request",
        headers=_auth(signing_key, COORDINATOR),
        json={"message": "One more thing"},
    )
    assert asked.status_code == 403

    _mock_profile(monkeypatch, ["event_organizer"])
    answered = client.post(
        "/events/session-1/clarifications/reply",
        headers=_auth(signing_key, ORGANIZER),
        json={"message": "Late answer"},
    )
    assert answered.status_code == 403

    listed = client.get("/events/session-1/clarifications", headers=_auth(signing_key, ORGANIZER))
    assert listed.status_code == 200
    assert len(listed.get_json()) == 1


def test_route_stranger_gets_404(client, signing_key, monkeypatch, api_db, notified):
    _mock_profile(monkeypatch, ["event_organizer"])
    response = client.get("/events/session-1/clarifications", headers=_auth(signing_key, "org-2"))
    assert response.status_code == 404


def test_route_lead_cannot_read_the_thread(client, signing_key, monkeypatch, api_db, notified):
    _mock_profile(monkeypatch, ["event_coordinator_lead"])
    response = client.get("/events/session-1/clarifications", headers=_auth(signing_key, "lead-1"))
    assert response.status_code == 403
