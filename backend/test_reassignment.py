"""
Quick manual test for reassign_coordinator(), against the events your
test_assignment.py run already assigned.

Run from backend/ with your venv active, AFTER test_assignment.py has
successfully assigned both seeded events:

    python test_reassignment.py

Expected behaviour: "Team Building Workshop" (currently Chloe, per your
last test_assignment.py run) gets handed to Alice -- who's free that day,
since her only booking is on a different date -- and the audit log shows
both the old and new coordinator for that change.
"""

from supabase_client import supabase
from coordinator_assignment import reassign_coordinator, NoCoordinatorAvailableError


def main():
    event = (
        supabase.table("events")
        .select("id, name, coordinator_id, profiles!events_coordinator_id_fkey(name)")
        .eq("name", "Team Building Workshop")
        .single()
        .execute()
        .data
    )

    if not event["coordinator_id"]:
        print("This event has no coordinator yet -- run test_assignment.py first.")
        return

    current_name = event["profiles"]["name"] if event.get("profiles") else "(unknown)"
    print(f"Currently assigned to: {current_name}")

    alice = (
        supabase.table("profiles")
        .select("id, name")
        .eq("email", "coordinator1@example.com")
        .single()
        .execute()
        .data
    )

    if event["coordinator_id"] == alice["id"]:
        print("Already assigned to Alice -- nothing to reassign for this test run.")
        return

    try:
        new_coordinator = reassign_coordinator(
            event_id=event["id"],
            new_coordinator_id=alice["id"],
            requested_by=event["coordinator_id"],  # simulates the current coordinator making the call
            reason="test reassignment",
        )
        print(f"Reassigned to: {new_coordinator['name']} <{new_coordinator['email']}>")
    except NoCoordinatorAvailableError as e:
        print(f"No coordinator available: {e}")
    except ValueError as e:
        print(f"Error: {e}")

    log_rows = (
        supabase.table("coordinator_assignment_log")
        .select("previous_coordinator_id, new_coordinator_id, reason, assigned_at")
        .eq("event_id", event["id"])
        .order("assigned_at")
        .execute()
        .data
    )
    print("\nAudit log for this event:")
    for row in log_rows:
        print(f"  {row['assigned_at']}: {row['previous_coordinator_id']} -> "
              f"{row['new_coordinator_id']} ({row['reason']})")


if __name__ == "__main__":
    main()
