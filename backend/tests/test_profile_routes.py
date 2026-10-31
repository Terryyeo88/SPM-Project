"""
HTTP routes for IS-68: GET /me's contact fields and PATCH /me/profile.

The routes run against the in-memory fake (profile_service's supabase is
swapped out), so these prove the wiring end to end: the profile written
and read is always the TOKEN's user, never one named by the request.
Service rules are test_profile_service.py's job.
"""

from __future__ import annotations

import pytest

import app.auth.context as context_module
import app.me.profile_service as service
from tests.fake_supabase import FakeSupabase

ME = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"

DEFAULTS = {"phone": None, "organisation": None, "notify_email": True, "notify_sms": False}
OTHERS_CONTACT = {"phone": "+6580000000", "organisation": "Other Org", "notify_email": False, "notify_sms": True}


def _mock_profile(monkeypatch, roles=("attendee",)):
    monkeypatch.setattr(
        context_module,
        "_load_profile_with_roles",
        lambda user_id: ("Ethan Koh", "ethan@example.com", frozenset(roles)),
    )
    monkeypatch.setattr(context_module, "_get_last_active", lambda session_id: None)
    monkeypatch.setattr(context_module, "_touch_session_activity", lambda *a, **k: None)


def _auth(signing_key, user_id=ME):
    return {"Authorization": f"Bearer {signing_key.make_token(sub=user_id)}"}


@pytest.fixture
def fake(monkeypatch):
    db = FakeSupabase()
    db.tables["profiles"] = [
        {"id": ME, "name": "Ethan Koh", "email": "ethan@example.com", **DEFAULTS},
        {"id": OTHER, "name": "Other Person", "email": "other@example.com", **OTHERS_CONTACT},
    ]
    monkeypatch.setattr(service, "supabase", db)
    return db


def _contact(fake, user_id):
    row = next(row for row in fake.tables["profiles"] if row["id"] == user_id)
    return {field: row[field] for field in service.CONTACT_FIELDS}


# -- GET /me -----------------------------------------------------------------


def test_get_me_returns_the_defaults_for_a_never_edited_profile(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch)

    response = client.get("/me", headers=_auth(signing_key))

    assert response.status_code == 200
    assert response.get_json() == {
        "id": ME, "email": "ethan@example.com", "name": "Ethan Koh", "roles": ["attendee"], **DEFAULTS,
    }


def test_get_me_reads_back_what_was_saved(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch)
    client.patch(
        "/me/profile", json={"phone": "+65 9123 4567", "notify_sms": True}, headers=_auth(signing_key)
    )

    body = client.get("/me", headers=_auth(signing_key)).get_json()

    assert {field: body[field] for field in service.CONTACT_FIELDS} == {
        **DEFAULTS, "phone": "+6591234567", "notify_sms": True,
    }


def test_get_me_never_shows_another_users_contact_details(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch)

    body = client.get("/me", headers=_auth(signing_key)).get_json()

    assert {field: body[field] for field in service.CONTACT_FIELDS} == DEFAULTS
    other = client.get("/me", headers=_auth(signing_key, OTHER)).get_json()
    assert {field: other[field] for field in service.CONTACT_FIELDS} == OTHERS_CONTACT


# -- PATCH /me/profile -------------------------------------------------------------


@pytest.mark.parametrize(
    "roles",
    [["attendee"], ["event_organizer"], ["event_coordinator"], ["event_coordinator_lead"], ["venue_staff"],
     ["technical_support_staff"], ["safety_officer"], []],
)
def test_every_role_saves_phone_and_preferences_to_their_own_profile(client, signing_key, monkeypatch, fake, roles):
    _mock_profile(monkeypatch, roles)
    payload = {"phone": "+65 9123 4567", "notify_email": False, "notify_sms": True}

    response = client.patch("/me/profile", json=payload, headers=_auth(signing_key))

    expected = {"phone": "+6591234567", "organisation": None, "notify_email": False, "notify_sms": True}
    assert (response.status_code, response.get_json()) == (200, expected)
    assert _contact(fake, ME) == expected
    assert _contact(fake, OTHER) == OTHERS_CONTACT


def test_saving_with_the_phone_blank(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch)

    response = client.patch("/me/profile", json={"phone": "", "notify_email": True}, headers=_auth(signing_key))

    assert (response.status_code, response.get_json()) == (200, DEFAULTS)


@pytest.mark.parametrize(
    "payload",
    [
        {"id": OTHER, "phone": "+65 9123 4567"},
        {"id": ME, "phone": "+65 9123 4567"},
        {"email": "other@example.com"},
        {"organisation": "Hijacked"},
        {"id": OTHER, "email": "other@example.com", "organisation": "Hijacked"},
    ],
)
def test_a_body_naming_a_read_only_field_is_a_400_and_writes_nothing(client, signing_key, monkeypatch, fake, payload):
    _mock_profile(monkeypatch)

    response = client.patch("/me/profile", json=payload, headers=_auth(signing_key))

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "profile_field_not_editable"
    assert _contact(fake, OTHER) == OTHERS_CONTACT
    assert _contact(fake, ME) == DEFAULTS


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"notify_email": False, "notify_sms": False}, service.AT_LEAST_ONE_MESSAGE),
        ({"notify_sms": True}, service.SMS_NEEDS_PHONE_MESSAGE),
        ({"phone": "91234567"}, service.PHONE_FORMAT_MESSAGE),
    ],
)
def test_rule_breaking_updates_are_400s_with_a_clear_message(client, signing_key, monkeypatch, fake, payload, message):
    _mock_profile(monkeypatch)

    response = client.patch("/me/profile", json=payload, headers=_auth(signing_key))

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "validation_error"
    assert response.get_json()["error"]["message"] == message
    assert _contact(fake, ME) == DEFAULTS


@pytest.mark.parametrize("method", ["get", "patch", "put", "post", "delete"])
def test_there_is_no_route_that_takes_another_users_id(client, signing_key, monkeypatch, fake, method):
    """No id in the URL: another user's profile is not reachable at all.
    Asserted as "refused, nothing written" rather than a specific status:
    app-wide, an unmatched URL is currently a 500, not a 404, because the
    catch-all error handler in app/__init__.py also catches werkzeug's
    NotFound (pre-existing; logged in docs/open-questions.md, IS-68)."""
    _mock_profile(monkeypatch)

    response = getattr(client, method)(
        f"/me/profile/{OTHER}", json={"phone": "+65 9123 4567"}, headers=_auth(signing_key)
    )

    assert response.status_code >= 400
    assert _contact(fake, OTHER) == OTHERS_CONTACT
    assert not [call for call in fake.calls if call["op"] == "update"]


def test_two_users_each_write_only_their_own(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch)

    client.patch("/me/profile", json={"phone": "+65 9123 4567"}, headers=_auth(signing_key, ME))
    client.patch("/me/profile", json={"notify_email": True}, headers=_auth(signing_key, OTHER))

    assert _contact(fake, ME) == {**DEFAULTS, "phone": "+6591234567"}
    assert _contact(fake, OTHER) == {**OTHERS_CONTACT, "notify_email": True}


def test_a_body_that_is_not_json_is_a_400(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch)

    response = client.patch("/me/profile", data="phone=9123", headers=_auth(signing_key))

    assert response.status_code == 400
    assert _contact(fake, ME) == DEFAULTS


def test_patch_without_a_token_is_a_401(client, fake):
    response = client.patch("/me/profile", json={"phone": "+65 9123 4567"})

    assert response.status_code == 401
    assert _contact(fake, ME) == DEFAULTS
