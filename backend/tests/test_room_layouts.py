"""Room layouts managed by Venue Staff: who may read and manage them, the
routes, the service's handling of database refusals, and how event
validation treats active vs soft-deleted layouts.

The database's own rules (permanent delete only once soft-deleted and no
live event uses it, names kept on events, renames reaching events and
venues) are tested against a real database in
test_room_layouts_integration.py.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from postgrest.exceptions import APIError

import app.auth.context as context_module
import app.events.change_request_service as change_request_service
import app.events.event_service as event_service
import app.room_layouts.room_layout_service as service
import app.venues.venue_service as venue_service
from app.authz import actions
from app.authz.policy import can
from app.shared.errors import NotFoundError, ValidationError
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


# -- routes --------------------------------------------------------------------


def _layout(room_layout_id, name, is_active=True):
    return {"room_layout_id": room_layout_id, "name": name, "is_active": is_active}


class _RefusingSupabase(FakeSupabase):
    """FakeSupabase whose `refuse_op` queries raise `error`, the way the real
    database refuses through a constraint or trigger."""

    def __init__(self, rows, refuse_op, error):
        super().__init__()
        self.tables["room_layouts"] = [dict(row) for row in rows]
        self.refuse_op, self.error = refuse_op, error

    def table(self, name):
        query = super().table(name)
        execute = query.execute

        def refusing_execute():
            if query.op == self.refuse_op:
                raise self.error
            return execute()

        query.execute = refusing_execute
        return query


def _db_error(code, message="refused"):
    return APIError({"message": message, "code": code, "hint": None, "details": None})


@pytest.fixture
def layouts_db(monkeypatch):
    fake = FakeSupabase()
    fake.tables["room_layouts"] = [
        _layout("theatre-id", "theatre"),
        _layout("banquet-id", "banquet", is_active=False),
    ]
    monkeypatch.setattr(service, "supabase", fake)
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


def _names(response):
    return [row["name"] for row in response.get_json()]


def test_list_shows_only_active_layouts_by_default(api, layouts_db):
    response = api("GET", "/room-layouts", ["event_organizer"])

    assert response.status_code == 200
    assert _names(response) == ["theatre"]


def test_venue_staff_can_include_soft_deleted_layouts(api, layouts_db):
    response = api("GET", "/room-layouts?include_inactive=true", ["venue_staff"])

    assert response.status_code == 200
    assert _names(response) == ["banquet", "theatre"]


def test_only_venue_staff_may_see_soft_deleted_layouts(api, layouts_db):
    assert api("GET", "/room-layouts?include_inactive=true", ["event_organizer"]).status_code == 403


def test_venue_staff_add_a_layout(api, layouts_db):
    response = api("POST", "/room-layouts", ["venue_staff"], {"name": "  u-shape  "})

    assert response.status_code == 201
    assert response.get_json()["name"] == "u-shape"  # trimmed
    assert "u-shape" in [row["name"] for row in layouts_db.tables["room_layouts"]]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/room-layouts"),
        ("POST", "/room-layouts/theatre-id"),
        ("DELETE", "/room-layouts/theatre-id"),
        ("POST", "/room-layouts/theatre-id/restore"),
        ("DELETE", "/room-layouts/theatre-id/permanent"),
    ],
)
def test_other_roles_cannot_change_layouts(api, layouts_db, method, path):
    before = [dict(row) for row in layouts_db.tables["room_layouts"]]

    response = api(method, path, ["event_organizer", "event_coordinator"], {"name": "u-shape"})

    assert response.status_code == 403
    assert layouts_db.tables["room_layouts"] == before


@pytest.mark.parametrize("body", [{}, {"name": "   "}, {"name": 5}, {"name": "x", "is_active": False}, ["x"]])
def test_adding_a_layout_needs_just_a_name(api, layouts_db, body):
    assert api("POST", "/room-layouts", ["venue_staff"], body).status_code == 400


def test_adding_a_duplicate_name_is_a_409_that_mentions_restoring(api, monkeypatch):
    monkeypatch.setattr(service, "supabase", _RefusingSupabase([], "insert", _db_error("23505")))

    response = api("POST", "/room-layouts", ["venue_staff"], {"name": "Banquet"})

    assert response.status_code == 409
    assert "restore it" in response.get_json()["error"]["message"]


def test_venue_staff_rename_a_layout(api, layouts_db):
    response = api("POST", "/room-layouts/theatre-id", ["venue_staff"], {"name": "theatre style"})

    assert response.status_code == 200
    assert response.get_json()["name"] == "theatre style"


def test_renaming_an_unknown_layout_is_a_404(api, layouts_db):
    assert api("POST", "/room-layouts/nope", ["venue_staff"], {"name": "x"}).status_code == 404


def test_soft_delete_and_restore(api, layouts_db):
    deleted = api("DELETE", "/room-layouts/theatre-id", ["venue_staff"])
    assert deleted.status_code == 200
    assert deleted.get_json()["is_active"] is False

    restored = api("POST", "/room-layouts/theatre-id/restore", ["venue_staff"])
    assert restored.status_code == 200
    assert restored.get_json()["is_active"] is True


def test_permanent_delete_of_a_soft_deleted_layout(api, layouts_db):
    response = api("DELETE", "/room-layouts/banquet-id/permanent", ["venue_staff"])

    assert response.status_code == 204
    assert [row["name"] for row in layouts_db.tables["room_layouts"]] == ["theatre"]


def test_permanent_delete_of_an_active_layout_is_refused(api, layouts_db):
    response = api("DELETE", "/room-layouts/theatre-id/permanent", ["venue_staff"])

    assert response.status_code == 409
    assert "must be soft-deleted" in response.get_json()["error"]["message"]
    assert [call["op"] for call in layouts_db.calls] == ["select"]  # never attempted


def test_permanent_delete_refused_while_live_events_use_it(api, monkeypatch):
    """The database refuses (trigger, 23503) while an event that isn't
    completed or cancelled still uses the layout; its message is passed on."""
    message = 'Room layout "banquet" is still used by 2 event(s) that are not completed or cancelled.'
    fake = _RefusingSupabase([_layout("banquet-id", "banquet", is_active=False)], "delete", _db_error("23503", message))
    monkeypatch.setattr(service, "supabase", fake)

    response = api("DELETE", "/room-layouts/banquet-id/permanent", ["venue_staff"])

    assert response.status_code == 409
    assert response.get_json()["error"]["message"] == message


def test_permanent_delete_of_an_unknown_layout_is_a_404(api, layouts_db):
    assert api("DELETE", "/room-layouts/nope/permanent", ["venue_staff"]).status_code == 404


# -- event validation against the managed list -----------------------------------


@pytest.fixture
def managed_layouts(monkeypatch):
    """theatre and u-shape (added by Venue Staff) are active; banquet is soft-deleted."""
    monkeypatch.setattr(
        event_service, "_room_layouts", lambda: {"theatre": True, "u-shape": True, "banquet": False}
    )


def test_a_layout_venue_staff_added_can_be_chosen(managed_layouts):
    payload = event_service.validate_event_payload({"name": "Talk", "room_layout": "u-shape"}, for_submission=False)

    assert payload["room_layout"] == "u-shape"


def test_a_soft_deleted_layout_cannot_be_chosen(managed_layouts):
    with pytest.raises(ValidationError, match='"banquet" room layout is no longer available'):
        event_service.validate_event_payload({"name": "Talk", "room_layout": "banquet"}, for_submission=False)


def test_an_unknown_layout_lists_only_the_active_ones(managed_layouts):
    with pytest.raises(ValidationError, match=r"room_layout must be one of: theatre, u-shape\.$"):
        event_service.validate_event_payload({"name": "Talk", "room_layout": "stadium"}, for_submission=False)


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

    with pytest.raises(ValidationError, match="no longer available"):
        event_service._draft_payload({"room_layout": "banquet"}, {"room_layout": "theatre"})


def test_a_draft_cannot_save_an_unknown_layout(managed_layouts):
    """Drafts skip completeness checks, not the layout check -- otherwise the
    database would refuse the unknown name with an unhelpful error."""
    with pytest.raises(ValidationError, match="room_layout must be one of"):
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

    with pytest.raises(ValidationError, match="no longer available"):
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

    with pytest.raises(ValidationError, match="no longer available"):
        change_request_service._validated_details(event, {"room_layout": "banquet"})

    event.room_layout = "banquet"
    details = change_request_service._validated_details(event, {"expected_attendance": 30})
    assert details["room_layout"] == "banquet"


# -- venues reference layouts (venue_room_layouts) --------------------------------

THEATRE = "11111111-1111-1111-1111-111111111111"
BANQUET = "22222222-2222-2222-2222-222222222222"
OLD_LAYOUT = "33333333-3333-3333-3333-333333333333"


@pytest.fixture
def venue_db(monkeypatch):
    """Venue v1 supports theatre and a soft-deleted layout; banquet is active
    but not on the venue."""
    fake = FakeSupabase()
    fake.tables["venues"] = [{"id": "v1", "name": "Hall A"}]
    fake.tables["room_layouts"] = [
        _layout(THEATRE, "theatre"),
        _layout(BANQUET, "banquet"),
        _layout(OLD_LAYOUT, "old layout", is_active=False),
    ]
    fake.tables["venue_room_layouts"] = [
        {"venue_id": "v1", "room_layout_id": THEATRE},
        {"venue_id": "v1", "room_layout_id": OLD_LAYOUT},
    ]
    monkeypatch.setattr(venue_service, "supabase", fake)
    return fake


def _venue_layout_ids(fake):
    return sorted(row["room_layout_id"] for row in fake.tables["venue_room_layouts"] if row["venue_id"] == "v1")


def test_a_venue_lists_its_layouts_by_name_and_with_ids(monkeypatch):
    """The join comes back nested; venues are returned with
    supported_layouts (names, what event checks compare) and
    supported_room_layouts (ids, for editing), sorted by name."""
    fake = FakeSupabase()
    fake.tables["venues"] = [
        {
            "id": "v1",
            "name": "Hall A",
            "venue_room_layouts": [
                {"room_layouts": _layout(THEATRE, "theatre")},
                {"room_layouts": _layout(OLD_LAYOUT, "banquet", is_active=False)},
            ],
        }
    ]
    monkeypatch.setattr(venue_service, "supabase", fake)

    [venue] = venue_service.list_venues()

    assert venue["supported_layouts"] == ["banquet", "theatre"]
    assert venue["supported_room_layouts"][0] == {"room_layout_id": OLD_LAYOUT, "name": "banquet", "is_active": False}
    assert "venue_room_layouts" not in venue
    assert venue_service.VENUE_SELECT in [call["columns"] for call in fake.calls]


def test_setting_a_venues_layouts_adds_and_removes_links(venue_db):
    venue_service.set_venue_room_layouts("v1", {"room_layout_ids": [THEATRE, BANQUET]})

    assert _venue_layout_ids(venue_db) == [THEATRE, BANQUET]
    # New links are written before old ones are removed.
    ops = [(call["table"], call["op"]) for call in venue_db.calls]
    assert ops.index(("venue_room_layouts", "insert")) < ops.index(("venue_room_layouts", "delete"))


def test_a_venue_keeps_a_soft_deleted_layout_it_already_lists(venue_db):
    venue_service.set_venue_room_layouts("v1", {"room_layout_ids": [THEATRE, OLD_LAYOUT, BANQUET]})

    assert _venue_layout_ids(venue_db) == [THEATRE, BANQUET, OLD_LAYOUT]


def test_a_soft_deleted_layout_cannot_be_added_to_a_venue(venue_db):
    venue_db.tables["venue_room_layouts"] = []

    with pytest.raises(ValidationError, match="Soft-deleted room layouts can't be added to a venue: old layout"):
        venue_service.set_venue_room_layouts("v1", {"room_layout_ids": [OLD_LAYOUT]})
    assert _venue_layout_ids(venue_db) == []


@pytest.mark.parametrize(
    ("body", "message"),
    [
        (["x"], "must be a JSON object"),
        ({"room_layout_ids": "theatre"}, "must be a list of room layout ids"),
        ({"room_layout_ids": [THEATRE], "name": "x"}, "Unknown fields: name"),
        ({"room_layout_ids": ["not-a-uuid"]}, "Unknown room layout id: not-a-uuid"),
        ({"room_layout_ids": ["44444444-4444-4444-4444-444444444444"]}, "Unknown room layout id"),
    ],
)
def test_bad_venue_layout_lists_are_refused_and_nothing_changes(venue_db, body, message):
    with pytest.raises(ValidationError, match=message):
        venue_service.set_venue_room_layouts("v1", body)
    assert _venue_layout_ids(venue_db) == [THEATRE, OLD_LAYOUT]


def test_setting_layouts_on_an_unknown_venue_is_a_404(venue_db):
    with pytest.raises(NotFoundError):
        venue_service.set_venue_room_layouts("nope", {"room_layout_ids": []})


def test_only_venue_staff_set_a_venues_layouts(api, venue_db):
    body = {"room_layout_ids": [THEATRE]}

    assert api("POST", "/venues/v1/room-layouts", ["venue_staff"], body).status_code == 200
    for role in ("event_coordinator", "event_organizer", "event_coordinator_lead"):
        assert api("POST", "/venues/v1/room-layouts", [role], body).status_code == 403, role
    assert _venue_layout_ids(venue_db) == [THEATRE]
