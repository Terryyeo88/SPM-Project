"""
Attendee Registration (Justin) -- rules, validation, service and routes.
Unit level: no database. The service's _db_* functions are monkeypatched.

The confirmed-vs-waitlisted decision itself lives in the database function
public.register_attendee (supabase/migrations/20261005000000_registrations.sql),
so that it's atomic. What a unit test can't prove -- capacity, the waiting
list, the registration window and concurrent registrations against real
Postgres -- is in test_registrations_integration.py.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

import app.auth.context as context_module
import app.registrations.registration_service as service
import app.registrations.routes as routes_module
from app.authz import actions
from app.authz.policy import can
from app.authz.rules import Decision, rule_event_register
from app.shared.errors import NotFoundError, ValidationError
from tests.factories import make_user

ATTENDEE = make_user(["attendee"], user_id="att-1")
ORGANISER = make_user(["event_organizer"], user_id="org-1")
COORDINATOR = make_user(["event_coordinator"], user_id="coord-9")

VALID = {"email": "ethan@example.com", "phone": "91234567", "notify_email": True, "notify_sms": False}


def _session(status="confirmed", registration_needs=True, **overrides):
    return SimpleNamespace(
        id="s1",
        organizer_id="org-1",
        coordinator_id="coord-1",
        status=status,
        registration_needs=registration_needs,
        registration_start_datetime="2026-10-03T08:00:00+00:00",
        registration_end_datetime="2026-11-02T15:59:00+00:00",
        **overrides,
    )


# -- rules -----------------------------------------------------------------------


def test_attendee_may_register_for_a_confirmed_session_with_registration_enabled():
    assert rule_event_register(ATTENDEE, _session()) is Decision.ALLOW


@pytest.mark.parametrize(
    "event",
    [
        _session(status="planning"),
        _session(status="approved"),
        _session(status="completed"),
        _session(status="cancelled"),
        _session(registration_needs=False),
        _session(registration_needs=None),
    ],
)
def test_attendee_cannot_register_unless_confirmed_and_enabled(event):
    """AC1. To an attendee such a session doesn't exist: 404, not 403."""
    assert rule_event_register(ATTENDEE, event) is Decision.DENY_NOT_FOUND


def test_only_attendees_register():
    # The organiser can see their own event, so 403; an unrelated coordinator 404.
    assert rule_event_register(ORGANISER, _session()) is Decision.DENY_FORBIDDEN
    assert rule_event_register(COORDINATOR, _session()) is Decision.DENY_NOT_FOUND


def test_only_attendees_browse_and_list_their_registrations():
    assert can(ATTENDEE, actions.REGISTRATION_LIST)
    for user in (ORGANISER, COORDINATOR, make_user(["event_coordinator_lead"])):
        assert not can(user, actions.REGISTRATION_LIST)


# -- required registration information (AC3) -------------------------------------


def test_phone_is_required():
    for phone in ("", "   ", None):
        with pytest.raises(ValidationError, match="phone number is required"):
            service.validate_registration_details({**VALID, "phone": phone})


def test_email_is_required_valid_and_normalised():
    for email in ("", "  ", None):
        with pytest.raises(ValidationError, match="email address is required"):
            service.validate_registration_details({**VALID, "email": email})
    for email in ("ethan", "ethan@", "@example.com", "ethan@example", "a b@example.com"):
        with pytest.raises(ValidationError, match="valid email"):
            service.validate_registration_details({**VALID, "email": email})
    cleaned = service.validate_registration_details({**VALID, "email": " Ethan@Example.COM "})
    assert cleaned["email"] == "ethan@example.com"


def test_at_least_one_notification_channel_is_required():
    """Edit Profile wireframe: "Email notifications" / "SMS notifications" checkboxes."""
    with pytest.raises(ValidationError, match="at least one way to be notified"):
        service.validate_registration_details({**VALID, "notify_email": False, "notify_sms": False})
    with pytest.raises(ValidationError, match="at least one way to be notified"):
        service.validate_registration_details({"email": "e@x.com", "phone": "91234567"})


@pytest.mark.parametrize(("notify_email", "notify_sms"), [(True, False), (False, True), (True, True)])
def test_email_sms_or_both(notify_email, notify_sms):
    cleaned = service.validate_registration_details({**VALID, "notify_email": notify_email, "notify_sms": notify_sms})
    assert (cleaned["notify_email"], cleaned["notify_sms"]) == (notify_email, notify_sms)


