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

UNSET = {"phone": None, "organisation": None, "notify_email": None, "notify_sms": None}
OTHERS_CONTACT = {"phone": "+65 8000 0000", "organisation": "Other Org", "notify_email": False, "notify_sms": True}


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
        {"id": ME, "name": "Ethan Koh", "email": "ethan@example.com", **UNSET},
        {"id": OTHER, "name": "Other Person", "email": "other@example.com", **OTHERS_CONTACT},
    ]
    monkeypatch.setattr(service, "supabase", db)
    return db


def _contact(fake, user_id):
    row = next(row for row in fake.tables["profiles"] if row["id"] == user_id)
    return {field: row[field] for field in service.CONTACT_FIELDS}


# -- GET /me -----------------------------------------------------------------


def test_get_me_returns_the_four_fields_as_null_when_never_given(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch)

    response = client.get("/me", headers=_auth(signing_key))

    assert response.status_code == 200
    assert response.get_json() == {
        "id": ME, "email": "ethan@example.com", "name": "Ethan Koh", "roles": ["attendee"], **UNSET,
    }


def test_get_me_reads_back_what_was_saved(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch)
    saved = {"phone": "9123 4567", "organisation": "SMU", "notify_email": True, "notify_sms": False}
    client.patch("/me/profile", json=saved, headers=_auth(signing_key))

    body = client.get("/me", headers=_auth(signing_key)).get_json()

    assert {field: body[field] for field in service.CONTACT_FIELDS} == saved


def test_get_me_never_shows_another_users_contact_details(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch)

    body = client.get("/me", headers=_auth(signing_key)).get_json()

    assert {field: body[field] for field in service.CONTACT_FIELDS} == UNSET
    other = client.get("/me", headers=_auth(signing_key, OTHER)).get_json()
    assert {field: other[field] for field in service.CONTACT_FIELDS} == OTHERS_CONTACT


# -- PATCH /me/profile -------------------------------------------------------------


@pytest.mark.parametrize(
    "roles",
    [["attendee"], ["event_organizer"], ["event_coordinator"], ["event_coordinator_lead"], ["venue_staff"],
     ["technical_support_staff"], ["safety_officer"], []],
)
def test_every_role_saves_all_three_to_their_own_profile(client, signing_key, monkeypatch, fake, roles):
    _mock_profile(monkeypatch, roles)
    payload = {"phone": "+65 9123 4567", "organisation": "SMU", "notify_email": False, "notify_sms": True}

    response = client.patch("/me/profile", json=payload, headers=_auth(signing_key))

    assert (response.status_code, response.get_json()) == (200, payload)
    assert _contact(fake, ME) == payload
    assert _contact(fake, OTHER) == OTHERS_CONTACT


def test_saving_with_the_optional_ones_blank(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch)

    response = client.patch(
        "/me/profile",
        json={"phone": "", "organisation": "", "notify_email": None, "notify_sms": None},
        headers=_auth(signing_key),
    )

    assert (response.status_code, response.get_json()) == (200, UNSET)


@pytest.mark.parametrize(
    "payload",
    [
        {"id": OTHER, "phone": "9123 4567"},
        {"id": ME, "phone": "9123 4567"},
        {"email": "other@example.com"},
        {"id": OTHER, "email": "other@example.com", "organisation": "Hijacked"},
    ],
)
def test_a_body_naming_id_or_email_is_a_400_and_writes_nothing(client, signing_key, monkeypatch, fake, payload):
    _mock_profile(monkeypatch)

    response = client.patch("/me/profile", json=payload, headers=_auth(signing_key))

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "profile_field_not_editable"
    assert _contact(fake, OTHER) == OTHERS_CONTACT
    assert _contact(fake, ME) == UNSET


@pytest.mark.parametrize("method", ["get", "patch", "put", "post", "delete"])
def test_there_is_no_route_that_takes_another_users_id(client, signing_key, monkeypatch, fake, method):
    """No id in the URL: another user's profile is not reachable at all.
    Asserted as "refused, nothing written" rather than a specific status:
    app-wide, an unmatched URL is currently a 500, not a 404, because the
    catch-all error handler in app/__init__.py also catches werkzeug's
    NotFound (pre-existing; logged in docs/open-questions.md, IS-68)."""
    _mock_profile(monkeypatch)

    response = getattr(client, method)(
        f"/me/profile/{OTHER}", json={"phone": "9123 4567"}, headers=_auth(signing_key)
    )

    assert response.status_code >= 400
    assert _contact(fake, OTHER) == OTHERS_CONTACT
    assert not [call for call in fake.calls if call["op"] == "update"]


def test_two_users_each_write_only_their_own(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch)

    client.patch("/me/profile", json={"phone": "9123 4567"}, headers=_auth(signing_key, ME))
    client.patch("/me/profile", json={"organisation": "Changed"}, headers=_auth(signing_key, OTHER))

    assert _contact(fake, ME) == {**UNSET, "phone": "9123 4567"}
    assert _contact(fake, OTHER) == {**OTHERS_CONTACT, "organisation": "Changed"}


def test_an_invalid_phone_is_a_400(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch)

    response = client.patch("/me/profile", json={"phone": "abc"}, headers=_auth(signing_key))

    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "validation_error"


def test_a_body_that_is_not_json_is_a_400(client, signing_key, monkeypatch, fake):
    _mock_profile(monkeypatch)

    response = client.patch("/me/profile", data="phone=9123", headers=_auth(signing_key))

    assert response.status_code == 400
    assert _contact(fake, ME) == UNSET


def test_patch_without_a_token_is_a_401(client, fake):
    response = client.patch("/me/profile", json={"phone": "9123 4567"})

    assert response.status_code == 401
    assert _contact(fake, ME) == UNSET
