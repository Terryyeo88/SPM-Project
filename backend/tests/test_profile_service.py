"""
app.me.profile_service (IS-68): the caller's own phone, organisation and
communication preferences -- reading, partial updates, blank optional
fields, validation, and the guard of the ticket: a user reads and writes
their OWN profile only. In-memory fake, no database; the real columns and
existing NULL rows are test_profile_contact_integration.py's job.
"""

from __future__ import annotations

import pytest

import app.me.profile_service as service
from app.shared.errors import NotFoundError, ValidationError
from tests.fake_supabase import FakeSupabase

ME = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
NOBODY = "33333333-3333-3333-3333-333333333333"

UNSET = {"phone": None, "organisation": None, "notify_email": None, "notify_sms": None}
OTHERS_CONTACT = {"phone": "+65 8000 0000", "organisation": "Other Org", "notify_email": False, "notify_sms": True}


def _profile(user_id, name, email, **contact):
    return {"id": user_id, "name": name, "email": email, **UNSET, **contact}


@pytest.fixture
def fake(monkeypatch):
    db = FakeSupabase()
    db.tables["profiles"] = [
        _profile(ME, "Ethan Koh", "ethan@example.com"),
        _profile(OTHER, "Other Person", "other@example.com", **OTHERS_CONTACT),
    ]
    monkeypatch.setattr(service, "supabase", db)
    return db


def _row(fake, user_id):
    return next(row for row in fake.tables["profiles"] if row["id"] == user_id)


def _contact(fake, user_id):
    return {field: _row(fake, user_id)[field] for field in service.CONTACT_FIELDS}


def _updates(fake):
    return [call for call in fake.calls if call["op"] == "update"]


def _other_untouched(fake):
    assert _row(fake, OTHER) == _profile(OTHER, "Other Person", "other@example.com", **OTHERS_CONTACT)


# -- reading ------------------------------------------------------------------


def test_a_profile_with_nothing_given_reads_back_as_all_null(fake):
    assert service.get_contact(ME) == UNSET


def test_reads_back_the_callers_own_saved_values(fake):
    service.update_own_profile(
        ME, {"phone": "9123 4567", "organisation": "SMU", "notify_email": True, "notify_sms": False}
    )

    assert service.get_contact(ME) == {
        "phone": "9123 4567", "organisation": "SMU", "notify_email": True, "notify_sms": False,
    }


def test_the_read_is_scoped_to_the_callers_id(fake):
    service.get_contact(ME)

    read = [call for call in fake.calls if call["op"] == "select"][-1]
    assert read["filters"] == [("eq", "id", ME)]


def test_reading_returns_only_the_four_fields_and_never_another_users(fake):
    contact = service.get_contact(ME)

    assert set(contact) == set(service.CONTACT_FIELDS)
    assert contact == UNSET


def test_a_missing_profile_is_a_404(fake):
    with pytest.raises(NotFoundError):
        service.get_contact(NOBODY)


# -- saving -------------------------------------------------------------------


def test_saving_all_three(fake):
    saved = service.update_own_profile(
        ME,
        {"phone": " +65 9123 4567 ", "organisation": " Singapore Management University ",
         "notify_email": False, "notify_sms": True},
    )

    expected = {"phone": "+65 9123 4567", "organisation": "Singapore Management University",
                "notify_email": False, "notify_sms": True}
    assert saved == expected
    assert _contact(fake, ME) == expected
    assert (_row(fake, ME)["name"], _row(fake, ME)["email"]) == ("Ethan Koh", "ethan@example.com")
    assert "updated_at" in _row(fake, ME)
    _other_untouched(fake)


def test_saving_with_the_optional_ones_blank_stores_null_not_empty_text(fake):
    service.update_own_profile(ME, {"phone": "9123 4567", "organisation": "SMU"})

    saved = service.update_own_profile(
        ME, {"phone": "   ", "organisation": "", "notify_email": None, "notify_sms": None}
    )

    assert saved == UNSET
    assert _contact(fake, ME) == UNSET