@pytest.mark.parametrize("field", ["notify_email", "notify_sms", "include_organisation"])
def test_choices_must_be_booleans(field):
    with pytest.raises(ValidationError, match=f"{field} must be true or false"):
        service.validate_registration_details({**VALID, field: "yes"})


def test_organisation_is_left_out_unless_asked_for():
    assert service.validate_registration_details(VALID)["include_organisation"] is False


def test_name_and_organisation_cannot_be_submitted():
    """They come from the profile; the form only shows them."""
    for field in ("name", "organisation"):
        with pytest.raises(ValidationError, match="Unknown registration fields"):
            service.validate_registration_details({**VALID, field: "Someone Else"})


@pytest.mark.parametrize("phone", ["abc", "12", "9123-45x7", "+", "1" * 25])
def test_phone_must_look_like_a_phone_number(phone):
    with pytest.raises(ValidationError, match="valid phone number"):
        service.validate_registration_details({**VALID, "phone": phone})


@pytest.mark.parametrize("phone", ["91234567", "9123 4567", "+65 9123 4567", "+65-9123-4567"])
def test_valid_phone_numbers_are_accepted_and_trimmed(phone):
    assert service.validate_registration_details({**VALID, "phone": f" {phone} "})["phone"] == phone


def test_notes_are_optional_trimmed_and_capped():
    assert service.validate_registration_details(VALID)["notes"] is None
    assert service.validate_registration_details({**VALID, "notes": "  "})["notes"] is None
    assert service.validate_registration_details({**VALID, "notes": " vegan "})["notes"] == "vegan"
    with pytest.raises(ValidationError, match="at most"):
        service.validate_registration_details({**VALID, "notes": "x" * 501})


def test_unknown_fields_are_refused():
    with pytest.raises(ValidationError, match="Unknown registration fields: status"):
        service.validate_registration_details({**VALID, "status": "confirmed"})


# -- register: outcome of the database function ---------------------------------


@pytest.fixture
def db_result(monkeypatch):
    calls = []

    def set_result(result):
        def fake(event_id, attendee_id, details):
            calls.append((event_id, attendee_id, details))
            return result

        monkeypatch.setattr(service, "_db_register", fake)
        monkeypatch.setattr(service, "_db_profile_organisation", lambda attendee_id: "Acme Pte Ltd")
        return calls

    return set_result


@pytest.mark.parametrize("status", ["confirmed", "waitlisted"])
def test_register_returns_the_recorded_registration(db_result, status):
    """AC4/AC5: the status the database function decided is what comes back."""
    calls = db_result({"outcome": "registered", "registration": {"id": "r1", "status": status}})

    registration = service.register(_session(), "att-1", {**VALID, "notes": "vegan"})

    assert registration == {"id": "r1", "status": status}
    assert calls == [
        ("s1", "att-1", {**VALID, "include_organisation": False, "organisation": None, "notes": "vegan"})
    ]


def test_included_organisation_is_the_profiles(db_result):
    calls = db_result({"outcome": "registered", "registration": {}})
    service.register(_session(), "att-1", {**VALID, "include_organisation": True})
    assert calls[0][2]["organisation"] == "Acme Pte Ltd"


def test_invalid_details_never_reach_the_database(db_result):
    calls = db_result({"outcome": "registered", "registration": {}})
    with pytest.raises(ValidationError):
        service.register(_session(), "att-1", {**VALID, "phone": "nope"})
    assert calls == []


@pytest.mark.parametrize(
    ("outcome", "message"),
    [
        ("already_registered", "already registered"),
        ("not_started", "opens on 3 Oct 2026, 4:00 PM"),  # 08:00 UTC shown in Singapore time
        ("closed", "closed on 2 Nov 2026, 11:59 PM"),
        ("not_open", "no longer open"),
    ],
)
def test_register_explains_each_refusal(db_result, outcome, message):
    """AC2 (registration period) and duplicates, with a message an attendee can act on."""
    db_result({"outcome": outcome})
    with pytest.raises(ValidationError, match=message):
        service.register(_session(), "att-1", VALID)


def test_register_for_a_session_that_vanished_is_404(db_result):
    db_result({"outcome": "not_found"})
    with pytest.raises(NotFoundError):
        service.register(_session(), "att-1", VALID)


# -- withdraw ----------------------------------------------------------------------


