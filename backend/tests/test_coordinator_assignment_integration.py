"""
Integration tests for app.events.coordinator_service -- converted from
Justin's original print-and-eyeball scripts (backend/test_assignment.py,
backend/test_reassignment.py). Those depended on an external seed
(seed.py/seed.sql) already having run and on running in a specific
order (reassignment only made sense after assignment had succeeded, and
re-running assignment twice required resetting the seed first). These
create their own throwaway coordinators/organiser/events per test and
clean up afterwards, so each test is independent and re-runnable on its
own, in any order, any number of times.

Marked `integration`: every test here does real Supabase reads/writes
against auth.users/profiles/user_roles/events/coordinator_assignment_log.
Skipped automatically (see conftest.py's pytest_collection_modifyitems)
without SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY -- never true in CI.

app/events/coordinator_service.py itself is untouched by this ticket --
these tests exercise its existing, unmodified logic exactly as Justin
wrote it. They don't know or care about app.authz; that policy layer
isn't wired into this module by this ticket (see docs/traceability.md
and the Phase 4 report's note for Justin on reassign_coordinator).
"""

from __future__ import annotations

import uuid

import pytest

from app.events.coordinator_service import assign_initial_coordinator, reassign_coordinator
from app.extensions import supabase

pytestmark = pytest.mark.integration

_PASSWORD = "Password123!-throwaway-test-account"


class _Fixtures:
    """Creates throwaway auth users/profiles/roles/events for one test
    and deletes them afterwards. Events must be deleted BEFORE the users
    they reference -- events.organizer_id/coordinator_id have no ON
    DELETE CASCADE in the migration, only coordinator_assignment_log and
    profiles->auth.users do."""

    def __init__(self):
        self.event_ids: list[str] = []
        self.user_ids: list[str] = []

    def create_user(self, name: str, role: str) -> dict:
        email = f"test-{uuid.uuid4()}@example.com"
        created = supabase.auth.admin.create_user(
            {"email": email, "password": _PASSWORD, "email_confirm": True}
        )
        user_id = created.user.id
        self.user_ids.append(user_id)
        supabase.table("profiles").insert({"id": user_id, "name": name, "email": email}).execute()
        supabase.table("user_roles").insert({"user_id": user_id, "role": role}).execute()
        return {"id": user_id, "name": name, "email": email}

    def create_event(self, **fields) -> str:
        defaults = {
            "name": f"Throwaway Event {uuid.uuid4()}",
            "description": "integration test event -- safe to delete",
            "purpose": "testing",
            "expected_attendance": 10,
        }
        defaults.update(fields)
        result = supabase.table("events").insert(defaults).execute()
        event_id = result.data[0]["id"]
        self.event_ids.append(event_id)
        return event_id

    def cleanup(self) -> None:
        for event_id in self.event_ids:
            supabase.table("events").delete().eq("id", event_id).execute()
        for user_id in self.user_ids:
            supabase.auth.admin.delete_user(user_id)


@pytest.fixture
def fixtures():
    f = _Fixtures()
    yield f
    f.cleanup()


# -- assign_initial_coordinator ---------------------------------------------


def test_assign_initial_coordinator_skips_coordinator_occupied_on_same_date(fixtures):
    """Mirrors the original test_assignment.py's "Product Launch
    Networking Night" case: a coordinator already booked on the target
    date must be skipped even though they'd otherwise be a candidate.

    Asserts the comparative property (the occupied one is never picked),
    not which coordinator IS picked: assign_initial_coordinator's
    candidate pool is every event_coordinator in the database, which on
    a shared project includes Phase 3's seeded coordinators (Alice,
    Brandon, Chloe) alongside this test's own throwaway one. Pinning an
    exact winner would make this test depend on seed data it doesn't own
    and didn't create."""
    busy_coordinator = fixtures.create_user("Busy Coordinator", "event_coordinator")
    organizer = fixtures.create_user("Test Organizer", "event_organizer")

    fixtures.create_event(
        organizer_id=organizer["id"],
        coordinator_id=busy_coordinator["id"],
        status="planning",
        preferred_start_date="2027-03-01",
    )
    event_id = fixtures.create_event(
        organizer_id=organizer["id"],
        coordinator_id=None,
        status="submitted",
        preferred_start_date="2027-03-01",
    )

    chosen = assign_initial_coordinator(event_id)

    assert chosen["id"] != busy_coordinator["id"]


