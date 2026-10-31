"""
app.me.profile_service (IS-68): the caller's own phone and communication
preferences -- reading, partial updates, the agreed rules (+65 phone, at
least one preference, SMS needs a phone, organisation read-only), and the
guard of the ticket: a user reads and writes their OWN profile only.
In-memory fake, no database; the real columns, checks and backfill are
test_profile_contact_integration.py's job.
"""

from __future__ import annotations

import pytest

import app.me.profile_service as service
from app.shared.errors import NotFoundError, ValidationError
from tests.fake_supabase import FakeSupabase

ME = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
NOBODY = "33333333-3333-3333-3333-333333333333"

# A profile that has never been edited: the column defaults.
DEFAULTS = {"phone": None, "organisation": None, "notify_email": True, "notify_sms": False}
OTHERS_CONTACT = {"phone": "+6580000000", "organisation": "Other Org", "notify_email": False, "notify_sms": True}


def _profile(user_id, name, email, **contact):
    return {"id": user_id, "name": name, "email": email, **DEFAULTS, **contact}


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


def _refused(fake, payload, message, code="validation_error"):
    before = dict(_row(fake, ME))
    writes_before = len(_updates(fake))
    with pytest.raises(ValidationError) as raised:
        service.update_own_profile(ME, payload)
    assert raised.value.message.startswith(message), raised.value.message
    assert raised.value.code == code
    assert len(_updates(fake)) == writes_before
    assert _row(fake, ME) == before


# -- reading ------------------------------------------------------------------


def test_a_never_edited_profile_reads_back_the_defaults(fake):
    assert service.get_contact(ME) == DEFAULTS


def test_reads_back_the_callers_own_saved_values(fake):
    service.update_own_profile(ME, {"phone": "+65 9123 4567", "notify_email": False, "notify_sms": True})

    assert service.get_contact(ME) == {
        "phone": "+6591234567", "organisation": None, "notify_email": False, "notify_sms": True,
    }


def test_the_read_is_scoped_to_the_callers_id(fake):
    service.get_contact(ME)

    read = [call for call in fake.calls if call["op"] == "select"][-1]
    assert read["filters"] == [("eq", "id", ME)]


def test_reading_returns_only_the_four_fields(fake):
    assert set(service.get_contact(ME)) == set(service.CONTACT_FIELDS)


def test_organisation_is_still_read(fake):
    """Read-only, not hidden: GET /me shows it and registrations copy it."""
    assert service.get_contact(OTHER)["organisation"] == "Other Org"


def test_a_missing_profile_is_a_404(fake):
    with pytest.raises(NotFoundError):
        service.get_contact(NOBODY)


# -- saving -------------------------------------------------------------------


def test_saving_phone_and_both_preferences(fake):
    saved = service.update_own_profile(ME, {"phone": " +65 9123 4567 ", "notify_email": False, "notify_sms": True})

    expected = {"phone": "+6591234567", "organisation": None, "notify_email": False, "notify_sms": True}
    assert saved == expected
    assert _contact(fake, ME) == expected
    assert (_row(fake, ME)["name"], _row(fake, ME)["email"]) == ("Ethan Koh", "ethan@example.com")
    assert "updated_at" in _row(fake, ME)
    _other_untouched(fake)


@pytest.mark.parametrize("typed", ["+6591234567", "+65 9123 4567", "+65-9123-4567", " +65 91234567 "])
def test_the_phone_is_stored_without_spaces_or_hyphens(fake, typed):
    assert service.update_own_profile(ME, {"phone": typed})["phone"] == "+6591234567"


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_the_phone_is_optional_and_blank_is_stored_as_null(fake, blank):
    service.update_own_profile(ME, {"phone": "+65 9123 4567"})

    assert service.update_own_profile(ME, {"phone": blank})["phone"] is None
    assert _row(fake, ME)["phone"] is None


def test_an_update_changes_only_the_fields_it_names(fake):
    service.update_own_profile(ME, {"phone": "+65 9123 4567"})

    saved = service.update_own_profile(ME, {"notify_sms": True})

    assert saved == {"phone": "+6591234567", "organisation": None, "notify_email": True, "notify_sms": True}
    assert set(_updates(fake)[-1]["payload"]) == {"notify_sms", "updated_at"}


def test_sms_only_is_allowed_with_a_phone(fake):
    saved = service.update_own_profile(ME, {"phone": "+65 9123 4567", "notify_email": False, "notify_sms": True})

    assert (saved["notify_email"], saved["notify_sms"]) == (False, True)


# -- at least one preference --------------------------------------------------------


def test_both_preferences_off_is_refused(fake):
    _refused(fake, {"notify_email": False, "notify_sms": False}, service.AT_LEAST_ONE_MESSAGE)