@pytest.mark.parametrize(("promoted_id", "promoted"), [("r9", True), (None, False)])
def test_withdraw_reports_whether_the_next_person_moved_up(monkeypatch, promoted_id, promoted):
    calls = []

    def fake(event_id, attendee_id):
        calls.append((event_id, attendee_id))
        return {"outcome": "withdrawn", "promoted_registration_id": promoted_id}

    monkeypatch.setattr(service, "_db_withdraw", fake)
    assert service.withdraw("s1", "att-1") == {"withdrawn": True, "promoted": promoted}
    assert calls == [("s1", "att-1")]


def test_withdraw_without_a_registration_is_404(monkeypatch):
    monkeypatch.setattr(service, "_db_withdraw", lambda *a: {"outcome": "not_registered"})
    with pytest.raises(NotFoundError, match="aren't registered"):
        service.withdraw("s1", "att-1")


def test_withdraw_after_the_session_started_is_refused(monkeypatch):
    monkeypatch.setattr(service, "_db_withdraw", lambda *a: {"outcome": "started"})
    with pytest.raises(ValidationError, match="already started"):
        service.withdraw("s1", "att-1")


# -- browsing and my registrations ------------------------------------------------


def test_open_sessions_carry_places_left(monkeypatch):
    seen = {}

    def fake_sessions(from_date):
        seen["from"] = from_date
        return [
            {"id": "full", "name": "Talk", "expected_attendance": 2},
            {"id": "roomy", "name": "Talk", "expected_attendance": 50},
            {"id": "unlimited", "name": "Talk", "expected_attendance": None},
        ]

    monkeypatch.setattr(service, "_db_public_sessions", fake_sessions)
    monkeypatch.setattr(
        service,
        "_db_registration_statuses",
        lambda ids: [
            {"event_id": "full", "status": "confirmed"},
            {"event_id": "full", "status": "confirmed"},
            {"event_id": "full", "status": "waitlisted"},
            {"event_id": "roomy", "status": "confirmed"},
        ],
    )

    sessions = {s["id"]: s for s in service.list_open_sessions(today=date(2026, 10, 4))}

    assert seen["from"] == "2026-10-04"
    assert (sessions["full"]["places_left"], sessions["full"]["waitlist_count"]) == (0, 1)
    assert sessions["roomy"]["places_left"] == 49
    assert sessions["unlimited"]["places_left"] is None


def test_my_registrations_show_waiting_list_position_first_come_first_served(monkeypatch):
    monkeypatch.setattr(
        service,
        "_db_my_registrations",
        lambda attendee_id: [
            {"id": "mine-1", "event_id": "s1", "status": "waitlisted", "registered_at": "2026-10-04T10:00:02"},
            {"id": "mine-2", "event_id": "s2", "status": "confirmed", "registered_at": "2026-10-04T09:00:00"},
        ],
    )
    monkeypatch.setattr(
        service,
        "_db_sessions_by_id",
        lambda ids: [
            {"id": "s1", "name": "Talk", "preferred_start_date": "2026-11-03"},
            {"id": "s2", "name": "Talk", "preferred_start_date": "2026-11-01"},
        ],
    )
    monkeypatch.setattr(
        service,
        "_db_waitlists",
        lambda ids: [
            {"id": "mine-1", "event_id": "s1", "registered_at": "2026-10-04T10:00:02"},
            {"id": "earlier", "event_id": "s1", "registered_at": "2026-10-04T10:00:01"},
        ],
    )

    mine = service.list_my_registrations("att-1")

    assert [r["id"] for r in mine] == ["mine-2", "mine-1"]  # soonest session first
    assert mine[0]["waitlist_position"] is None
    assert mine[1]["waitlist_position"] == 2
    assert mine[1]["session"]["name"] == "Talk"


def test_session_page_has_places_and_my_registration(monkeypatch):
    monkeypatch.setattr(service, "_db_sessions_by_id", lambda ids: [{"id": "s1", "expected_attendance": 2}])
    monkeypatch.setattr(service, "_db_registration_statuses", lambda ids: [{"event_id": "s1", "status": "confirmed"}])
    monkeypatch.setattr(
        service,
        "list_my_registrations",
        lambda attendee_id: [{"id": "r1", "event_id": "s1", "status": "confirmed", "session": {"id": "s1"}}],
    )

    page = service.get_session("s1", "att-1")

    assert page["places_left"] == 1
    assert page["my_registration"] == {"id": "r1", "event_id": "s1", "status": "confirmed"}


def test_no_registrations_makes_no_further_queries(monkeypatch):
    monkeypatch.setattr(service, "_db_my_registrations", lambda attendee_id: [])
    monkeypatch.setattr(service, "_db_sessions_by_id", lambda ids: pytest.fail("should not query sessions"))
    assert service.list_my_registrations("att-1") == []


