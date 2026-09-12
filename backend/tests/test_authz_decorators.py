"""
Tests for app.authz.decorators.require -- the Flask-facing interface
other developers use. Gap found during the Phase 5 criterion audit: no
test had ever exercised this decorator at all, direct or otherwise.
Everything here drives it through a real Flask route (the `app`/
`client`/`signing_key` fixtures), the same way a real caller would,
rather than calling its inner function directly.
"""

from __future__ import annotations

import app.auth.context as context_module
from app.authz.decorators import require
from app.shared.errors import NotFoundError
from tests.factories import FakeEvent


def _mock_profile(monkeypatch, roles):
    monkeypatch.setattr(
        context_module,
        "_load_profile_with_roles",
        lambda user_id: ("Test User", "test@example.com", frozenset(roles)),
    )
    monkeypatch.setattr(context_module, "_get_last_active", lambda session_id: None)
    monkeypatch.setattr(context_module, "_touch_session_activity", lambda *a, **k: None)


def test_require_with_loader_authorises_and_passes_resource_to_view(app, client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_organizer"])
    event = FakeEvent(organizer_id="user-1", status="draft")

    @app.route("/_test/edit-event/<event_id>")
    @require("event.edit", loader=lambda event_id: event)
    def edit_event(resource, event_id):
        return {"received_id": resource.id, "url_event_id": event_id}

    token = signing_key.make_token(sub="user-1")
    response = client.get("/_test/edit-event/event-1", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.get_json() == {"received_id": "event-1", "url_event_id": "event-1"}


def test_require_with_loader_denies_when_policy_says_no(app, client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_organizer"])
    event = FakeEvent(organizer_id="someone-else", status="draft")

    @app.route("/_test/edit-other-event")
    @require("event.edit", loader=lambda: event)
    def edit_other_event(resource):
        return {"should": "not reach here"}

    token = signing_key.make_token(sub="user-1")
    response = client.get("/_test/edit-other-event", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 404  # no relationship -> hidden, per the 403/404 ruling
    assert response.get_json()["error"]["code"] == "not_found"


def test_require_loaders_own_not_found_propagates_unchanged(app, client, signing_key, monkeypatch):
    """A loader raising NotFoundError itself (resource genuinely doesn't
    exist) must produce the exact same 404 a failed, existence-sensitive
    authorisation would have -- the whole point documented in
    decorators.py's docstring."""
    _mock_profile(monkeypatch, ["event_organizer"])

    def loader(event_id):
        raise NotFoundError("No such event.")

    @app.route("/_test/missing-event/<event_id>")
    @require("event.edit", loader=loader)
    def get_missing_event(resource, event_id):
        return {"should": "not reach here"}

    token = signing_key.make_token(sub="user-1")
    response = client.get(
        "/_test/missing-event/does-not-exist", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 404
    assert response.get_json()["error"]["code"] == "not_found"


def test_require_without_loader_is_role_only(app, client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["event_organizer"])

    @app.route("/_test/create-event", methods=["POST"])
    @require("event.create")
    def create_event():
        return {"created": True}

    token = signing_key.make_token(sub="user-1")
    response = client.post("/_test/create-event", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.get_json() == {"created": True}


def test_require_without_loader_denies_wrong_role(app, client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["attendee"])

    @app.route("/_test/create-event-2", methods=["POST"])
    @require("event.create")
    def create_event_2():
        return {"should": "not reach here"}

    token = signing_key.make_token(sub="user-1")
    response = client.post("/_test/create-event-2", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 403
    assert response.get_json()["error"]["code"] == "not_authorised"


def test_require_rejects_unauthenticated_before_loader_runs(app, client):
    loader_calls = []

    @app.route("/_test/protected-with-loader/<event_id>")
    @require("event.edit", loader=lambda event_id: loader_calls.append(event_id))
    def protected_with_loader(resource, event_id):
        return {"should": "not reach here"}

    response = client.get("/_test/protected-with-loader/event-1")  # no token

    assert response.status_code == 401
    assert loader_calls == []  # loader must never run for an unauthenticated caller
