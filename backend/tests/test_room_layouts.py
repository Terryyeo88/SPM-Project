"""Room layouts managed by Venue Staff -- IS-60 Venue Categories.

Story: "As a Venue staff, I want to record what type of venues are
available so that I can properly categorize the venues." Venue categories
are the room layouts (theatre, classroom, ...): the `room_layouts` table,
`/room-layouts` routes and app/room_layouts/room_layout_service.py.
Disabling a category is its soft delete (is_active = false).

  AC1  Venue Staff create a category.
  AC2  Venue Staff edit a category.
  AC3  A category can be disabled while ongoing events use it.
  AC4  A category must be disabled before it can be permanently deleted.
  AC5  A disabled category can be permanently deleted once no ongoing event
       (one not completed, cancelled or rejected) uses it.

Also: who may list categories, and how event validation (drafts,
submission, change requests, a stale form) treats active vs disabled ones.

These run against the in-memory FakeSupabase. The database's own rules
(permanent delete only once disabled and no ongoing event uses it, names
kept on events, renames reaching events and venues) are tested against a
real database in test_room_layouts_integration.py.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from postgrest.exceptions import APIError

import app.auth.context as context_module
import app.events.change_request_service as change_request_service
import app.events.event_service as event_service
import app.events.routes as routes_module
import app.room_layouts.room_layout_service as service
from app.authz import actions
from app.authz.policy import can
from app.shared.errors import ValidationError
from tests.factories import make_user
from tests.fake_supabase import FakeSupabase

# -- authz ---------------------------------------------------------------------


@pytest.mark.parametrize("role", ["event_organizer", "event_coordinator", "event_coordinator_lead", "venue_staff"])
def test_every_role_that_works_with_layouts_can_list_them(role):
    assert can(make_user([role]), actions.ROOM_LAYOUT_LIST) is True


def test_a_role_with_no_use_for_layouts_cannot_list_them():
    assert can(make_user(["attendee"]), actions.ROOM_LAYOUT_LIST) is False


@pytest.mark.parametrize(
    ("role", "allowed"),
    [
        ("venue_staff", True),
        ("event_organizer", False),
        ("event_coordinator", False),
        ("event_coordinator_lead", False),
    ],
)
def test_only_venue_staff_manage_layouts(role, allowed):
    assert can(make_user([role]), actions.ROOM_LAYOUT_MANAGE) is allowed


# Not completed, cancelled or rejected. Drafts and rejected sessions are with
# their organiser to fix: disabling a category clears it from them (database
# trigger), so they never hold one up.
ONGOING_STATUSES = ["submitted", "under_review", "approved", "planning", "safety_review", "confirmed"]
NON_STAFF_ROLES = [
    "event_organizer",
    "event_coordinator",
    "event_coordinator_lead",
    "safety_officer",
    "attendee",
]


def _category(room_layout_id, name, is_active=True):
    return {"room_layout_id": room_layout_id, "name": name, "is_active": is_active}


def _db_error(code, message="refused"):
    return APIError({"message": message, "code": code, "hint": None, "details": None})


class _RefusingSupabase(FakeSupabase):
    """FakeSupabase whose `refuse_op` queries on room_layouts raise `error`,
    the way the real database refuses through a constraint or trigger."""

    def __init__(self, rows, refuse_op, error):
        super().__init__()
        self.tables["room_layouts"] = [dict(row) for row in rows]
        self.refuse_op, self.error = refuse_op, error

    def table(self, name):
        query = super().table(name)
        execute = query.execute

        def refusing_execute():
            if name == "room_layouts" and query.op == self.refuse_op:
                raise self.error
            return execute()

        query.execute = refusing_execute
        return query


class _CategoriesSupabase(FakeSupabase):
    """FakeSupabase that fills in room_layouts.is_active on insert, as the
    column's database default (true) does."""

    def table(self, name):
        query = super().table(name)
        insert = query.insert

        def insert_with_default(payload):
            return insert({"is_active": True, **payload} if name == "room_layouts" else payload)

        query.insert = insert_with_default
        return query


# Event validation's real lookup of the categories table; conftest's autouse
# _seeded_room_layouts replaces it with a fixed list for every unit test.
_REAL_ROOM_LAYOUTS = event_service._room_layouts


