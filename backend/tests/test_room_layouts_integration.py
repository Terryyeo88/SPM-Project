"""Live Supabase tests for room layouts (IS-60 Venue Categories): the
database rules the unit tests' fakes (test_room_layouts.py) can't prove.
Categories are the room_layouts rows; disabling is the soft delete
(is_active = false). See supabase/migrations/20261012000000_room_layouts.sql.

  AC1  a created category is stored active and is offered.
  AC2  an edit keeps the same category, now under the new name, on events.
  AC3  disabling is allowed while ongoing events use the category, and they
       keep it (drafts and rejected sessions have it cleared instead, with
       the cleared name kept in room_layout_removed for the organiser).
  AC4  the database itself refuses permanently deleting an active category,
       even when the backend's own check is bypassed.
  AC5  permanent delete is refused while any event that isn't completed,
       cancelled or rejected uses the category, and allowed once none does;
       completed/cancelled events keep its name, rejected sessions lose it.

Also:
  - an event written with a layout NAME is linked to its row
  - a rename reaches linked events, venues' supported_layouts and pending
    change requests; a permanent delete leaves venues' supported_layouts
  - a venue's supported_layouts may only name layouts that exist
    (supabase/migrations/20261012100000_venue_supported_layouts.sql)

Every test creates its own throwaway organiser, layout and events and
removes them afterwards. Skipped automatically without a local Supabase
(see conftest.py).
"""

from __future__ import annotations

import uuid

import pytest
from postgrest.exceptions import APIError

from app.extensions import supabase
from app.room_layouts import room_layout_service as service
from app.room_layouts.room_layout_service import RoomLayoutConflictError
from app.venues.venue_service import get_venue

pytestmark = pytest.mark.integration

_PASSWORD = "Password123!-throwaway-test-account"

# Not completed, cancelled or rejected (drafts are left out too: disabling
# clears the layout from drafts and rejected sessions).
ONGOING_STATUSES = ["submitted", "under_review", "approved", "planning", "safety_review", "confirmed"]
FINISHED_STATUSES = ["completed", "cancelled"]


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


def _stored(room_layout_id):
    return supabase.table("room_layouts").select("*").eq("room_layout_id", room_layout_id).execute().data


def _raw_delete(room_layout_id):
    """A DELETE straight to the table, skipping the backend's checks."""
    return supabase.table("room_layouts").delete().eq("room_layout_id", room_layout_id).execute()


# -- AC1 --------------------------------------------------------------------------


def test_ac1_a_created_category_is_stored_active_and_offered(layout):
    [stored] = _stored(layout["room_layout_id"])

    assert stored["name"] == layout["name"]
    assert stored["is_active"] is True
    assert layout["name"] in [row["name"] for row in service.list_room_layouts()]


def test_ac1_a_name_differing_only_in_case_is_a_duplicate(layout):
    with pytest.raises(RoomLayoutConflictError, match="already exists"):
        service.create_room_layout({"name": layout["name"].upper()})


# -- AC2 --------------------------------------------------------------------------


def test_ac2_an_edit_renames_the_same_category_on_its_events(organizer, layout):
    event = _event(organizer, layout["name"], status="planning")
    new_name = f"renamed-{uuid.uuid4()}"

    edited = service.rename_room_layout(layout["room_layout_id"], {"name": new_name})

    assert (edited["room_layout_id"], edited["name"]) == (layout["room_layout_id"], new_name)
    reloaded = _reload(event["id"])
    assert (reloaded["room_layout"], reloaded["room_layout_id"]) == (new_name, layout["room_layout_id"])


# -- AC3 --------------------------------------------------------------------------


@pytest.mark.parametrize("status", ONGOING_STATUSES)
def test_ac3_disabling_is_allowed_while_an_ongoing_event_uses_it(organizer, layout, status):
    event = _event(organizer, layout["name"], status=status)

    disabled = service.soft_delete_room_layout(layout["room_layout_id"])

    assert disabled["is_active"] is False
    assert layout["name"] not in [row["name"] for row in service.list_room_layouts()]
    kept = _reload(event["id"])
    assert (kept["room_layout"], kept["room_layout_id"]) == (layout["name"], layout["room_layout_id"])


# -- AC4 --------------------------------------------------------------------------


def test_ac4_the_service_refuses_an_active_category(layout):
    with pytest.raises(RoomLayoutConflictError, match="must be soft-deleted"):
        service.delete_room_layout(layout["room_layout_id"])

    assert _stored(layout["room_layout_id"])


def test_ac4_the_database_refuses_an_active_category_even_bypassing_the_service(layout):
    with pytest.raises(APIError) as refused:
        _raw_delete(layout["room_layout_id"])

    assert refused.value.code == "23514"  # check_violation, from before_room_layout_delete
    assert _stored(layout["room_layout_id"])