def test_turning_email_off_while_sms_is_off_is_refused(fake):
    """Checked on the profile after the change, not just the request."""
    _refused(fake, {"notify_email": False}, service.AT_LEAST_ONE_MESSAGE)


def test_turning_sms_off_while_email_is_off_is_refused(fake):
    service.update_own_profile(ME, {"phone": "+65 9123 4567", "notify_email": False, "notify_sms": True})

    _refused(fake, {"notify_sms": False}, service.AT_LEAST_ONE_MESSAGE)


# -- SMS needs a phone --------------------------------------------------------------


def test_sms_with_no_phone_is_refused(fake):
    _refused(fake, {"notify_sms": True}, service.SMS_NEEDS_PHONE_MESSAGE)


def test_sms_with_a_blank_phone_in_the_same_request_is_refused(fake):
    _refused(fake, {"phone": "  ", "notify_sms": True}, service.SMS_NEEDS_PHONE_MESSAGE)


def test_removing_the_phone_while_sms_is_on_is_refused(fake):
    service.update_own_profile(ME, {"phone": "+65 9123 4567", "notify_sms": True})

    _refused(fake, {"phone": None}, service.SMS_NEEDS_PHONE_MESSAGE)
    assert _row(fake, ME)["phone"] == "+6591234567"


def test_removing_the_phone_and_turning_sms_off_together_is_fine(fake):
    service.update_own_profile(ME, {"phone": "+65 9123 4567", "notify_sms": True})

    saved = service.update_own_profile(ME, {"phone": None, "notify_sms": False})

    assert (saved["phone"], saved["notify_email"], saved["notify_sms"]) == (None, True, False)


# -- own profile only: the guard of IS-68 ---------------------------------------


def test_the_update_is_scoped_to_the_callers_id(fake):
    service.update_own_profile(ME, {"phone": "+65 9123 4567"})

    assert _updates(fake)[-1]["filters"] == [("eq", "id", ME)]


def test_one_user_saving_never_writes_another_users_profile(fake):
    service.update_own_profile(ME, {"phone": "+65 9123 4567", "notify_sms": True})
    service.update_own_profile(ME, {"phone": None, "notify_sms": False})

    _other_untouched(fake)


@pytest.mark.parametrize(
    ("payload", "named"),
    [
        ({"id": OTHER, "phone": "+65 9123 4567"}, "id"),
        ({"id": ME}, "id"),
        ({"email": "other@example.com"}, "email"),
        ({"email": "ethan@example.com", "phone": "+65 9123 4567"}, "email"),
        ({"organisation": "SMU"}, "organisation"),
        ({"organisation": None, "notify_email": True}, "organisation"),
        ({"id": OTHER, "email": "other@example.com"}, "id and email"),
    ],
)
def test_a_payload_naming_a_read_only_field_is_refused_and_nothing_is_written(fake, payload, named):
    _refused(fake, payload, f"{named} cannot be changed here.", code="profile_field_not_editable")
    _other_untouched(fake)


# -- validation -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"phone": "91234567"}, service.PHONE_FORMAT_MESSAGE),  # no +65
        ({"phone": "+65 9123 456"}, service.PHONE_FORMAT_MESSAGE),  # 7 digits
        ({"phone": "+65 9123 45678"}, service.PHONE_FORMAT_MESSAGE),  # 9 digits
        ({"phone": "+60 9123 4567"}, service.PHONE_FORMAT_MESSAGE),  # not +65
        ({"phone": "+65 call me"}, service.PHONE_FORMAT_MESSAGE),
        ({"phone": 6591234567}, "phone must be text or null"),
        ({"notify_email": "yes"}, "notify_email must be true or false"),
        ({"notify_sms": 1}, "notify_sms must be true or false"),
        ({"notify_email": None}, "notify_email must be true or false"),
        ({"name": "Someone Else"}, "Unknown profile fields: name"),
        ({}, "Nothing to update"),
    ],
)
def test_invalid_updates_are_400s(fake, payload, message):
    _refused(fake, payload, message)


@pytest.mark.parametrize("payload", [None, [], "phone=9123"])
def test_a_body_that_is_not_an_object_is_a_400(fake, payload):
    with pytest.raises(ValidationError):
        service.update_own_profile(ME, payload)
    assert not _updates(fake)


def test_updating_a_profile_that_does_not_exist_is_a_404(fake):
    with pytest.raises(NotFoundError):
        service.update_own_profile(NOBODY, {"phone": "+65 9123 4567"})


def test_a_profile_deleted_between_the_read_and_the_write_is_a_404(fake, monkeypatch):
    monkeypatch.setattr(service, "_db_own_row", lambda user_id, fields: dict(DEFAULTS))

    with pytest.raises(NotFoundError):
        service.update_own_profile(NOBODY, {"phone": "+65 9123 4567"})


def test_normalise_phone():
    assert service.normalise_phone("+65 9123-4567") == "+6591234567"