@pytest.fixture
def categories_db(monkeypatch):
    """theatre is active, banquet is disabled. Event validation reads the
    same table (event_service -> list_room_layouts), so the effect of a
    change on what events may pick is visible through this fake too."""
    fake = _CategoriesSupabase()
    fake.tables["room_layouts"] = [
        _category("theatre-id", "theatre"),
        _category("banquet-id", "banquet", is_active=False),
    ]
    monkeypatch.setattr(service, "supabase", fake)
    monkeypatch.setattr(event_service, "_room_layouts", _REAL_ROOM_LAYOUTS)
    return fake


@pytest.fixture
def api(client, signing_key, monkeypatch):
    """Calls the API as a user holding `roles`."""

    def call(method, path, roles, body=None):
        monkeypatch.setattr(
            context_module,
            "_load_profile_with_roles",
            lambda user_id: ("Test User", "test@example.com", frozenset(roles)),
        )
        monkeypatch.setattr(context_module, "_get_last_active", lambda session_id: None)
        monkeypatch.setattr(context_module, "_touch_session_activity", lambda *a, **k: None)
        headers = {"Authorization": f"Bearer {signing_key.make_token(sub='user-1')}"}
        return client.open(path, method=method, headers=headers, json=body)

    return call


def _listed(api, roles=("venue_staff",), include_inactive=True):
    path = "/room-layouts?include_inactive=true" if include_inactive else "/room-layouts"
    return {row["name"]: row["is_active"] for row in api("GET", path, list(roles)).get_json()}


def _choose(name, current=None):
    """Validates an event session picking category `name`."""
    return event_service.validate_event_payload(
        {"name": "Talk", "room_layout": name}, for_submission=False, current_room_layout=current
    )


def _stored(db):
    return [dict(row) for row in db.tables["room_layouts"]]


# -- AC1: Venue Staff create a category ------------------------------------------


def test_ac1_venue_staff_create_a_category(api, categories_db):
    response = api("POST", "/room-layouts", ["venue_staff"], {"name": "  U-shape  "})

    assert response.status_code == 201
    created = response.get_json()
    assert created["name"] == "U-shape"  # trimmed
    assert created["is_active"] is True
    assert created["room_layout_id"]


def test_ac1_a_new_category_is_offered_to_organisers_and_can_be_chosen(api, categories_db):
    api("POST", "/room-layouts", ["venue_staff"], {"name": "u-shape"})

    assert "u-shape" in _listed(api, ["event_organizer"], include_inactive=False)
    assert _choose("u-shape")["room_layout"] == "u-shape"


@pytest.mark.parametrize(
    "body",
    [None, {}, {"name": ""}, {"name": "   "}, {"name": 5}, {"name": None}, {"name": "x", "is_active": False}, ["x"]],
    ids=["no-body", "empty", "blank", "whitespace", "number", "null", "extra-field", "list"],
)
def test_ac1_a_category_needs_a_non_blank_name(api, categories_db, body):
    before = _stored(categories_db)

    response = api("POST", "/room-layouts", ["venue_staff"], body)

    assert response.status_code == 400
    assert _stored(categories_db) == before


def test_ac1_a_duplicate_name_is_refused_and_points_to_restoring(api, monkeypatch):
    """The unique index is case-insensitive, and the clash may be with a
    disabled category the user can't pick -- so the message says to
    restore it."""
    monkeypatch.setattr(service, "supabase", _RefusingSupabase([], "insert", _db_error("23505")))

    response = api("POST", "/room-layouts", ["venue_staff"], {"name": "Banquet"})

    assert response.status_code == 409
    assert response.get_json()["error"]["message"] == (
        'A room layout named "Banquet" already exists. If it was deleted, restore it instead.'
    )


@pytest.mark.parametrize("role", NON_STAFF_ROLES)
def test_ac1_only_venue_staff_create_a_category(api, categories_db, role):
    before = _stored(categories_db)

    response = api("POST", "/room-layouts", [role], {"name": "u-shape"})

    assert response.status_code == 403
    assert _stored(categories_db) == before


def test_ac1_creating_needs_a_signed_in_user(client, categories_db):
    assert client.post("/room-layouts", json={"name": "u-shape"}).status_code == 401


