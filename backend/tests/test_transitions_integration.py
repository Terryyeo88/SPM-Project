"""Live Supabase integration tests for app.events.transitions -- only the
two properties a unit test structurally cannot prove:

1. The conditional UPDATE is really atomic against real Postgres. The unit
   tests use an in-memory store that honours the contract by construction,
   and can't show that PostgREST + Postgres actually honour it under
   concurrency. Here, several threads start the same transition from the
   same status at the same instant, and exactly one may win.
2. A real event_status_log row is written with the right
   from/to/actor/reason (column names, FK to profiles, enum casts), in
   the same shape as the rows Justin's approve/reject already wrote.

Same reasoning as test_session_activity_integration.py and
test_jwt_integration.py: each caught a real bug the unit tests couldn't.
"""

from __future__ import annotations

import threading
import uuid

import pytest

from app.events.transitions import TransitionConflictError, status_history, transition
from app.extensions import supabase

pytestmark = pytest.mark.integration

_PASSWORD = "Password123!-throwaway-test-account"


def _create_user(roles: list[str]) -> str:
    email = f"transition-test-{uuid.uuid4()}@example.com"
    created = supabase.auth.admin.create_user({"email": email, "password": _PASSWORD, "email_confirm": True})
    user_id = created.user.id
    supabase.table("profiles").insert({"id": user_id, "name": "Transition Test User", "email": email}).execute()
    for role in roles:
        supabase.table("user_roles").insert({"user_id": user_id, "role": role}).execute()
    return user_id


def _delete_user(user_id: str) -> None:
    supabase.table("user_roles").delete().eq("user_id", user_id).execute()
    supabase.table("profiles").delete().eq("id", user_id).execute()
    supabase.auth.admin.delete_user(user_id)


def _insert_event(organizer_id: str, coordinator_id: str, status: str) -> str:
    row = (
        supabase.table("events")
        .insert(
            {
                "name": f"Transition Test Event {uuid.uuid4()}",
                "organizer_id": organizer_id,
                "coordinator_id": coordinator_id,
                "status": status,
            }
        )
        .execute()
        .data[0]
    )
    return row["id"]


@pytest.fixture
def people():
    organizer = _create_user(["event_organizer"])
    coordinator = _create_user(["event_coordinator"])
    event_ids: list[str] = []
    try:
        yield organizer, coordinator, event_ids
    finally:
        # events first: event_status_log cascades from events, but its
        # changed_by FK to profiles does not.
        for event_id in event_ids:
            supabase.table("events").delete().eq("id", event_id).execute()
        _delete_user(organizer)
        _delete_user(coordinator)


def _race(event_id: str, attempts: list[tuple[str, str | None]], coordinator: str, expected_from: str):
    """Fire every attempt at once from its own thread; return per-attempt outcomes."""
    barrier = threading.Barrier(len(attempts))
    outcomes: list = [None] * len(attempts)

    def run(i, to_status, reason):
        barrier.wait()
        try:
            outcomes[i] = transition(event_id, to_status, coordinator, reason=reason, expected_from=expected_from)
        except Exception as exc:  # noqa: BLE001 -- we assert on the type below
            outcomes[i] = exc

    threads = [threading.Thread(target=run, args=(i, t, r)) for i, (t, r) in enumerate(attempts)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return outcomes


def test_concurrent_transitions_from_same_status_exactly_one_wins(people):
    """Two coordinators' requests race from `approved`: one to planning,
    one to cancelled. Exactly one lands; the other gets a conflict; the
    stored status and history reflect only the winner."""
    organizer, coordinator, event_ids = people
    event_id = _insert_event(organizer, coordinator, "approved")
    event_ids.append(event_id)

    outcomes = _race(event_id, [("planning", None), ("cancelled", "venue fell through")], coordinator, "approved")

    winners = [o for o in outcomes if isinstance(o, dict)]
    losers = [o for o in outcomes if isinstance(o, TransitionConflictError)]
    assert len(winners) == 1, outcomes
    assert len(losers) == 1, outcomes

    stored = supabase.table("events").select("status").eq("id", event_id).single().execute().data["status"]
    assert stored == winners[0]["status"]
    history = status_history(event_id)
    assert [(h["from_status"], h["to_status"]) for h in history] == [("approved", stored)]


def test_many_identical_concurrent_transitions_exactly_one_wins(people):
    """Ten simultaneous approved -> planning attempts (a hammered button):
    one success, nine conflicts, one history row."""
    organizer, coordinator, event_ids = people
    event_id = _insert_event(organizer, coordinator, "approved")
    event_ids.append(event_id)

    outcomes = _race(event_id, [("planning", None)] * 10, coordinator, "approved")

    assert sum(isinstance(o, dict) for o in outcomes) == 1, outcomes
    assert sum(isinstance(o, TransitionConflictError) for o in outcomes) == 9, outcomes
    assert len(status_history(event_id)) == 1


def test_history_row_records_from_to_actor_and_reason(people):
    organizer, coordinator, event_ids = people
    event_id = _insert_event(organizer, coordinator, "confirmed")
    event_ids.append(event_id)

    updated = transition(event_id, "cancelled", coordinator, reason="  Keynote withdrew  ", expected_from="confirmed")

    assert updated["status"] == "cancelled"
    rows = supabase.table("event_status_log").select("*").eq("event_id", event_id).execute().data
    assert len(rows) == 1
    row = rows[0]
    assert row["from_status"] == "confirmed"
    assert row["to_status"] == "cancelled"
    assert row["changed_by"] == coordinator
    assert row["reason"] == "Keynote withdrew"
    assert row["changed_at"]
    # Same column set as the rows approve/reject already wrote live.
    assert set(row) == {"id", "event_id", "from_status", "to_status", "changed_by", "reason", "changed_at"}


def test_stale_expected_status_is_refused_against_real_postgres(people):
    """The stale-write regression, end to end. The caller believes the
    event is `submitted`, but it's really `approved`. Nothing is
    overwritten."""
    organizer, coordinator, event_ids = people
    event_id = _insert_event(organizer, coordinator, "approved")
    event_ids.append(event_id)

    with pytest.raises(TransitionConflictError):
        transition(event_id, "under_review", organizer, expected_from="submitted")

    stored = supabase.table("events").select("status").eq("id", event_id).single().execute().data["status"]
    assert stored == "approved"
    assert status_history(event_id) == []