def test_saving_with_organisation_left_out_entirely(fake):
    saved = service.update_own_profile(ME, {"phone": "9123 4567", "notify_email": True, "notify_sms": False})

    assert saved == {"phone": "9123 4567", "organisation": None, "notify_email": True, "notify_sms": False}


def test_an_update_changes_only_the_fields_it_names(fake):
    service.update_own_profile(ME, {"phone": "9123 4567", "organisation": "SMU", "notify_email": True})

    saved = service.update_own_profile(ME, {"notify_sms": True})

    assert saved == {"phone": "9123 4567", "organisation": "SMU", "notify_email": True, "notify_sms": True}
    assert set(_updates(fake)[-1]["payload"]) == {"notify_sms", "updated_at"}


def test_both_preferences_may_be_false(fake):
    """A profile may say "neither": nothing sends email or SMS yet, and a
    registration still asks for at least one of its own."""
    saved = service.update_own_profile(ME, {"notify_email": False, "notify_sms": False})

    assert (saved["notify_email"], saved["notify_sms"]) == (False, False)


# -- own profile only: the guard of IS-68 ---------------------------------------


def test_the_update_is_scoped_to_the_callers_id(fake):
    service.update_own_profile(ME, {"phone": "9123 4567"})

    assert _updates(fake)[-1]["filters"] == [("eq", "id", ME)]


def test_one_user_saving_never_writes_another_users_profile(fake):
    service.update_own_profile(
        ME, {"phone": "9123 4567", "organisation": "SMU", "notify_email": True, "notify_sms": True}
    )
    service.update_own_profile(ME, {"phone": None, "organisation": None})

    _other_untouched(fake)


@pytest.mark.parametrize(
    ("payload", "named"),
    [
        ({"id": OTHER, "phone": "9123 4567"}, "id"),
        ({"id": ME}, "id"),
        ({"email": "other@example.com"}, "email"),
        ({"email": "ethan@example.com", "phone": "9123 4567"}, "email"),
        ({"id": OTHER, "email": "other@example.com"}, "id and email"),
    ],
)
def test_a_payload_naming_id_or_email_is_refused_and_nothing_is_written(fake, payload, named):
    with pytest.raises(ValidationError) as raised:
        service.update_own_profile(ME, payload)

    assert raised.value.code == "profile_field_not_editable"
    assert raised.value.message == f"{named} cannot be changed here."
    assert not _updates(fake)
    assert _row(fake, ME) == _profile(ME, "Ethan Koh", "ethan@example.com")
    _other_untouched(fake)


# -- validation -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"phone": "123"}, "Enter a valid phone number"),
        ({"phone": "call me"}, "Enter a valid phone number"),
        ({"phone": 91234567}, "phone must be text or null"),
        ({"organisation": ["SMU"]}, "organisation must be text or null"),
        ({"organisation": "x" * 201}, "Organisation can be at most 200 characters"),
        ({"notify_email": "yes"}, "notify_email must be true, false or null"),
        ({"notify_sms": 1}, "notify_sms must be true, false or null"),
        ({"name": "Someone Else"}, "Unknown profile fields: name"),
        ({}, "Nothing to update"),
    ],
)
def test_invalid_updates_are_400s(fake, payload, message):
    with pytest.raises(ValidationError) as raised:
        service.update_own_profile(ME, payload)

    assert raised.value.message.startswith(message)
    assert raised.value.code == "validation_error"
    assert not _updates(fake)


@pytest.mark.parametrize("payload", [None, [], "phone=9123"])
def test_a_body_that_is_not_an_object_is_a_400(fake, payload):
    with pytest.raises(ValidationError):
        service.update_own_profile(ME, payload)


def test_organisation_at_the_length_limit_is_accepted(fake):
    assert service.update_own_profile(ME, {"organisation": "x" * 200})["organisation"] == "x" * 200


def test_updating_a_profile_that_does_not_exist_is_a_404(fake):
    with pytest.raises(NotFoundError):
        service.update_own_profile(NOBODY, {"phone": "9123 4567"})