# -- AC2: Venue Staff edit a category ----------------------------------------------


def test_ac2_venue_staff_rename_a_category(api, categories_db):
    response = api("POST", "/room-layouts/theatre-id", ["venue_staff"], {"name": " Theatre Style "})

    assert response.status_code == 200
    assert response.get_json() == _category("theatre-id", "Theatre Style")  # same row, trimmed
    assert _listed(api) == {"Theatre Style": True, "banquet": False}


def test_ac2_events_pick_the_category_by_its_new_name(api, categories_db):
    api("POST", "/room-layouts/theatre-id", ["venue_staff"], {"name": "theatre style"})

    assert _choose("theatre style")["room_layout"] == "theatre style"
    with pytest.raises(ValidationError, match="no longer exists"):
        _choose("theatre")


def test_ac2_editing_a_disabled_category_keeps_it_disabled(api, categories_db):
    response = api("POST", "/room-layouts/banquet-id", ["venue_staff"], {"name": "gala banquet"})

    assert response.status_code == 200
    assert response.get_json()["is_active"] is False


@pytest.mark.parametrize("body", [{}, {"name": "  "}, {"name": 5}, {"name": "x", "is_active": True}])
def test_ac2_an_edit_needs_a_non_blank_name_and_changes_nothing_otherwise(api, categories_db, body):
    before = _stored(categories_db)

    response = api("POST", "/room-layouts/theatre-id", ["venue_staff"], body)

    assert response.status_code == 400
    assert _stored(categories_db) == before


def test_ac2_renaming_onto_another_categorys_name_is_refused(api, monkeypatch):
    fake = _RefusingSupabase([_category("theatre-id", "theatre")], "update", _db_error("23505"))
    monkeypatch.setattr(service, "supabase", fake)

    response = api("POST", "/room-layouts/theatre-id", ["venue_staff"], {"name": "banquet"})

    assert response.status_code == 409
    assert "already exists" in response.get_json()["error"]["message"]


def test_ac2_editing_an_unknown_category_is_a_404(api, categories_db):
    assert api("POST", "/room-layouts/nope", ["venue_staff"], {"name": "x"}).status_code == 404


@pytest.mark.parametrize("role", NON_STAFF_ROLES)
def test_ac2_only_venue_staff_edit_a_category(api, categories_db, role):
    before = _stored(categories_db)

    response = api("POST", "/room-layouts/theatre-id", [role], {"name": "renamed"})

    assert response.status_code == 403
    assert _stored(categories_db) == before


# -- AC3: disable a category while ongoing events use it ---------------------------


def test_ac3_a_category_used_by_ongoing_events_can_be_disabled(api, categories_db):
    """Disabling isn't held up by events: one per ongoing status uses
    theatre, and the soft delete still goes through without touching them.
    (Drafts lose the category through a database trigger -- integration.)"""
    categories_db.rows = [
        {"id": f"event-{status}", "status": status, "room_layout": "theatre", "room_layout_id": "theatre-id"}
        for status in ONGOING_STATUSES
    ]
    events_before = [dict(row) for row in categories_db.rows]

    response = api("DELETE", "/room-layouts/theatre-id", ["venue_staff"])

    assert response.status_code == 200
    assert response.get_json()["is_active"] is False
    assert categories_db.rows == events_before
    assert {call["table"] for call in categories_db.calls} == {"room_layouts"}


def test_ac3_a_disabled_category_is_no_longer_offered(api, categories_db):
    api("DELETE", "/room-layouts/theatre-id", ["venue_staff"])

    assert "theatre" not in _listed(api, ["event_organizer"], include_inactive=False)
    assert _listed(api) == {"banquet": False, "theatre": False}  # Venue Staff still see it


def test_ac3_a_disabled_category_cannot_be_chosen_for_a_new_event(api, categories_db):
    api("DELETE", "/room-layouts/theatre-id", ["venue_staff"])

    with pytest.raises(ValidationError, match='"theatre" no longer exists'):
        _choose("theatre")


def test_ac3_an_ongoing_event_keeps_its_disabled_category(api, categories_db):
    api("DELETE", "/room-layouts/theatre-id", ["venue_staff"])

    assert _choose("theatre", current="theatre")["room_layout"] == "theatre"


