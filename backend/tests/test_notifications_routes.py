"""
HTTP routes for notifications (IS-69):

  GET  /notifications                GET /notifications/unread-count
  POST /notifications/<id>/read      POST /notifications/read-all

Routing + authz wiring only: the notification_service functions imported
into the route module are monkeypatched. Service behaviour is
test_notification_service.py's job.
"""

from __future__ import annotations

import pytest

import app.auth.context as context_module
import app.notifications.routes as routes
from app.shared.errors import NotFoundError


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


def _notification_for(recipient_id):
    return lambda notification_id: {"id": notification_id, "recipient_id": recipient_id}


@pytest.fixture
def calls(monkeypatch):
    seen = []

    def record(name, result):
        def fake(*args):
            seen.append((name, args))
            return result

        monkeypatch.setattr(routes, name, fake)

    record("list_notifications", [{"id": "n-1"}])
    record("unread_count", 3)
    record("mark_read", {"id": "n-1", "read_at": "now"})
    record("mark_all_read", 3)
    return seen


@pytest.mark.parametrize("roles", [["attendee"], ["safety_officer"], ["event_organizer"], []])
def test_list_returns_the_callers_notifications_and_unread_count(client, signing_key, monkeypatch, calls, roles):
    _mock_profile(monkeypatch, roles)

    response = client.get("/notifications?unread=true", headers=_auth(signing_key))

    assert response.status_code == 200
    assert response.get_json() == {"notifications": [{"id": "n-1"}], "unread_count": 3}
    assert calls == [("list_notifications", ("user-1", "true")), ("unread_count", ("user-1",))]


def test_unread_count(client, signing_key, monkeypatch, calls):
    _mock_profile(monkeypatch, ["venue_staff"])

    response = client.get("/notifications/unread-count", headers=_auth(signing_key))

    assert (response.status_code, response.get_json()) == (200, {"unread_count": 3})


def test_mark_read_own(client, signing_key, monkeypatch, calls):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(routes, "get_notification", _notification_for("user-1"))

    response = client.post("/notifications/n-1/read", headers=_auth(signing_key))

    assert response.status_code == 200
    assert response.get_json() == {"notification": {"id": "n-1", "read_at": "now"}, "unread_count": 3}
    assert ("mark_read", ("n-1", "user-1")) in calls


def test_mark_read_someone_elses_is_404_and_writes_nothing(client, signing_key, monkeypatch, calls):
    _mock_profile(monkeypatch, ["event_coordinator"])
    monkeypatch.setattr(routes, "get_notification", _notification_for("someone-else"))

    response = client.post("/notifications/n-1/read", headers=_auth(signing_key))

    assert response.status_code == 404
    assert calls == []


def test_mark_read_missing_is_404(client, signing_key, monkeypatch, calls):
    _mock_profile(monkeypatch, ["attendee"])

    def missing(notification_id):
        raise NotFoundError("Notification not found.")

    monkeypatch.setattr(routes, "get_notification", missing)

    assert client.post("/notifications/n-1/read", headers=_auth(signing_key)).status_code == 404


def test_mark_all_read(client, signing_key, monkeypatch, calls):
    _mock_profile(monkeypatch, ["technical_support_staff"])

    response = client.post("/notifications/read-all", headers=_auth(signing_key))

    assert (response.status_code, response.get_json()) == (200, {"marked_read": 3, "unread_count": 3})
    assert ("mark_all_read", ("user-1",)) in calls


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("get", "/notifications"),
        ("get", "/notifications/unread-count"),
        ("post", "/notifications/n-1/read"),
        ("post", "/notifications/read-all"),
    ],
)
def test_every_route_needs_a_login(client, calls, method, path):
    assert getattr(client, method)(path).status_code == 401
    assert calls == []