# -- AC5 --------------------------------------------------------------------------


@pytest.mark.parametrize("status", ONGOING_STATUSES)
def test_ac5_refused_while_an_ongoing_event_uses_it(organizer, layout, status):
    _event(organizer, layout["name"], status=status)
    service.soft_delete_room_layout(layout["room_layout_id"])

    with pytest.raises(
        RoomLayoutConflictError, match=r"still used by 1 event\(s\) that are not completed, cancelled or rejected"
    ):
        service.delete_room_layout(layout["room_layout_id"])

    assert _stored(layout["room_layout_id"])


def test_ac5_the_database_refuses_it_while_in_use_even_bypassing_the_service(organizer, layout):
    _event(organizer, layout["name"], status="confirmed")
    service.soft_delete_room_layout(layout["room_layout_id"])

    with pytest.raises(APIError) as refused:
        _raw_delete(layout["room_layout_id"])

    assert refused.value.code == "23503"  # foreign_key_violation, from before_room_layout_delete
    assert _stored(layout["room_layout_id"])


@pytest.mark.parametrize("status", FINISHED_STATUSES)
def test_ac5_allowed_once_its_events_are_finished_and_they_keep_its_name(organizer, layout, status):
    event = _event(organizer, layout["name"], status=status)
    service.soft_delete_room_layout(layout["room_layout_id"])

    service.delete_room_layout(layout["room_layout_id"])

    assert _stored(layout["room_layout_id"]) == []
    kept = _reload(event["id"])
    assert (kept["room_layout"], kept["room_layout_id"]) == (layout["name"], None)


def test_ac5_allowed_once_the_last_ongoing_event_finishes(organizer, layout):
    first = _event(organizer, layout["name"], status="planning")
    second = _event(organizer, layout["name"], status="confirmed")
    service.soft_delete_room_layout(layout["room_layout_id"])

    supabase.table("events").update({"status": "completed"}).eq("id", first["id"]).execute()
    with pytest.raises(RoomLayoutConflictError, match=r"still used by 1 event\(s\)"):
        service.delete_room_layout(layout["room_layout_id"])

    supabase.table("events").update({"status": "cancelled"}).eq("id", second["id"]).execute()
    service.delete_room_layout(layout["room_layout_id"])

    assert _stored(layout["room_layout_id"]) == []


def test_ac5_a_draft_that_used_it_does_not_hold_up_the_delete(organizer, layout):
    """Disabling cleared the draft's layout (AC3, see
    test_ac3_disabling_clears_it_from_drafts_and_rejected_sessions_and_says_why), so it no longer counts."""
    _event(organizer, layout["name"], status="draft")
    service.soft_delete_room_layout(layout["room_layout_id"])

    service.delete_room_layout(layout["room_layout_id"])

    assert _stored(layout["room_layout_id"]) == []


def test_ac5_a_rejected_session_does_not_hold_up_the_delete_and_lets_go_of_it(organizer, layout):
    """A rejected session still holding the disabled layout (here written
    straight to the table) doesn't count as ongoing: the delete goes ahead,
    and the session's layout is cleared with its name kept for the notice.
    A completed event keeps the name, as before."""
    service.soft_delete_room_layout(layout["room_layout_id"])
    rejected = _event(organizer, layout["name"], status="rejected")
    completed = _event(organizer, layout["name"], status="completed")

    service.delete_room_layout(layout["room_layout_id"])

    assert _stored(layout["room_layout_id"]) == []
    cleared = _reload(rejected["id"])
    assert (cleared["room_layout"], cleared["room_layout_id"], cleared["room_layout_removed"]) == (
        None,
        None,
        layout["name"],
    )
    kept = _reload(completed["id"])
    assert (kept["room_layout"], kept["room_layout_id"], kept["room_layout_removed"]) == (layout["name"], None, None)


def test_ac5_an_unused_disabled_category_is_deleted(layout):
    service.soft_delete_room_layout(layout["room_layout_id"])

    service.delete_room_layout(layout["room_layout_id"])

    assert _stored(layout["room_layout_id"]) == []


# -- linking, renames and venues ----------------------------------------------


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


@pytest.fixture
def venue(layout):
    """A venue supporting theatre and the test layout."""
    row = (
        supabase.table("venues")
        .insert(
            {
                "name": f"Layout venue {uuid.uuid4()}",
                "location": "Test",
                "capacity": 10,
                "supported_layouts": ["theatre", layout["name"]],
            }
        )
        .execute()
        .data[0]
    )
    yield row
    supabase.table("venues").delete().eq("id", row["id"]).execute()