def test_ac3_a_disabled_category_can_be_restored(api, categories_db):
    api("DELETE", "/room-layouts/theatre-id", ["venue_staff"])

    response = api("POST", "/room-layouts/theatre-id/restore", ["venue_staff"])

    assert response.status_code == 200
    assert response.get_json()["is_active"] is True
    assert _choose("theatre")["room_layout"] == "theatre"


@pytest.mark.parametrize(
    ("method", "path"),
    [("DELETE", "/room-layouts/nope"), ("POST", "/room-layouts/nope/restore")],
)
def test_ac3_disabling_or_restoring_an_unknown_category_is_a_404(api, categories_db, method, path):
    assert api(method, path, ["venue_staff"]).status_code == 404


@pytest.mark.parametrize("role", NON_STAFF_ROLES)
@pytest.mark.parametrize(
    ("method", "path"),
    [("DELETE", "/room-layouts/theatre-id"), ("POST", "/room-layouts/banquet-id/restore")],
)
def test_ac3_only_venue_staff_disable_or_restore(api, categories_db, role, method, path):
    before = _stored(categories_db)

    assert api(method, path, [role]).status_code == 403
    assert _stored(categories_db) == before


@pytest.mark.parametrize("role", NON_STAFF_ROLES)
def test_ac3_only_venue_staff_see_disabled_categories(api, categories_db, role):
    assert api("GET", "/room-layouts?include_inactive=true", [role]).status_code == 403


# -- AC4: disable before permanently deleting --------------------------------------


def test_ac4_an_active_category_cannot_be_permanently_deleted(api, categories_db):
    response = api("DELETE", "/room-layouts/theatre-id/permanent", ["venue_staff"])

    assert response.status_code == 409
    assert response.get_json()["error"]["message"] == (
        'Room layout "theatre" must be soft-deleted before it can be permanently deleted.'
    )
    assert [call["op"] for call in categories_db.calls] == ["select"]  # the delete is never sent
    assert _listed(api)["theatre"] is True


def test_ac4_restored_between_the_check_and_the_delete_is_still_refused(api, monkeypatch):
    """The database trigger refuses an active category with check_violation
    (23514) even if it was restored after the service looked."""
    message = 'Room layout "banquet" must be soft-deleted before it can be permanently deleted.'
    fake = _RefusingSupabase(
        [_category("banquet-id", "banquet", is_active=False)], "delete", _db_error("23514", message)
    )
    monkeypatch.setattr(service, "supabase", fake)

    response = api("DELETE", "/room-layouts/banquet-id/permanent", ["venue_staff"])

    assert response.status_code == 409
    assert response.get_json()["error"]["message"] == message


def test_ac4_disable_then_permanently_delete(api, categories_db):
    assert api("DELETE", "/room-layouts/theatre-id/permanent", ["venue_staff"]).status_code == 409
    assert api("DELETE", "/room-layouts/theatre-id", ["venue_staff"]).status_code == 200
    assert api("DELETE", "/room-layouts/theatre-id/permanent", ["venue_staff"]).status_code == 204


# -- AC5: permanent delete once no ongoing event uses it ---------------------------


def test_ac5_a_disabled_unused_category_is_permanently_deleted(api, categories_db):
    response = api("DELETE", "/room-layouts/banquet-id/permanent", ["venue_staff"])

    assert response.status_code == 204
    assert _listed(api) == {"theatre": True}
    assert api("POST", "/room-layouts/banquet-id/restore", ["venue_staff"]).status_code == 404


def test_ac5_a_permanently_deleted_category_cannot_be_chosen(api, categories_db):
    api("DELETE", "/room-layouts/banquet-id/permanent", ["venue_staff"])

    with pytest.raises(ValidationError, match="Please refresh the page and choose a new room layout"):
        _choose("banquet")


