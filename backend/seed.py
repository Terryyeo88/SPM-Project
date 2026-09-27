"""
Seed script — creates sample users (3 as Event Coordinators) and sample
events, for local dev / testing the coordinator assignment logic against
real data instead of an empty database.

Run from backend/ with your venv active and .env filled in:
    python seed.py

Safe to re-run: it looks up existing rows by email/name before creating
duplicates, so running it twice won't double up your data.

NOTE: this uses the Supabase Admin API (auth.admin.create_user), which
requires the SERVICE ROLE key — exactly what app/extensions.py already
loads. These are throwaway local-dev accounts with a shared dummy
password; never reuse this pattern for real user signups.
"""

from app.extensions import supabase

SEED_PASSWORD = "Password123!"

COORDINATORS = [
    {"email": "coordinator1@example.com", "name": "Alice Tan"},
    {"email": "coordinator2@example.com", "name": "Brandon Lee"},
    {"email": "coordinator3@example.com", "name": "Chloe Wong"},
]

ORGANIZERS = [
    {"email": "organizer1@example.com", "name": "Derek Ong"},
]

# Venues (View Venue Catalogue, Nawaz, Sprint 1) -- no auth.users involved,
# a venue isn't owned by anyone, so these are plain rows.
VENUES = [
    {
        "name": "Grand Ballroom",
        "location": "Main Building, Level 3",
        "capacity": 300,
        "facilities": ["microphone", "projector", "screen", "wifi"],
        "accessibility_features": ["wheelchair_access", "lift_access"],
        "supported_layouts": ["theatre", "banquet", "networking"],
        "status": "available",
    },
    {
        "name": "Innovation Hub",
        "location": "Tech Wing, Level 1",
        "capacity": 80,
        "facilities": ["projector", "screen", "wifi"],
        "accessibility_features": ["wheelchair_access", "removable_seats"],
        "supported_layouts": ["classroom", "seminar", "boardroom"],
        "status": "available",
    },
    {
        "name": "Executive Boardroom",
        "location": "Main Building, Level 5",
        "capacity": 20,
        "facilities": ["screen", "wifi"],
        "accessibility_features": ["wheelchair_access"],
        "supported_layouts": ["boardroom"],
        "status": "occupied",
    },
    {
        "name": "Riverside Pavilion",
        "location": "East Campus, Ground Floor",
        "capacity": 150,
        "facilities": ["microphone", "wifi"],
        "accessibility_features": ["wheelchair_access", "lift_access", "extra_legroom_seats"],
        "supported_layouts": ["banquet", "networking", "seminar"],
        "status": "maintenance",
    },
]


def get_or_create_user(email: str, name: str) -> str:
    """Return the profile id for this email, creating the auth user +
    profile row if it doesn't exist yet."""
    existing = supabase.table("profiles").select("id").eq("email", email).execute()
    if existing.data:
        return existing.data[0]["id"]

    created = supabase.auth.admin.create_user(
        {
            "email": email,
            "password": SEED_PASSWORD,
            "email_confirm": True,
        }
    )
    user_id = created.user.id

    supabase.table("profiles").insert(
        {"id": user_id, "name": name, "email": email}
    ).execute()

    return user_id


def add_role(user_id: str, role: str) -> None:
    supabase.table("user_roles").upsert(
        {"user_id": user_id, "role": role}
    ).execute()


def get_or_create_event(event: dict) -> dict:
    existing = (
        supabase.table("events")
        .select("*")
        .eq("name", event["name"])
        .execute()
    )
    if existing.data:
        return existing.data[0]

    result = supabase.table("events").insert(event).execute()
    return result.data[0]


def get_or_create_venue(venue: dict) -> dict:
    existing = (
        supabase.table("venues")
        .select("*")
        .eq("name", venue["name"])
        .execute()
    )
    if existing.data:
        return existing.data[0]

    result = supabase.table("venues").insert(venue).execute()
    return result.data[0]


def main():
    coordinator_ids = []
    for c in COORDINATORS:
        uid = get_or_create_user(c["email"], c["name"])
        add_role(uid, "event_coordinator")
        coordinator_ids.append(uid)
        print(f"Coordinator ready: {c['name']} <{c['email']}> -> {uid}")

    organizer_ids = []
    for o in ORGANIZERS:
        uid = get_or_create_user(o["email"], o["name"])
        add_role(uid, "event_organizer")
        organizer_ids.append(uid)
        print(f"Organizer ready:   {o['name']} <{o['email']}> -> {uid}")

    organizer_id = organizer_ids[0]

    # Event A: already assigned to coordinator1, on 2026-11-10.
    # Used to test that the auto-assignment logic correctly skips a
    # coordinator who is already occupied on that date.
    event_a = get_or_create_event(
        {
            "organizer_id": organizer_id,
            "coordinator_id": coordinator_ids[0],
            "name": "Annual Tech Symposium",
            "description": "A symposium on emerging tech trends.",
            "purpose": "Knowledge sharing",
            "status": "planning",
            "preferred_start_date": "2026-11-10",
            "expected_attendance": 200,
            "room_layout": "theatre",
        }
    )
    print(f"Event ready: {event_a['name']} (coordinator already assigned)")

    # Event B: unassigned, SAME date as Event A. A correct assignment
    # algorithm should skip coordinator1 here and pick coordinator2 or 3.
    event_b = get_or_create_event(
        {
            "organizer_id": organizer_id,
            "coordinator_id": None,
            "name": "Product Launch Networking Night",
            "description": "Networking event for a new product line.",
            "purpose": "Marketing",
            "status": "submitted",
            "preferred_start_date": "2026-11-10",
            "expected_attendance": 100,
            "room_layout": "networking",
        }
    )
    print(f"Event ready: {event_b['name']} (needs assignment, same date as A)")

    # Event C: unassigned, different date — the straightforward case.
    event_c = get_or_create_event(
        {
            "organizer_id": organizer_id,
            "coordinator_id": None,
            "name": "Team Building Workshop",
            "description": "Half-day workshop for staff bonding.",
            "purpose": "Team building",
            "status": "submitted",
            "preferred_start_date": "2026-10-05",
            "expected_attendance": 40,
            "room_layout": "classroom",
        }
    )
    print(f"Event ready: {event_c['name']} (needs assignment, open date)")

    for venue in VENUES:
        v = get_or_create_venue(venue)
        print(f"Venue ready: {v['name']} ({v['status']})")

    print("\nDone. 3 coordinators, 1 organizer, 3 events, 4 venues seeded.")


if __name__ == "__main__":
    main()
