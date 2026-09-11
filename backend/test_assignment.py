"""
Quick manual test for coordinator_assignment.py against the seeded data.

Run from backend/ with your venv active (after running seed.py or
seed.sql at least once):

    python test_assignment.py

Expected behaviour:
  - "Team Building Workshop" (2026-10-05, no conflicts) should succeed
    and pick Brandon or Chloe (Alice already has 1 active event so she's
    not the least-loaded, even though she'd technically be free that day).
  - "Product Launch Networking Night" (2026-11-10, same date Alice is
    already booked on "Annual Tech Symposium") should succeed too, but
    must NOT pick Alice -- that's the conflict check actually being
    exercised, not just the happy path.
"""

from app.extensions import supabase
from app.events.coordinator_service import assign_initial_coordinator, NoCoordinatorAvailableError


def run(event_name: str):
    print(f"\n--- {event_name} ---")
    event = (
        supabase.table("events")
        .select("id, coordinator_id")
        .eq("name", event_name)
        .single()
        .execute()
        .data
    )

    if event["coordinator_id"]:
        print("Already has a coordinator assigned -- skipping (re-run seed.py/seed.sql "
              "to reset, or test against a fresh event).")
        return

    try:
        coordinator = assign_initial_coordinator(event["id"])
        print(f"Assigned: {coordinator['name']} <{coordinator['email']}>")
    except NoCoordinatorAvailableError as e:
        print(f"No coordinator available: {e}")
    except ValueError as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    run("Team Building Workshop")
    run("Product Launch Networking Night")
