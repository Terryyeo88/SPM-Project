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

import uuid
from datetime import UTC, date, datetime, timedelta, timezone

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

# Event Coordinator Lead (Week 7 change #5): assigns submitted requests
# from the unassigned queue to coordinators.
LEADS = [
    {"email": "lead1@example.com", "name": "Grace Lim"},
]

# Attendees (Attendee Registration, Justin): register for the demo
# sessions below. Three, so with a capacity of 2 the third is waitlisted.
ATTENDEES = [
    {"email": "attendee1@example.com", "name": "Ethan Koh"},
    {"email": "attendee2@example.com", "name": "Fiona Ng"},
    {"email": "attendee3@example.com", "name": "Gavin Tan"},
]

REGISTRATION_DEMO_NAME = "Registration Demo: Community Workshop"
OLD_REGISTRATION_DEMO_NAME = "Registration Demo: Tech Talk Series"

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


def seed_registration_demo(organizer_id: str, coordinator_id: str) -> None:
    """A CONFIRMED request with two sessions, so registration can be tested
    before venue/equipment work exists to confirm an event the normal way.
    Same data as the matching block in supabase/seed.sql. Both sessions hold
    2 people (expected_attendance), so the third attendee is waitlisted:

      14:00 session -- registration already open
      10:00 session -- registration opens 2 hours after this runs

    FRESH EVERY RUN: the demo request (and its registrations, by cascade) is
    deleted and recreated, dates relative to now. Also removes the older
    "Registration Demo: Tech Talk Series". Inserted directly as confirmed --
    a seed shortcut, no status history.
    """
    sgt = timezone(timedelta(hours=8))
    now = datetime.now(UTC)
    today = date.today()

    def end_of(day: date) -> str:
        return datetime(day.year, day.month, day.day, 23, 59, tzinfo=sgt).isoformat()

    for old_name in (OLD_REGISTRATION_DEMO_NAME, REGISTRATION_DEMO_NAME):
        supabase.table("events").delete().eq("name", old_name).execute()

    shared_event_id = str(uuid.uuid4())
    sessions = [
        {"start_in": 30, "start": "14:00", "end": "16:00", "opens": now - timedelta(days=1)},
        {"start_in": 37, "start": "10:00", "end": "12:00", "opens": now + timedelta(hours=2)},
    ]
    supabase.table("events").insert([
        {
            "organizer_id": organizer_id,
            "coordinator_id": coordinator_id,
            "shared_event_id": shared_event_id,
            "name": REGISTRATION_DEMO_NAME,
            "description": "A hands-on community workshop in two sessions. Open to the public.",
            "purpose": "Community outreach",
            "status": "confirmed",
            "preferred_start_date": (today + timedelta(days=s["start_in"])).isoformat(),
            "preferred_end_date": (today + timedelta(days=s["start_in"])).isoformat(),
            "preferred_start_time": s["start"],
            "preferred_end_time": s["end"],
            "expected_attendance": 2,
            "room_layout": "classroom",
            "accessibility_needs": [],
            "equipment_needed": {"equipment": []},
            "registration_needs": True,
            "registration_start_datetime": s["opens"].isoformat(),
            "registration_end_datetime": end_of(today + timedelta(days=s["start_in"] - 1)),
            "special_requests": "",
        }
        for s in sessions
    ]).execute()
    print(f"Event ready: {REGISTRATION_DEMO_NAME} (confirmed, 2 fresh sessions for registration testing)")


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

    for lead in LEADS:
        uid = get_or_create_user(lead["email"], lead["name"])
        add_role(uid, "event_coordinator_lead")
        print(f"Lead ready:        {lead['name']} <{lead['email']}> -> {uid}")

    for attendee in ATTENDEES:
        uid = get_or_create_user(attendee["email"], attendee["name"])
        add_role(uid, "attendee")
        print(f"Attendee ready:    {attendee['name']} <{attendee['email']}> -> {uid}")

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

    seed_registration_demo(organizer_id, coordinator_ids[1])

    for venue in VENUES:
        v = get_or_create_venue(venue)
        print(f"Venue ready: {v['name']} ({v['status']})")

    print("\nDone. 3 coordinators, 1 lead, 1 organizer, 3 attendees, 4 events, 4 venues seeded.")


if __name__ == "__main__":
    main()