# -- routes ------------------------------------------------------------------------


def _as(monkeypatch, signing_key, roles, user_id):
    monkeypatch.setattr(
        context_module, "_load_profile_with_roles",
        lambda _user_id: ("Test User", "test@example.com", frozenset(roles)),
    )
    monkeypatch.setattr(context_module, "_get_last_active", lambda session_id: None)
    monkeypatch.setattr(context_module, "_touch_session_activity", lambda *a, **k: None)
    return {"Authorization": f"Bearer {signing_key.make_token(sub=user_id)}"}


def test_register_route_registers_the_caller(client, signing_key, monkeypatch):
    headers = _as(monkeypatch, signing_key, ["attendee"], "att-1")
    monkeypatch.setattr(routes_module, "load_session", lambda event_id: _session())
    calls = []

    def fake_register(event, attendee_id, payload):
        calls.append((event.id, attendee_id, payload))
        return {"id": "r1", "status": "waitlisted"}

    monkeypatch.setattr(routes_module, "register", fake_register)

    response = client.post("/registrations/s1", headers=headers, json=VALID)

    assert response.status_code == 201
    assert response.get_json()["status"] == "waitlisted"
    assert calls == [("s1", "att-1", VALID)]


def test_register_route_hides_an_unconfirmed_session_from_attendees(client, signing_key, monkeypatch):
    headers = _as(monkeypatch, signing_key, ["attendee"], "att-1")
    monkeypatch.setattr(routes_module, "load_session", lambda event_id: _session(status="planning"))
    monkeypatch.setattr(routes_module, "register", lambda *a: pytest.fail("must not register"))

    response = client.post("/registrations/s1", headers=headers, json=VALID)

    assert response.status_code == 404


def test_register_route_refuses_non_attendees(client, signing_key, monkeypatch):
    headers = _as(monkeypatch, signing_key, ["event_organizer"], "org-1")
    monkeypatch.setattr(routes_module, "load_session", lambda event_id: _session())
    monkeypatch.setattr(routes_module, "register", lambda *a: pytest.fail("must not register"))

    response = client.post("/registrations/s1", headers=headers, json=VALID)

    assert response.status_code == 403


def test_list_routes_are_attendee_only(client, signing_key, monkeypatch):
    monkeypatch.setattr(routes_module, "list_open_sessions", lambda: [{"id": "s1"}])
    monkeypatch.setattr(routes_module, "list_my_registrations", lambda attendee_id: [{"id": "r1"}])

    headers = _as(monkeypatch, signing_key, ["attendee"], "att-1")
    assert client.get("/registrations/open", headers=headers).get_json() == [{"id": "s1"}]
    assert client.get("/registrations/mine", headers=headers).get_json() == [{"id": "r1"}]

    headers = _as(monkeypatch, signing_key, ["event_coordinator"], "coord-1")
    assert client.get("/registrations/open", headers=headers).status_code == 403
    assert client.get("/registrations/mine", headers=headers).status_code == 403


def test_session_and_withdraw_routes(client, signing_key, monkeypatch):
    headers = _as(monkeypatch, signing_key, ["attendee"], "att-1")
    monkeypatch.setattr(routes_module, "load_session", lambda event_id: _session())
    monkeypatch.setattr(routes_module, "get_session", lambda event_id, attendee_id: {"id": event_id})
    monkeypatch.setattr(routes_module, "withdraw", lambda event_id, attendee_id: {"withdrawn": True})

    assert client.get("/registrations/sessions/s1", headers=headers).get_json() == {"id": "s1"}
    assert client.delete("/registrations/s1", headers=headers).get_json() == {"withdrawn": True}


def test_session_page_is_hidden_from_attendees_unless_public(client, signing_key, monkeypatch):
    headers = _as(monkeypatch, signing_key, ["attendee"], "att-1")
    monkeypatch.setattr(routes_module, "load_session", lambda event_id: _session(status="planning"))
    assert client.get("/registrations/sessions/s1", headers=headers).status_code == 404


def test_only_attendees_withdraw(client, signing_key, monkeypatch):
    headers = _as(monkeypatch, signing_key, ["event_organizer"], "org-1")
    monkeypatch.setattr(routes_module, "load_session", lambda event_id: _session())
    monkeypatch.setattr(routes_module, "withdraw", lambda *a: pytest.fail("must not withdraw"))
    assert client.delete("/registrations/s1", headers=headers).status_code == 403