def test_ac5_refused_while_an_ongoing_event_uses_it(api, monkeypatch):
    """The database refuses (trigger, 23503) while an event that isn't
    completed, cancelled or rejected still uses the category; its reason is shown
    and the category stays."""
    message = 'Room layout "banquet" is still used by 1 event(s) that are not completed, cancelled or rejected.'
    fake = _RefusingSupabase(
        [_category("banquet-id", "banquet", is_active=False)], "delete", _db_error("23503", message)
    )
    monkeypatch.setattr(service, "supabase", fake)

    response = api("DELETE", "/room-layouts/banquet-id/permanent", ["venue_staff"])

    assert response.status_code == 409
    assert response.get_json()["error"]["message"] == message
    assert fake.tables["room_layouts"] == [_category("banquet-id", "banquet", is_active=False)]


def test_ac5_any_other_database_error_is_not_reported_as_a_conflict(monkeypatch):
    fake = _RefusingSupabase([_category("banquet-id", "banquet", is_active=False)], "delete", _db_error("42501"))
    monkeypatch.setattr(service, "supabase", fake)

    with pytest.raises(APIError):
        service.delete_room_layout("banquet-id")


def test_ac5_permanently_deleting_an_unknown_category_is_a_404(api, categories_db):
    assert api("DELETE", "/room-layouts/nope/permanent", ["venue_staff"]).status_code == 404


@pytest.mark.parametrize("role", NON_STAFF_ROLES)
def test_ac5_only_venue_staff_permanently_delete(api, categories_db, role):
    before = _stored(categories_db)

    assert api("DELETE", "/room-layouts/banquet-id/permanent", [role]).status_code == 403
    assert _stored(categories_db) == before


# -- event validation against the managed list -----------------------------------


@pytest.fixture
def managed_layouts(monkeypatch):
    """theatre and u-shape (added by Venue Staff) are active; banquet is soft-deleted."""
    monkeypatch.setattr(event_service, "_room_layouts", lambda: {"theatre": True, "u-shape": True, "banquet": False})


def test_a_layout_venue_staff_added_can_be_chosen(managed_layouts):
    payload = event_service.validate_event_payload({"name": "Talk", "room_layout": "u-shape"}, for_submission=False)

    assert payload["room_layout"] == "u-shape"


def test_a_soft_deleted_layout_cannot_be_chosen(managed_layouts):
    with pytest.raises(ValidationError, match='room layout "banquet" no longer exists'):
        event_service.validate_event_payload({"name": "Talk", "room_layout": "banquet"}, for_submission=False)


def test_a_layout_name_that_no_longer_exists_asks_for_a_refresh(managed_layouts):
    """E.g. permanently deleted after the page loaded."""
    with pytest.raises(ValidationError, match="Please refresh the page and choose a new room layout"):
        event_service.validate_event_payload({"name": "Talk", "room_layout": "stadium"}, for_submission=False)


def test_a_malformed_layout_lists_only_the_active_ones(managed_layouts):
    with pytest.raises(ValidationError, match=r"room_layout must be one of: theatre, u-shape\.$"):
        event_service.validate_event_payload({"name": "Talk", "room_layout": 5}, for_submission=False)


def test_a_session_keeps_its_soft_deleted_layout_when_other_details_change(managed_layouts):
    payload = event_service.validate_event_payload(
        {"name": "Talk", "room_layout": "banquet", "expected_attendance": 20},
        for_submission=False,
        current_room_layout="banquet",
    )

    assert payload["room_layout"] == "banquet"


def test_a_draft_keeps_its_soft_deleted_layout_but_cannot_switch_to_one(managed_layouts):
    kept = event_service._draft_payload({"expected_attendance": 20}, {"room_layout": "banquet"})
    assert kept["room_layout"] == "banquet"

    with pytest.raises(ValidationError, match="no longer exists"):
        event_service._draft_payload({"room_layout": "banquet"}, {"room_layout": "theatre"})


def test_a_draft_cannot_save_an_unknown_layout(managed_layouts):
    """Drafts skip completeness checks, not the layout check -- otherwise the
    database would refuse the unknown name with an unhelpful error."""
    with pytest.raises(ValidationError, match="no longer exists"):
        event_service._draft_payload({"room_layout": "stadium"})


