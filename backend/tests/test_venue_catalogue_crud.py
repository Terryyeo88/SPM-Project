"""Venue Staff add, edit and delete venues -- IS-61 CRUD in Venue Catalogue.

Story: "As a Venue staff, I want to add, edit and delete venues so that I
can easily manage what venues ConnectSphere currently has."

  AC1  Venue Staff can add a venue.
  AC2  Venue Staff can edit a venue's details.
  AC3  Venue Staff can delete a venue.
  AC4  Once a venue is deleted, ongoing events that booked it lose their
       booking and the coordinator is alerted to book another venue on the
       event details page.

These run against the in-memory FakeSupabase, with the delete_venue()
database function stubbed (_db_delete_venue). What the database itself does
on delete -- the soft delete and releasing bookings in one transaction, and
refusing bookings on a deleted venue -- is tested against a real database in
test_venue_catalogue_crud_integration.py. The coordinator's alert is
frontend (VenueRemovedAlert.test.js, lib/venueBookings.test.js).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from postgrest.exceptions import APIError

import app.auth.context as context_module
import app.safety.safety_service as safety_service
import app.venues.booking_service as booking_service
import app.venues.routes as routes_module
import app.venues.venue_service as service
from app.authz import actions
from app.authz.policy import can
from app.events.transitions import TransitionConflictError
from app.shared.errors import NotFoundError, ValidationError
from app.venues.venue_service import VenueDeletedError, VenuePermanentDeleteError
from tests.factories import make_user
from tests.fake_supabase import FakeSupabase

NON_STAFF_ROLES = [
    "event_organizer",
    "event_coordinator",
    "event_coordinator_lead",
    "technical_support_staff",
    "safety_officer",
    "attendee",
]

_NEW_VENUE = {
    "name": "Harbour Room",
    "location": "West Wing, Level 2",
    "capacity": 60,
    "facilities": ["projector", "wifi"],
    "accessibility_features": ["wheelchair_access"],
    "supported_layouts": ["classroom", "boardroom"],
    "status": "available",
    "setup_minutes": 15,
    "turnaround_minutes": 20,
}


def _venue(**overrides):
    return {
        "id": "venue-1",
        "name": "Grand Ballroom",
        "location": "Main Building, Level 3",
        "capacity": 300,
        "facilities": ["microphone", "wifi"],
        "accessibility_features": ["lift_access"],
        "supported_layouts": ["theatre", "banquet"],
        "status": "available",
        "setup_minutes": 30,
        "turnaround_minutes": 30,
        "operating_hours_start": "07:00:00",
        "operating_hours_end": "23:59:00",
        "deleted_at": None,
        "deleted_by": None,
        **overrides,
    }


@pytest.fixture
def db(monkeypatch):
    """FakeSupabase holding one venue, with the seeded room layouts active
    and "lecture" soft-deleted."""
    fake = FakeSupabase()
    fake.tables["venues"] = [_venue()]
    monkeypatch.setattr(service, "supabase", fake)
    active = ["theatre", "classroom", "boardroom", "seminar", "banquet", "networking"]
    monkeypatch.setattr(service, "list_room_layouts", lambda: [{"name": name} for name in active])
    return fake


def _stored(db, venue_id="venue-1"):
    return next(row for row in db.tables["venues"] if row["id"] == venue_id)


# -- authz ---------------------------------------------------------------------


@pytest.mark.parametrize("action", [actions.VENUE_CREATE, actions.VENUE_EDIT, actions.VENUE_DELETE])
def test_venue_staff_may_add_edit_and_delete_venues(action):
    assert can(make_user(["venue_staff"]), action) is True


@pytest.mark.parametrize("action", [actions.VENUE_CREATE, actions.VENUE_EDIT, actions.VENUE_DELETE])
@pytest.mark.parametrize("role", NON_STAFF_ROLES)
def test_no_other_role_may_add_edit_or_delete_venues(action, role):
    assert can(make_user([role]), action) is False


# -- AC1: add ------------------------------------------------------------------


def test_ac1_venue_staff_add_a_venue_with_every_detail(db):
    created = service.create_venue(dict(_NEW_VENUE))

    assert {key: created[key] for key in _NEW_VENUE} == _NEW_VENUE
    assert created in [dict(row) for row in db.tables["venues"]]


def test_ac1_name_location_capacity_and_one_layout_are_all_that_is_required(db):
    created = service.create_venue(
        {"name": "Annex", "location": "East Campus", "capacity": 10, "supported_layouts": ["theatre"]}
    )

    assert created["facilities"] == []
    assert created["accessibility_features"] == []
    assert created["supported_layouts"] == ["theatre"]
    assert created["status"] == "available"
    assert (created["setup_minutes"], created["turnaround_minutes"]) == (30, 30)


def test_ac1_a_new_venue_has_no_set_operating_hours(db):
    service.create_venue(dict(_NEW_VENUE))

    # Not written, so the columns keep their NULL default ("no set hours").
    [write] = [call for call in db.calls if call["op"] == "insert"]
    assert "operating_hours_start" not in write["payload"]
    assert "operating_hours_end" not in write["payload"]


def test_ac1_a_missing_required_detail_is_refused(db):
    with pytest.raises(ValidationError, match="Missing required venue fields: location, capacity"):
        service.create_venue({"name": "Annex"})
    assert len(db.tables["venues"]) == 1


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"name": "   "}, "Name is required"),
        ({"capacity": 0}, "Maximum capacity must be at least 1"),
        ({"capacity": "lots"}, "Maximum capacity must be a whole number"),
        ({"capacity": True}, "Maximum capacity must be a whole number"),
        ({"facilities": ["jacuzzi"]}, "Unknown facilities: jacuzzi"),
        ({"accessibility_features": ["Wheelchair Access"]}, "Unknown accessibility provisions"),
        ({"supported_layouts": ["amphitheatre"]}, "Unknown room layout: amphitheatre"),
        ({"supported_layouts": []}, "Choose at least one supported room layout"),
        ({"status": "closed"}, "status must be one of"),
        ({"setup_minutes": 4}, "Setup time must be at least 5 minutes"),
        ({"setup_minutes": -5}, "Setup time must be at least 5 minutes"),
        ({"turnaround_minutes": 0}, "Turnaround time must be at least 5 minutes"),
        ({"rating": 5}, "Unknown venue fields: rating"),
        ({"operating_hours_start": "08:00"}, "Unknown venue fields: operating_hours_start"),
    ],
)
def test_ac1_invalid_details_are_refused(db, change, message):
    with pytest.raises(ValidationError, match=message):
        service.create_venue({**_NEW_VENUE, **change})
    assert len(db.tables["venues"]) == 1


def test_ac1_five_minute_buffers_are_accepted(db):
    created = service.create_venue({**_NEW_VENUE, "setup_minutes": 5, "turnaround_minutes": 5})

    assert (created["setup_minutes"], created["turnaround_minutes"]) == (5, 5)


def test_ac1_a_new_venue_cannot_list_a_soft_deleted_layout(db):
    with pytest.raises(ValidationError, match="Unknown room layout: lecture"):
        service.create_venue({**_NEW_VENUE, "supported_layouts": ["lecture"]})


def test_ac1_repeated_choices_are_stored_once(db):
    created = service.create_venue({**_NEW_VENUE, "facilities": ["wifi", "wifi", "projector"]})

    assert created["facilities"] == ["wifi", "projector"]


# -- AC2: edit -----------------------------------------------------------------


def test_ac2_venue_staff_edit_a_venues_details(db):
    edited = service.update_venue("venue-1", {"capacity": 250, "location": "Main Building, Level 4"})

    assert (edited["capacity"], edited["location"]) == (250, "Main Building, Level 4")
    assert _stored(db)["capacity"] == 250


def test_ac2_only_the_fields_sent_are_written(db):
    service.update_venue("venue-1", {"status": "maintenance"})

    [write] = [call for call in db.calls if call["op"] == "update"]
    assert write["payload"] == {"status": "maintenance"}


def test_ac2_an_edit_leaves_existing_operating_hours_alone(db):
    # Set before IS-61 (seed data); the venue calendar still shows them.
    edited = service.update_venue("venue-1", {"capacity": 250})

    assert (edited["operating_hours_start"], edited["operating_hours_end"]) == ("07:00:00", "23:59:00")


def test_ac2_operating_hours_cannot_be_edited(db):
    with pytest.raises(ValidationError, match="Unknown venue fields: operating_hours_end"):
        service.update_venue("venue-1", {"operating_hours_end": "22:00"})


def test_ac2_a_venue_keeps_a_layout_listed_before_it_was_soft_deleted(db):
    _stored(db)["supported_layouts"] = ["theatre", "lecture"]

    edited = service.update_venue("venue-1", {"supported_layouts": ["lecture", "seminar"]})

    assert edited["supported_layouts"] == ["lecture", "seminar"]


def test_ac2_a_soft_deleted_layout_cannot_be_newly_added(db):
    with pytest.raises(ValidationError, match="Unknown room layout: lecture"):
        service.update_venue("venue-1", {"supported_layouts": ["theatre", "lecture"]})


def test_ac2_an_edit_cannot_remove_every_layout(db):
    with pytest.raises(ValidationError, match="Choose at least one supported room layout"):
        service.update_venue("venue-1", {"supported_layouts": []})
    assert not [call for call in db.calls if call["op"] == "update"]


def test_ac2_an_edit_cannot_shorten_a_buffer_below_five_minutes(db):
    with pytest.raises(ValidationError, match="Turnaround time must be at least 5 minutes"):
        service.update_venue("venue-1", {"turnaround_minutes": 4})


def test_ac2_an_empty_edit_is_refused(db):
    with pytest.raises(ValidationError, match="Nothing to update"):
        service.update_venue("venue-1", {})


def test_ac2_an_unknown_venue_is_not_found(db):
    with pytest.raises(NotFoundError):
        service.update_venue("missing", {"capacity": 5})


def test_ac2_a_deleted_venue_cannot_be_edited(db):
    _stored(db)["deleted_at"] = "2026-10-23T10:00:00+00:00"

    with pytest.raises(VenueDeletedError, match="deleted from the catalogue"):
        service.update_venue("venue-1", {"capacity": 5})
    assert not [call for call in db.calls if call["op"] == "update"]


def test_ac2_an_edit_is_conditioned_on_the_venue_not_being_deleted(db):
    service.update_venue("venue-1", {"capacity": 5})

    [write] = [call for call in db.calls if call["op"] == "update"]
    assert ("is", "deleted_at", None) in write["filters"]


def _refused(code, message):
    error = APIError({"message": message, "code": code, "hint": None, "details": None})

    def execute():
        raise error

    return SimpleNamespace(select=lambda *args: SimpleNamespace(execute=execute))


def test_ac2_a_layout_deleted_meanwhile_is_a_400_with_the_databases_message():
    # The database's venues_check_supported_layouts trigger (23503).
    with pytest.raises(ValidationError, match='Unknown room layout "theatre"'):
        service._write(_refused("23503", 'Unknown room layout "theatre".'))


# -- AC3: delete ---------------------------------------------------------------


def _deleted_outcome(released=()):
    return {"outcome": "deleted", "venue": _venue(deleted_at="2026-10-23T10:00:00+00:00"), "released": list(released)}


@pytest.fixture
def deleting(monkeypatch):
    """Stubs the database function and the status/safety follow-ups;
    records every call."""
    calls = SimpleNamespace(rpc=[], transitions=[], withdrawn=[], outcome=_deleted_outcome())

    def fake_db_delete(venue_id, deleted_by):
        calls.rpc.append((venue_id, deleted_by))
        return calls.outcome

    def fake_transition(event_id, to_status, actor, reason=None, expected_from=None):
        calls.transitions.append((event_id, expected_from, to_status, actor, reason))
        return {"id": event_id, "status": to_status}

    monkeypatch.setattr(service, "_db_delete_venue", fake_db_delete)
    monkeypatch.setattr(service, "transition", fake_transition)
    monkeypatch.setattr(service, "withdraw_pending_review", lambda *args: calls.withdrawn.append(args))
    return calls


def test_ac3_venue_staff_delete_a_venue(deleting):
    result = service.delete_venue("venue-1", "staff-1")

    assert deleting.rpc == [("venue-1", "staff-1")]
    assert result["venue"]["deleted_at"]
    assert result["released_bookings"] == []
    assert result["returned_to_planning"] == []


def test_ac3_an_unknown_venue_is_not_found(deleting):
    deleting.outcome = {"outcome": "not_found"}

    with pytest.raises(NotFoundError):
        service.delete_venue("missing", "staff-1")


def test_ac3_deleting_twice_is_refused(deleting):
    deleting.outcome = {"outcome": "already_deleted"}

    with pytest.raises(VenueDeletedError, match="already been deleted"):
        service.delete_venue("venue-1", "staff-1")


def test_ac3_a_deleted_venue_leaves_the_catalogue(db):
    db.tables["venues"].append(_venue(id="venue-2", name="Old Hall", deleted_at="2026-10-23T10:00:00+00:00"))

    assert [venue["id"] for venue in service.list_venues()] == ["venue-1"]


def test_ac3_a_deleted_venue_can_still_be_looked_up_for_old_bookings(db):
    db.tables["venues"].append(_venue(id="venue-2", name="Old Hall", deleted_at="2026-10-23T10:00:00+00:00"))

    assert service.get_venue("venue-2")["deleted_at"]


# -- AC4: ongoing events lose their booking ----------------------------------


def _released(booking_id, event_id, event_status, previous_status="confirmed"):
    return {
        "booking_id": booking_id,
        "event_id": event_id,
        "previous_status": previous_status,
        "event_status": event_status,
    }


def test_ac4_released_bookings_are_reported(deleting):
    deleting.outcome = _deleted_outcome([_released("b-1", "e-1", "planning", "pending")])

    result = service.delete_venue("venue-1", "staff-1")

    assert result["released_bookings"] == [_released("b-1", "e-1", "planning", "pending")]


def test_ac4_a_planning_session_stays_in_planning(deleting):
    deleting.outcome = _deleted_outcome([_released("b-1", "e-1", "planning")])

    result = service.delete_venue("venue-1", "staff-1")

    assert deleting.transitions == []
    assert result["returned_to_planning"] == []


def test_ac4_a_confirmed_session_goes_back_to_planning_so_it_can_be_rebooked(deleting):
    deleting.outcome = _deleted_outcome([_released("b-1", "e-1", "confirmed")])

    result = service.delete_venue("venue-1", "staff-1")

    [(event_id, expected_from, to_status, actor, reason)] = deleting.transitions
    assert (event_id, expected_from, to_status, actor) == ("e-1", "confirmed", "planning", "staff-1")
    assert 'Venue "Grand Ballroom" was deleted' in reason
    assert result["returned_to_planning"] == ["e-1"]
    assert deleting.withdrawn == []


def test_ac4_a_session_under_safety_check_has_its_check_withdrawn_and_goes_back_to_planning(deleting):
    deleting.outcome = _deleted_outcome([_released("b-1", "e-1", "safety_review")])

    result = service.delete_venue("venue-1", "staff-1")

    [(event_id, actor, comment)] = deleting.withdrawn
    assert (event_id, actor) == ("e-1", "staff-1")
    assert 'Venue "Grand Ballroom" was deleted' in comment
    assert [(row[0], row[1], row[2]) for row in deleting.transitions] == [("e-1", "safety_review", "planning")]
    assert result["returned_to_planning"] == ["e-1"]


def test_ac4_a_session_losing_two_bookings_moves_back_once(deleting):
    deleting.outcome = _deleted_outcome(
        [_released("b-1", "e-1", "confirmed"), _released("b-2", "e-1", "confirmed", "pending")]
    )

    service.delete_venue("venue-1", "staff-1")

    assert len(deleting.transitions) == 1


def test_ac4_a_session_that_moved_on_meanwhile_is_left_alone(deleting, monkeypatch):
    deleting.outcome = _deleted_outcome([_released("b-1", "e-1", "confirmed"), _released("b-2", "e-2", "confirmed")])

    def conflicting(event_id, *args, **kwargs):
        if event_id == "e-1":
            raise TransitionConflictError("moved on")
        return {}

    monkeypatch.setattr(service, "transition", conflicting)

    result = service.delete_venue("venue-1", "staff-1")

    assert result["returned_to_planning"] == ["e-2"]


def test_ac4_withdrawing_a_safety_check_closes_only_the_pending_one(monkeypatch):
    fake = FakeSupabase()
    fake.tables["safety_reviews"] = [
        {"id": "r-old", "event_id": "e-1", "status": "approved", "reviewed_by": "officer-1"},
        {"id": "r-new", "event_id": "e-1", "status": "pending", "reviewed_by": None},
        {"id": "r-other", "event_id": "e-2", "status": "pending", "reviewed_by": None},
    ]
    monkeypatch.setattr(safety_service, "supabase", fake)

    withdrawn = safety_service.withdraw_pending_review("e-1", "staff-1", "Venue deleted.")

    assert withdrawn["id"] == "r-new"
    by_id = {row["id"]: row for row in fake.tables["safety_reviews"]}
    assert (by_id["r-new"]["status"], by_id["r-new"]["reviewed_by"]) == ("changes_requested", "staff-1")
    assert by_id["r-new"]["comment"] == "Venue deleted."
    assert by_id["r-new"]["reviewed_at"]
    assert by_id["r-old"]["status"] == "approved"
    assert by_id["r-other"]["status"] == "pending"


def test_ac4_withdrawing_with_nothing_pending_does_nothing(monkeypatch):
    fake = FakeSupabase()
    fake.tables["safety_reviews"] = [{"id": "r-old", "event_id": "e-1", "status": "approved"}]
    monkeypatch.setattr(safety_service, "supabase", fake)

    assert safety_service.withdraw_pending_review("e-1", "staff-1", "Venue deleted.") is None


# -- a deleted venue can't be booked -------------------------------------------


def test_a_deleted_venue_cannot_be_requested(monkeypatch):
    fake = FakeSupabase()
    fake.tables["venues"] = [_venue(deleted_at="2026-10-23T10:00:00+00:00")]
    monkeypatch.setattr(booking_service, "supabase", fake)
    event = SimpleNamespace(id="e-1", preferred_start_date="2026-12-01")

    with pytest.raises(ValidationError, match='Venue "Grand Ballroom" has been deleted'):
        booking_service.create_booking_request(event, "venue-1", "coordinator-1")
    assert fake.tables.get("venue_bookings", []) == []


def test_a_booking_racing_the_delete_gets_the_databases_message(monkeypatch):
    fake = FakeSupabase()
    fake.tables["venues"] = [_venue()]
    monkeypatch.setattr(booking_service, "supabase", fake)
    table = fake.table

    def refusing_table(name):
        query = table(name)
        if name == "venue_bookings":
            query.execute = lambda: (_ for _ in ()).throw(
                APIError(
                    {
                        "message": 'Venue "Grand Ballroom" has been deleted',
                        "code": "23514",
                        "hint": None,
                        "details": None,
                    }
                )
            )
        return query

    monkeypatch.setattr(fake, "table", refusing_table)
    event = SimpleNamespace(id="e-1", preferred_start_date="2026-12-01")

    with pytest.raises(ValidationError, match="has been deleted"):
        booking_service.create_booking_request(event, "venue-1", "coordinator-1")


# -- routes --------------------------------------------------------------------


def _mock_profile(monkeypatch, roles):
    monkeypatch.setattr(
        context_module,
        "_load_profile_with_roles",
        lambda user_id: ("Test User", "test@example.com", frozenset(roles)),
    )
    monkeypatch.setattr(context_module, "_get_last_active", lambda session_id: None)
    monkeypatch.setattr(context_module, "_touch_session_activity", lambda *a, **k: None)


def _forbidden(*args, **kwargs):
    raise AssertionError("should not be called")


def _headers(signing_key):
    return {"Authorization": f"Bearer {signing_key.make_token(sub='staff-1')}"}


def test_route_ac1_venue_staff_add_a_venue(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["venue_staff"])
    seen = []
    monkeypatch.setattr(routes_module, "create_venue", lambda body: seen.append(body) or {"id": "v-new", **body})

    response = client.post("/venues", json={"name": "Annex"}, headers=_headers(signing_key))

    assert response.status_code == 201
    assert response.get_json()["id"] == "v-new"
    assert seen == [{"name": "Annex"}]


def test_route_ac1_a_validation_error_is_a_400(client, signing_key, monkeypatch, db):
    _mock_profile(monkeypatch, ["venue_staff"])

    response = client.post("/venues", json={"name": "Annex"}, headers=_headers(signing_key))

    assert response.status_code == 400
    assert "Missing required venue fields" in response.get_json()["error"]["message"]


def test_route_ac2_venue_staff_edit_a_venue(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["venue_staff"])
    monkeypatch.setattr(routes_module, "update_venue", lambda venue_id, body: {"id": venue_id, **body})

    response = client.post("/venues/venue-1", json={"capacity": 12}, headers=_headers(signing_key))

    assert response.status_code == 200
    assert response.get_json() == {"id": "venue-1", "capacity": 12}


def test_route_ac2_editing_a_deleted_venue_is_a_409(client, signing_key, monkeypatch, db):
    _mock_profile(monkeypatch, ["venue_staff"])
    _stored(db)["deleted_at"] = "2026-10-23T10:00:00+00:00"

    response = client.post("/venues/venue-1", json={"capacity": 12}, headers=_headers(signing_key))

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "venue_deleted"


def test_route_ac3_venue_staff_delete_a_venue_as_themselves(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["venue_staff"])
    seen = []
    monkeypatch.setattr(
        routes_module,
        "delete_venue",
        lambda venue_id, deleted_by: (
            seen.append((venue_id, deleted_by))
            or {"venue": {"id": venue_id}, "released_bookings": [], "returned_to_planning": []}
        ),
    )

    response = client.delete("/venues/venue-1", headers=_headers(signing_key))

    assert response.status_code == 200
    assert seen == [("venue-1", "staff-1")]


@pytest.mark.parametrize("role", NON_STAFF_ROLES)
@pytest.mark.parametrize(
    ("method", "path", "patched"),
    [
        ("post", "/venues", "create_venue"),
        ("post", "/venues/venue-1", "update_venue"),
        ("delete", "/venues/venue-1", "delete_venue"),
        ("get", "/venues/deleted", "list_deleted_venues"),
        ("delete", "/venues/venue-1/permanent", "permanently_delete_venue"),
    ],
)
def test_route_only_venue_staff_add_edit_or_delete(client, signing_key, monkeypatch, role, method, path, patched):
    _mock_profile(monkeypatch, [role])
    monkeypatch.setattr(routes_module, patched, _forbidden)

    response = getattr(client, method)(path, json={"capacity": 1}, headers=_headers(signing_key))

    assert response.status_code == 403


# -- permanent delete (the second step after deleting) -------------------------


def test_permanent_delete_lists_only_deleted_venues(db):
    db.tables["venues"].append(_venue(id="venue-2", name="Old Hall", deleted_at="2026-10-23T10:00:00+00:00"))

    assert [venue["id"] for venue in service.list_deleted_venues()] == ["venue-2"]


def test_permanent_delete_needs_the_venue_deleted_from_the_catalogue_first(db):
    with pytest.raises(VenuePermanentDeleteError, match="must be deleted from the catalogue before"):
        service.permanently_delete_venue("venue-1")
    assert not [call for call in db.calls if call["op"] == "delete"]
    assert len(db.tables["venues"]) == 1


def test_permanent_delete_removes_a_deleted_venue(db):
    _stored(db)["deleted_at"] = "2026-10-23T10:00:00+00:00"

    service.permanently_delete_venue("venue-1")

    [delete] = [call for call in db.calls if call["op"] == "delete"]
    assert ("eq", "id", "venue-1") in delete["filters"]
    assert db.tables["venues"] == []


def test_permanent_delete_of_an_unknown_venue_is_not_found(db):
    with pytest.raises(NotFoundError):
        service.permanently_delete_venue("missing")


def test_permanent_delete_turns_the_databases_refusal_into_a_409(db, monkeypatch):
    _stored(db)["deleted_at"] = "2026-10-23T10:00:00+00:00"
    table = db.table

    def refusing_table(name):
        query = table(name)
        if name == "venues":
            execute = query.execute

            def refuse_delete():
                if query.op == "delete":
                    raise APIError(
                        {
                            "message": 'Venue "Grand Ballroom" still has bookings for ongoing events',
                            "code": "23503",
                            "hint": None,
                            "details": None,
                        }
                    )
                return execute()

            query.execute = refuse_delete
        return query

    monkeypatch.setattr(db, "table", refusing_table)

    with pytest.raises(VenuePermanentDeleteError, match="still has bookings for ongoing events"):
        service.permanently_delete_venue("venue-1")


def test_a_permanently_deleted_venues_bookings_still_show_its_name():
    rows = [
        {"id": "b-1", "venue_id": None, "venue_name": "Old Hall", "venues": None},
        {"id": "b-2", "venue_id": "venue-1", "venue_name": None, "venues": {"name": "Grand Ballroom"}},
    ]

    shown = booking_service.with_venue_names(rows)

    assert [row["venues"]["name"] for row in shown] == ["Old Hall", "Grand Ballroom"]


def test_route_lists_deleted_venues_for_venue_staff(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["venue_staff"])
    monkeypatch.setattr(routes_module, "list_deleted_venues", lambda: [_venue(deleted_at="2026-10-23T10:00:00+00:00")])

    response = client.get("/venues/deleted", headers=_headers(signing_key))

    assert response.status_code == 200
    assert response.get_json()[0]["id"] == "venue-1"


def test_route_permanently_deletes_with_204(client, signing_key, monkeypatch):
    _mock_profile(monkeypatch, ["venue_staff"])
    seen = []
    monkeypatch.setattr(routes_module, "permanently_delete_venue", seen.append)

    response = client.delete("/venues/venue-1/permanent", headers=_headers(signing_key))

    assert response.status_code == 204
    assert seen == ["venue-1"]


def test_route_permanent_delete_of_an_active_venue_is_a_409(client, signing_key, monkeypatch, db):
    _mock_profile(monkeypatch, ["venue_staff"])

    response = client.delete("/venues/venue-1/permanent", headers=_headers(signing_key))

    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "venue_permanent_delete_refused"