def test_a_rename_reaches_linked_events_and_venues(organizer, layout, venue):
    event = _event(organizer, layout["name"])

    new_name = f"renamed-{uuid.uuid4()}"
    service.rename_room_layout(layout["room_layout_id"], {"name": new_name})

    assert _reload(event["id"])["room_layout"] == new_name
    assert get_venue(venue["id"])["supported_layouts"] == ["theatre", new_name]

    supabase.table("events").update({"status": "completed"}).eq("id", event["id"]).execute()
    service.soft_delete_room_layout(layout["room_layout_id"])
    service.delete_room_layout(layout["room_layout_id"])

    assert get_venue(venue["id"])["supported_layouts"] == ["theatre"]


def test_a_venue_can_only_list_layouts_that_exist(venue):
    with pytest.raises(Exception, match="Unknown room layout"):
        supabase.table("venues").update({"supported_layouts": ["theatre", f"no-such-layout-{uuid.uuid4()}"]}).eq(
            "id", venue["id"]
        ).execute()


def test_a_rename_reaches_pending_change_requests_but_not_decided_ones(organizer, layout):
    """A pending change request names the layout in JSON; after a rename it
    must ask for the new name, or approving it would fail. A decided one is
    history and keeps the name as it was."""
    event = _event(organizer, "theatre", status="confirmed")

    def change_request(status):
        return (
            supabase.table("event_change_requests")
            .insert(
                {
                    "shared_event_id": str(uuid.uuid4()),
                    "event_id": event["id"],
                    "requested_by": organizer,
                    "requested_changes": {"room_layout": layout["name"], "expected_attendance": 50},
                    "previous_values": {"room_layout": "theatre", "expected_attendance": 40},
                    "status": status,
                }
            )
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


def test_ac3_disabling_clears_it_from_drafts_and_rejected_sessions_and_says_why(organizer, layout):
    """Drafts and rejected sessions using the layout lose it (name and id),
    so the organiser picks one still offered; room_layout_removed keeps the
    name so their form can say why it's empty. Other submitted events keep
    it. Restoring doesn't put it back."""
    draft = _event(organizer, layout["name"], status="draft")
    rejected = _event(organizer, layout["name"], status="rejected")
    other_draft = _event(organizer, "theatre", status="draft")
    submitted = _event(organizer, layout["name"], status="submitted")

    service.soft_delete_room_layout(layout["room_layout_id"])

    for event in (draft, rejected):
        cleared = _reload(event["id"])
        assert (cleared["room_layout"], cleared["room_layout_id"], cleared["room_layout_removed"]) == (
            None,
            None,
            layout["name"],
        )
    untouched = _reload(other_draft["id"])
    assert (untouched["room_layout"], untouched["room_layout_removed"]) == ("theatre", None)
    kept = _reload(submitted["id"])
    assert (kept["room_layout"], kept["room_layout_id"], kept["room_layout_removed"]) == (
        layout["name"],
        layout["room_layout_id"],
        None,
    )

    service.restore_room_layout(layout["room_layout_id"])
    assert _reload(draft["id"])["room_layout"] is None
    assert _reload(rejected["id"])["room_layout"] is None


def test_ac3_a_session_rejected_while_its_category_is_disabled_lets_go_of_it(organizer, layout):
    """It kept the layout while under review; once it's rejected (back with
    the organiser), the disabled layout is cleared as it would have been
    had the session already been rejected when the layout was disabled."""
    event = _event(organizer, layout["name"], status="under_review")
    service.soft_delete_room_layout(layout["room_layout_id"])
    assert _reload(event["id"])["room_layout"] == layout["name"]

    supabase.table("events").update({"status": "rejected"}).eq("id", event["id"]).execute()

    cleared = _reload(event["id"])
    assert (cleared["room_layout"], cleared["room_layout_id"], cleared["room_layout_removed"]) == (
        None,
        None,
        layout["name"],
    )


def test_a_session_rejected_with_an_active_layout_keeps_it(organizer, layout):
    event = _event(organizer, layout["name"], status="under_review")

    supabase.table("events").update({"status": "rejected"}).eq("id", event["id"]).execute()

    kept = _reload(event["id"])
    assert (kept["room_layout"], kept["room_layout_removed"]) == (layout["name"], None)


def test_choosing_a_layout_again_clears_the_removed_notice(organizer, layout):
    draft = _event(organizer, layout["name"], status="draft")
    service.soft_delete_room_layout(layout["room_layout_id"])
    assert _reload(draft["id"])["room_layout_removed"] == layout["name"]

    supabase.table("events").update({"expected_attendance": 30}).eq("id", draft["id"]).execute()
    assert _reload(draft["id"])["room_layout_removed"] == layout["name"]  # other edits keep it

    supabase.table("events").update({"room_layout": "theatre"}).eq("id", draft["id"]).execute()

    chosen = _reload(draft["id"])
    assert (chosen["room_layout"], chosen["room_layout_removed"]) == ("theatre", None)