def test_assign_initial_coordinator_prefers_less_loaded_coordinator(fixtures):
    """Mirrors the original test_assignment.py's point about workload-
    based selection: a coordinator carrying more active load must lose
    out to one carrying less, even though both are technically free on
    the target date. Same reasoning as the test above: asserts that the
    busier coordinator loses, not who specifically wins, since the
    shared project's other seeded coordinators are also real candidates
    this test doesn't control."""
    busier_coordinator = fixtures.create_user("Busier Coordinator", "event_coordinator")
    organizer = fixtures.create_user("Test Organizer", "event_organizer")

    # One active event on a DIFFERENT date -- still free for the target
    # date below, but carries more load than a coordinator with none.
    fixtures.create_event(
        organizer_id=organizer["id"],
        coordinator_id=busier_coordinator["id"],
        status="planning",
        preferred_start_date="2027-01-15",
    )
    event_id = fixtures.create_event(
        organizer_id=organizer["id"],
        coordinator_id=None,
        status="submitted",
        preferred_start_date="2027-04-10",
    )

    chosen = assign_initial_coordinator(event_id)

    assert chosen["id"] != busier_coordinator["id"]


# -- reassign_coordinator ----------------------------------------------------


def test_reassign_coordinator_records_audit_log(fixtures):
    """Mirrors the original test_reassignment.py: reassigning moves
    coordinator_id AND leaves an audit trail naming both the previous
    and new coordinator."""
    original_coordinator = fixtures.create_user("Original Coordinator", "event_coordinator")
    new_coordinator = fixtures.create_user("New Coordinator", "event_coordinator")
    organizer = fixtures.create_user("Test Organizer", "event_organizer")

    event_id = fixtures.create_event(
        organizer_id=organizer["id"],
        coordinator_id=original_coordinator["id"],
        status="planning",
        preferred_start_date="2027-06-01",
    )

    result = reassign_coordinator(
        event_id=event_id,
        new_coordinator_id=new_coordinator["id"],
        requested_by=original_coordinator["id"],
        reason="integration test reassignment",
    )

    assert result["id"] == new_coordinator["id"]

    updated_event = (
        supabase.table("events").select("coordinator_id").eq("id", event_id).single().execute()
    )
    assert updated_event.data["coordinator_id"] == new_coordinator["id"]

    log_rows = (
        supabase.table("coordinator_assignment_log")
        .select("previous_coordinator_id, new_coordinator_id, reason")
        .eq("event_id", event_id)
        .execute()
    )
    assert len(log_rows.data) == 1
    assert log_rows.data[0]["previous_coordinator_id"] == original_coordinator["id"]
    assert log_rows.data[0]["new_coordinator_id"] == new_coordinator["id"]


def test_reassign_coordinator_rejects_request_from_non_current_coordinator(fixtures):
    original_coordinator = fixtures.create_user("Original Coordinator", "event_coordinator")
    new_coordinator = fixtures.create_user("New Coordinator", "event_coordinator")
    someone_else = fixtures.create_user("Unrelated Coordinator", "event_coordinator")
    organizer = fixtures.create_user("Test Organizer", "event_organizer")

    event_id = fixtures.create_event(
        organizer_id=organizer["id"],
        coordinator_id=original_coordinator["id"],
        status="planning",
        preferred_start_date="2027-06-15",
    )

    with pytest.raises(ValueError):
        reassign_coordinator(
            event_id=event_id,
            new_coordinator_id=new_coordinator["id"],
            requested_by=someone_else["id"],
        )