def test_submitting_a_draft_whose_layout_was_soft_deleted_is_refused(managed_layouts, monkeypatch):
    """A request isn't sent for review with a layout no longer offered --
    the organiser picks another first."""
    fake = FakeSupabase()
    monkeypatch.setattr(event_service, "supabase", fake)
    event = SimpleNamespace(
        id="event-1",
        organizer_id="org-1",
        shared_event_id=None,
        status="draft",
        name="Talk",
        description="d",
        purpose="p",
        preferred_start_date="2099-01-01",
        preferred_end_date="2099-01-01",
        preferred_start_time=None,
        preferred_end_time=None,
        expected_attendance=20,
        accessibility_needs=[],
        room_layout="banquet",
        equipment_needed={"equipment": []},
        registration_needs=False,
        special_requests="",
    )

    with pytest.raises(ValidationError, match="no longer exists"):
        event_service.submit_event_request("event-1", event)
    assert fake.calls == []  # nothing changed status


def test_a_change_request_can_leave_a_soft_deleted_layout_alone_but_not_ask_for_one(managed_layouts):
    event = SimpleNamespace(
        id="event-1",
        name="Talk",
        description="d",
        purpose="p",
        preferred_start_date="2099-01-01",
        preferred_end_date="2099-01-01",
        preferred_start_time=None,
        preferred_end_time=None,
        expected_attendance=20,
        accessibility_needs=[],
        room_layout="theatre",
        equipment_needed={"equipment": []},
        registration_needs=False,
        special_requests=None,
    )

    with pytest.raises(ValidationError, match="no longer exists"):
        change_request_service._validated_details(event, {"room_layout": "banquet"})

    event.room_layout = "banquet"
    details = change_request_service._validated_details(event, {"expected_attendance": 30})
    assert details["room_layout"] == "banquet"


# -- a stale form still holding a deleted layout -----------------------------------


@pytest.fixture
def stale_draft(monkeypatch, managed_layouts):
    """A draft whose layout was cleared when "banquet" was soft-deleted (the
    database trigger) -- but the organiser's page was loaded before that and
    still has "banquet" selected."""
    fake = FakeSupabase(
        [
            {
                "id": "draft-1",
                "organizer_id": "user-1",
                "coordinator_id": None,
                "status": "draft",
                "shared_event_id": "group-1",
                "name": "Talk",
                "description": "d",
                "purpose": "p",
                "preferred_start_date": "2099-01-01",
                "preferred_end_date": "2099-01-01",
                "preferred_start_time": None,
                "preferred_end_time": None,
                "expected_attendance": 20,
                "accessibility_needs": [],
                "room_layout": None,
                "equipment_needed": {"equipment": []},
                "registration_needs": False,
                "registration_start_datetime": None,
                "registration_end_datetime": None,
                "special_requests": None,
            }
        ]
    )
    monkeypatch.setattr(event_service, "supabase", fake)
    monkeypatch.setattr(routes_module, "supabase", fake)
    return fake


REFRESH_MESSAGE = 'The room layout "banquet" no longer exists. Please refresh the page and choose a new room layout.'


def test_submitting_a_stale_draft_form_asks_to_refresh_and_choose_again(api, stale_draft):
    """Submit first saves the form (POST /events/<id>/draft); the deleted
    layout is refused there with the refresh message, and nothing is
    written or submitted."""
    body = {"name": "Talk", "sessions": [{"id": "draft-1", "room_layout": "banquet", "expected_attendance": 20}]}

    response = api("POST", "/events/draft-1/draft", ["event_organizer"], body)

    assert response.status_code == 400
    assert response.get_json()["error"]["message"] == REFRESH_MESSAGE
    assert [call["op"] for call in stale_draft.calls] == ["select", "select"]  # load_event + the draft's sessions
    assert stale_draft.get("draft-1")["room_layout"] is None


def test_creating_and_submitting_with_a_stale_layout_asks_to_refresh(api, stale_draft):
    body = {
        "name": "Talk",
        "description": "d",
        "purpose": "p",
        "sessions": [
            {
                "preferred_start_date": "2099-01-01",
                "preferred_end_date": "2099-01-01",
                "expected_attendance": 20,
                "room_layout": "banquet",
                "registration_needs": False,
            }
        ],
    }

    response = api("POST", "/events", ["event_organizer"], body)

    assert response.status_code == 400
    assert response.get_json()["error"]["message"] == REFRESH_MESSAGE
    assert len(stale_draft.rows) == 1  # nothing created
