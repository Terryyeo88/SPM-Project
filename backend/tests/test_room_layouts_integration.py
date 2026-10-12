"""Live Supabase tests for the room_layouts migration's database rules
(supabase/migrations/20261012000000_room_layouts.sql), through the same
service functions the routes call:

  - an event written with a layout NAME is linked to its row
  - permanent delete only once soft-deleted AND no live event uses it
  - events that used a permanently deleted layout keep its name
  - a rename reaches linked events and venues; a delete leaves venues
  - venues reference layouts through venue_room_layouts
"""

from __future__ import annotations

import uuid

import pytest

from app.extensions import supabase
from app.room_layouts import room_layout_service as service
from app.room_layouts.room_layout_service import RoomLayoutConflictError
from app.shared.errors import ValidationError
from app.venues.venue_service import get_venue, set_venue_room_layouts

pytestmark = pytest.mark.integration

_PASSWORD = "Password123!-throwaway-test-account"


@pytest.fixture
def organizer():
    email = f"layout-org-{uuid.uuid4()}@example.com"
    user_id = supabase.auth.admin.create_user({"email": email, "password": _PASSWORD, "email_confirm": True}).user.id
    supabase.table("profiles").insert({"id": user_id, "name": "Layout Test Organiser", "email": email}).execute()
    yield user_id
    supabase.table("events").delete().eq("organizer_id", user_id).execute()
    supabase.table("profiles").delete().eq("id", user_id).execute()
    supabase.auth.admin.delete_user(user_id)


@pytest.fixture
def layout():
    row = service.create_room_layout({"name": f"test-layout-{uuid.uuid4()}"})
    yield row
    supabase.table("events").update({"room_layout": None}).eq("room_layout_id", row["room_layout_id"]).execute()
    supabase.table("room_layouts").update({"is_active": False}).eq("room_layout_id", row["room_layout_id"]).execute()
    supabase.table("room_layouts").delete().eq("room_layout_id", row["room_layout_id"]).execute()


def _event(organizer_id, layout_name, status="draft"):
    return (
        supabase.table("events")
        .insert({"organizer_id": organizer_id, "name": "Layout test", "status": status, "room_layout": layout_name})
        .execute()
        .data[0]
    )


def _reload(event_id):
    return supabase.table("events").select("*").eq("id", event_id).single().execute().data


def test_an_event_written_with_a_layout_name_is_linked_to_its_row(organizer, layout):
    event = _event(organizer, layout["name"])

    assert event["room_layout_id"] == layout["room_layout_id"]


def test_the_existing_events_were_linked_by_the_migration():
    unlinked = (
        supabase.table("events").select("id").not_.is_("room_layout", "null").is_("room_layout_id", "null").execute()
    )
    # Only events whose layout was permanently deleted may be unlinked, and
    # those must be completed or cancelled.
    for row in unlinked.data or []:
        assert _reload(row["id"])["status"] in ("completed", "cancelled")


def test_an_unknown_layout_name_is_refused_by_the_database(organizer):
    with pytest.raises(Exception, match="Unknown room layout"):
        _event(organizer, f"no-such-layout-{uuid.uuid4()}")


def test_an_active_layout_cannot_be_permanently_deleted(layout):
    with pytest.raises(RoomLayoutConflictError, match="must be soft-deleted"):
        service.delete_room_layout(layout["room_layout_id"])


def test_permanent_delete_waits_until_every_event_using_it_is_completed_or_cancelled(organizer, layout):
    live = _event(organizer, layout["name"], status="planning")
    done = _event(organizer, layout["name"], status="completed")
    service.soft_delete_room_layout(layout["room_layout_id"])

    with pytest.raises(RoomLayoutConflictError, match=r"still used by 1 event\(s\)"):
        service.delete_room_layout(layout["room_layout_id"])

    supabase.table("events").update({"status": "cancelled"}).eq("id", live["id"]).execute()
    service.delete_room_layout(layout["room_layout_id"])

    for event_id in (live["id"], done["id"]):
        row = _reload(event_id)
        assert row["room_layout_id"] is None
        assert row["room_layout"] == layout["name"]  # the name is kept


