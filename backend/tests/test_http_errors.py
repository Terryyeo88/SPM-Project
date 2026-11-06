"""
Tests for the JSON error handlers in app/__init__.py (IS-73).

Unit-level: no real Supabase, no network. Flask matches the URL before the
auth hook runs, and the hook skips a request that matched no route, so the
404 and 405 below never verify a token or load a profile.
"""

from __future__ import annotations

import logging

import pytest

import app.auth.context as context_module
import app.events.routes as routes_module
from tests.factories import FakeEvent

SECRET_DETAIL = "db-password-hunter2"


def _mock_profile(monkeypatch, roles):
    monkeypatch.setattr(
        context_module,
        "_load_profile_with_roles",
        lambda user_id: ("Test User", "test@example.com", frozenset(roles)),
    )
    monkeypatch.setattr(context_module, "_get_last_active", lambda session_id: None)
    monkeypatch.setattr(context_module, "_touch_session_activity", lambda *a, **k: None)


def _auth(signing_key):
    return {"Authorization": f"Bearer {signing_key.make_token()}"}


@pytest.fixture
def app_log(caplog):
    caplog.set_level(logging.DEBUG, logger="app")
    return caplog


def _no_crash_logged(caplog):
    return all(record.levelno < logging.WARNING and not record.exc_info for record in caplog.records)


# -- unknown path -> 404 ------------------------------------------------------


def test_unknown_path_is_a_404_in_the_envelope(client, signing_key, app_log):
    response = client.get("/no-such-route", headers=_auth(signing_key))

    assert response.status_code == 404
    assert response.get_json() == {"error": {"code": "not_found", "message": "Not Found"}}
    assert _no_crash_logged(app_log)


def test_anonymous_caller_gets_the_same_404_as_an_authenticated_one(client, signing_key):
    """The auth hook skips a request that matched no route, so an unknown URL
    is a 404 whoever asks. Pinned so that changing this is a decision, not an
    accident: see docs/open-questions.md, IS-73."""
    anonymous = client.get("/no-such-route")
    authenticated = client.get("/no-such-route", headers=_auth(signing_key))

    assert anonymous.status_code == 404
    assert anonymous.get_json() == authenticated.get_json()


def test_known_protected_route_still_401s_for_an_anonymous_caller(client):
    response = client.get("/me")

    assert response.status_code == 401
    assert response.get_json()["error"]["code"] == "auth_missing_token"


# -- known path, wrong method -> 405 -----------------------------------------


def test_wrong_method_is_a_405_in_the_envelope(client, signing_key, app_log):
    response = client.delete("/me", headers=_auth(signing_key))

    assert response.status_code == 405
    assert response.get_json() == {
        "error": {"code": "method_not_allowed", "message": "Method Not Allowed"}
    }
    assert "GET" in response.headers["Allow"]
    assert _no_crash_logged(app_log)


# -- genuine crashes -> 500, logged, nothing leaked ---------------------------


def _assert_generic_500(response):
    assert response.status_code == 500
    assert response.get_json() == {"error": {"code": "internal_error", "message": "Internal server error"}}
    body = response.get_data(as_text=True)
    assert SECRET_DETAIL not in body
    assert "Traceback" not in body
    assert "RuntimeError" not in body
    assert "TypeError" not in body


def test_exception_in_a_view_is_a_generic_500_with_full_detail_logged(app, client, app_log):
    @app.route("/_test/boom")
    @context_module.public
    def boom():
        raise RuntimeError(SECRET_DETAIL)

    _assert_generic_500(client.get("/_test/boom"))

    crash = next(record for record in app_log.records if record.levelno == logging.ERROR)
    assert crash.exc_info[0] is RuntimeError
    assert SECRET_DETAIL in str(crash.exc_info[1])


def test_crash_outside_the_view_is_a_generic_500_not_an_http_error(app, client, app_log):
    """A view returning an invalid value fails after dispatch. Flask wraps that
    in InternalServerError, an HTTPException, so without its own registration
    it would reach the client-error handler and come out with a different code."""
    app.config["PROPAGATE_EXCEPTIONS"] = False

    @app.route("/_test/returns-nothing")
    @context_module.public
    def returns_nothing():
        return None

    _assert_generic_500(client.get("/_test/returns-nothing"))

    assert any(record.levelno == logging.ERROR and record.exc_info for record in app_log.records)


def test_http_exception_description_is_never_sent_to_the_caller(app, client):
    from flask import abort

    @app.route("/_test/abort")
    @context_module.public
    def aborts():
        abort(409, description=SECRET_DETAIL)

    response = client.get("/_test/abort")

    assert response.status_code == 409
    assert response.get_json() == {"error": {"code": "conflict", "message": "Conflict"}}


# -- AppError path is untouched ----------------------------------------------


def test_authz_404_still_comes_from_the_app_error_path(client, signing_key, monkeypatch):
    """A real route, a real policy decision. The message is what shows this
    came from AppError and not the routing 404, which has the same code."""
    _mock_profile(monkeypatch, ["event_coordinator"])
    event = FakeEvent(id="event-1", coordinator_id="someone-else")
    monkeypatch.setattr(routes_module, "load_event", lambda event_id: event)

    response = client.post(
        "/events/event-1/reassign-coordinator",
        headers=_auth(signing_key),
        json={"new_coordinator_id": "new-coord"},
    )

    assert response.status_code == 404
    error = response.get_json()["error"]
    assert error["code"] == "not_found"
    assert error["message"] != "Not Found"
