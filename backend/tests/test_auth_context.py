"""
Tests for app.auth.context: the before_request hook, idle timeout,
debounce, default-protected routing, and CurrentUser assembly.

These are unit tests -- app.auth.context._get_last_active,
._touch_session_activity, and ._load_profile_with_roles are monkeypatched
in every test that needs them, so nothing here touches a real database.
Token signing and JWKS lookup come from the `signing_key` fixture in
conftest.py, which is likewise fully in-memory.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import app.auth.context as context_module


def _register_protected_route(app):
    @app.route("/_test/whoami")
    def whoami():
        user = context_module.current_user()
        return {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "roles": sorted(user.roles),
            "session_id": user.session_id,
        }


def test_valid_token_produces_expected_current_user(app, client, signing_key, monkeypatch):
    _register_protected_route(app)
    monkeypatch.setattr(
        context_module,
        "_load_profile_with_roles",
        lambda user_id: ("Alice Tan", "alice@example.com", frozenset({"event_coordinator"})),
    )
    monkeypatch.setattr(context_module, "_get_last_active", lambda session_id: None)
    monkeypatch.setattr(context_module, "_touch_session_activity", lambda *a, **k: None)

    token = signing_key.make_token(sub="user-abc", session_id="sess-xyz")
    response = client.get("/_test/whoami", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.get_json()
    assert body["id"] == "user-abc"
    assert body["email"] == "alice@example.com"
    assert body["name"] == "Alice Tan"
    assert body["roles"] == ["event_coordinator"]
    assert body["session_id"] == "sess-xyz"


def test_multi_role_user_gets_both_roles_in_frozenset(app, client, signing_key, monkeypatch):
    _register_protected_route(app)
    monkeypatch.setattr(
        context_module,
        "_load_profile_with_roles",
        lambda user_id: (
            "Chloe Wong",
            "chloe@example.com",
            frozenset({"event_coordinator", "venue_staff"}),
        ),
    )
    monkeypatch.setattr(context_module, "_get_last_active", lambda session_id: None)
    monkeypatch.setattr(context_module, "_touch_session_activity", lambda *a, **k: None)

    token = signing_key.make_token()
    response = client.get("/_test/whoami", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.get_json()["roles"] == ["event_coordinator", "venue_staff"]


def test_idle_session_rejected_with_auth_session_idle(app, client, signing_key, monkeypatch):
    _register_protected_route(app)
    monkeypatch.setenv("SESSION_IDLE_TIMEOUT_MINUTES", "30")

    long_ago = datetime.now(UTC) - timedelta(minutes=45)
    monkeypatch.setattr(context_module, "_get_last_active", lambda session_id: long_ago)

    touch_calls = []
    monkeypatch.setattr(
        context_module, "_touch_session_activity", lambda *a, **k: touch_calls.append(a)
    )

    profile_load_calls = []
    monkeypatch.setattr(
        context_module,
        "_load_profile_with_roles",
        lambda user_id: (profile_load_calls.append(user_id), ("x", "x@example.com", frozenset()))[1],
    )

    token = signing_key.make_token()
    response = client.get("/_test/whoami", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "auth_session_idle"
    assert touch_calls == []  # a rejected session must not refresh its own clock
    assert profile_load_calls == []  # never reached -- idle check happens before the profile load


def test_debounce_two_rapid_requests_produce_one_write(app, client, signing_key, monkeypatch):
    _register_protected_route(app)
    monkeypatch.setattr(
        context_module,
        "_load_profile_with_roles",
        lambda user_id: ("Alice Tan", "alice@example.com", frozenset({"event_coordinator"})),
    )

    state = {"last_active": None}
    write_calls = []

    def fake_get_last_active(session_id):
        return state["last_active"]

    def fake_touch(session_id, user_id, now):
        write_calls.append(now)
        state["last_active"] = now

    monkeypatch.setattr(context_module, "_get_last_active", fake_get_last_active)
    monkeypatch.setattr(context_module, "_touch_session_activity", fake_touch)

    token = signing_key.make_token()
    headers = {"Authorization": f"Bearer {token}"}

    first = client.get("/_test/whoami", headers=headers)
    second = client.get("/_test/whoami", headers=headers)

    assert first.status_code == 200
    assert second.status_code == 200
    # First request: no prior record, so it writes. Second, moments
    # later: within the debounce window of the write the first request
    # just made, so it's skipped -- one write total, not two.
    assert len(write_calls) == 1


def test_public_route_works_with_no_token(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


def test_protected_route_rejects_without_token(app, client):
    _register_protected_route(app)
    response = client.get("/_test/whoami")
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "auth_missing_token"


def test_current_user_raises_if_called_on_a_public_route(app, client):
    """current_user() must never return None -- if somehow called where
    the before_request hook didn't attach a user (a @public route that
    mistakenly calls it), it raises AuthenticationError rather than
    handing back None for the caller to forget to check."""

    @app.route("/_test/misused-public-route")
    @context_module.public
    def misused_public_route():
        context_module.current_user()  # should raise -- g.current_user was never set
        return {"should": "not reach here"}

    response = client.get("/_test/misused-public-route")
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "auth_missing_token"