@pytest.fixture
def venue():
    row = (
        supabase.table("venues")
        .insert({"name": f"Layout venue {uuid.uuid4()}", "location": "Test", "capacity": 10})
        .execute()
        .data[0]
    )
    yield row
    supabase.table("venues").delete().eq("id", row["id"]).execute()  # cascades to venue_room_layouts


def _layout_id(name):
    return supabase.table("room_layouts").select("room_layout_id").eq("name", name).single().execute().data[
        "room_layout_id"
    ]


def test_venue_staff_set_a_venues_layouts(venue, layout):
    theatre = _layout_id("theatre")

    updated = set_venue_room_layouts(venue["id"], {"room_layout_ids": [theatre, layout["room_layout_id"]]})
    assert updated["supported_layouts"] == sorted(["theatre", layout["name"]])

    updated = set_venue_room_layouts(venue["id"], {"room_layout_ids": [layout["room_layout_id"]]})
    assert updated["supported_layouts"] == [layout["name"]]
    assert updated["supported_room_layouts"] == [
        {"room_layout_id": layout["room_layout_id"], "name": layout["name"], "is_active": True}
    ]


def test_a_soft_deleted_layout_stays_on_a_venue_but_cannot_be_added(venue, layout):
    set_venue_room_layouts(venue["id"], {"room_layout_ids": [layout["room_layout_id"]]})
    service.soft_delete_room_layout(layout["room_layout_id"])

    kept = set_venue_room_layouts(venue["id"], {"room_layout_ids": [layout["room_layout_id"], _layout_id("theatre")]})
    [kept_layout] = [row for row in kept["supported_room_layouts"] if row["room_layout_id"] == layout["room_layout_id"]]
    assert kept_layout["is_active"] is False

    set_venue_room_layouts(venue["id"], {"room_layout_ids": []})
    with pytest.raises(ValidationError, match="Soft-deleted room layouts can't be added"):
        set_venue_room_layouts(venue["id"], {"room_layout_ids": [layout["room_layout_id"]]})


def test_a_rename_reaches_linked_events_and_venues(organizer, layout, venue):
    event = _event(organizer, layout["name"])
    set_venue_room_layouts(venue["id"], {"room_layout_ids": [_layout_id("theatre"), layout["room_layout_id"]]})

    new_name = f"renamed-{uuid.uuid4()}"
    service.rename_room_layout(layout["room_layout_id"], {"name": new_name})

    assert _reload(event["id"])["room_layout"] == new_name
    assert get_venue(venue["id"])["supported_layouts"] == sorted(["theatre", new_name])

    supabase.table("events").update({"status": "completed"}).eq("id", event["id"]).execute()
    service.soft_delete_room_layout(layout["room_layout_id"])
    service.delete_room_layout(layout["room_layout_id"])

    assert get_venue(venue["id"])["supported_layouts"] == ["theatre"]  # removed by the cascade


def test_a_rename_reaches_pending_change_requests_but_not_decided_ones(organizer, layout):
    """A pending change request names the layout in JSON; after a rename it
    must ask for the new name, or approving it would fail. A decided one is
    history and keeps the name as it was."""
    event = _event(organizer, "theatre", status="confirmed")

    def change_request(status):
        return (
            supabase.table("event_change_requests")
            .insert({
                "shared_event_id": str(uuid.uuid4()),
                "event_id": event["id"],
                "requested_by": organizer,
                "requested_changes": {"room_layout": layout["name"], "expected_attendance": 50},
                "previous_values": {"room_layout": "theatre", "expected_attendance": 40},
                "status": status,
            })
            .execute()
            .data[0]
        )

    decided = change_request("rejected")
    pending = change_request("pending")

    new_name = f"renamed-{uuid.uuid4()}"
    service.rename_room_layout(layout["room_layout_id"], {"name": new_name})

    def requested(change):
        row = (
            supabase.table("event_change_requests")
            .select("requested_changes")
            .eq("event_change_req_id", change["event_change_req_id"])
            .single()
            .execute()
        )
        return row.data["requested_changes"]

    assert requested(pending) == {"room_layout": new_name, "expected_attendance": 50}
    assert requested(decided)["room_layout"] == layout["name"]


def test_a_name_differing_only_in_case_is_a_duplicate(layout):
    with pytest.raises(RoomLayoutConflictError, match="already exists"):
        service.create_room_layout({"name": layout["name"].upper()})
