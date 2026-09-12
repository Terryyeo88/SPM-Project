"""
Tests for GET /me (app/me/routes.py) -- the real shipped route, not a
throwaway test double. Gap found during the Phase 5 criterion audit: no
test had ever exercised this route directly even though every other
route-level behaviour (public vs protected, rejection codes) was
covered through a throwaway `/_test/whoami` route elsewhere.
"""

from __future__ import annotations

import app.auth.context as context_module


def _mock_profile(monkeypatch, name, email, roles):
    monkeypatch.setattr(
        context_module, "_load_profile_with_roles", lambda user_id: (name, email, frozenset(roles))
    )
    monkeypatch.setattr(context_module, "_get_last_active", lambda session_id: None)
    monkeypatch.setattr(context_module, "_touch_session_activity", lambda *a, **k: None)


def test_me_returns_id_email_name_roles_for_authenticated_user(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, "Alice Tan", "alice@example.com", ["event_coordinator"])
    token = signing_key.make_token(sub="user-abc", session_id="sess-1")

    response = client.get("/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    body = response.get_json()
    assert body == {
        "id": "user-abc",
        "email": "alice@example.com",
        "name": "Alice Tan",
        "roles": ["event_coordinator"],
    }


def test_me_works_for_any_role_no_policy_check(client, signing_key, monkeypatch):
    """GET /me needs no policy check beyond authentication -- an
    attendee, denied almost everything else in this system, still gets
    200 here."""
    _mock_profile(monkeypatch, "Some Attendee", "attendee@example.com", ["attendee"])
    token = signing_key.make_token()

    response = client.get("/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.get_json()["roles"] == ["attendee"]


def test_me_rejects_without_token(client):
    response = client.get("/me")
    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "auth_missing_token"
