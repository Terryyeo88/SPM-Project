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

# Technical Support Staff (Check Equipment Availability, Nawaz, IS-18):
# the role that checks requests against the equipment inventory.
TECH_STAFF = [
    {"email": "techsupport1@example.com", "name": "Ivan Goh"},
]

# Equipment inventory, unit level (IS-18): one entry per physical item.
# Types match app.events.event_service.EQUIPMENT. PRJ-003 is under
# maintenance on purpose, so the availability check has an out-of-service
# unit to leave out of the count. Same data as supabase/seed.sql.
EQUIPMENT_UNITS = [
    ("projector", "PRJ-001", "available", None),
    ("projector", "PRJ-002", "available", None),
    ("projector", "PRJ-003", "maintenance", "Lamp replacement pending"),
    ("microphone", "MIC-001", "available", None),
    ("microphone", "MIC-002", "available", None),
    ("microphone", "MIC-003", "available", None),
    ("microphone", "MIC-004", "available", None),
    ("screen", "SCR-001", "available", None),
    ("screen", "SCR-002", "available", None),
    ("wifi", "WIF-001", "available", None),
    ("wifi", "WIF-002", "available", None),
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
        "operating_hours_start": "07:00",
        "operating_hours_end": "23:59",
    },
    {
        "name": "Innovation Hub",
        "location": "Tech Wing, Level 1",
        "capacity": 80,
        "facilities": ["projector", "screen", "wifi"],
        "accessibility_features": ["wheelchair_access", "removable_seats"],
        "supported_layouts": ["classroom", "seminar", "boardroom"],
        "status": "available",
        "operating_hours_start": "08:00",
        "operating_hours_end": "20:00",
    },
    {
        "name": "Executive Boardroom",
        "location": "Main Building, Level 5",
        "capacity": 20,
        "facilities": ["screen", "wifi"],
        "accessibility_features": ["wheelchair_access"],
        "supported_layouts": ["boardroom"],
        "status": "occupied",
        "operating_hours_start": "08:00",
        "operating_hours_end": "18:00",
    },
    {
        "name": "Riverside Pavilion",
        "location": "East Campus, Ground Floor",
        "capacity": 150,
        "facilities": ["microphone", "wifi"],
        "accessibility_features": ["wheelchair_access", "lift_access", "extra_legroom_seats"],
        "supported_layouts": ["banquet", "networking", "seminar"],
        "status": "maintenance",
        # No operating-hours restriction seeded for this one on purpose --
        # exercises calendar_service's "both columns NULL -> no
        # restriction" path (see the migration's own comment), not just
        # the common case every other venue here covers.
        "operating_hours_start": None,
        "operating_hours_end": None,
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


def seed_venue_calendar_demo(grand_ballroom_id: str, tentative_event_id: str, requested_by_id: str) -> None:
    """Demo data for View Venue Availability Calendar (Nawaz, Sprint 2,
    IS-11): one block and two bookings against the Grand Ballroom, so the
    calendar has all three non-"available" states to show without
    needing a real booking-approval walkthrough first.

      - A "maintenance" venue_block next month (blocked, with reason).
      - A CONFIRMED venue_bookings row against `tentative_event_id`
        (event status "planning", per Event A in main() below) -- shows
        as "tentatively_held" per calendar_service's derivation.
      - A CONFIRMED venue_bookings row against the registration-demo's
        first (already-confirmed) session -- shows as "confirmed".

    FRESH EVERY RUN, same stance as seed_registration_demo: deletes any
    prior rows for this venue before inserting, so re-running the script
    doesn't pile up duplicate demo bookings/blocks with stale dates.
    """
    supabase.table("venue_blocks").delete().eq("venue_id", grand_ballroom_id).execute()
    supabase.table("venue_bookings").delete().eq("venue_id", grand_ballroom_id).execute()

    today = date.today()
    sgt = timezone(timedelta(hours=8))

    block_start = datetime(today.year, today.month, today.day, 0, 0, tzinfo=sgt) + timedelta(days=20)
    block_end = block_start + timedelta(days=2)
    supabase.table("venue_blocks").insert(
        {
            "venue_id": grand_ballroom_id,
            "reason": "maintenance",
            "note": "Annual deep-clean and AV system check.",
            "block_start": block_start.isoformat(),
            "block_end": block_end.isoformat(),
        }
    ).execute()

    tentative_start = datetime(today.year, today.month, today.day, 9, 0, tzinfo=sgt) + timedelta(days=10)
    supabase.table("venue_bookings").insert(
        {
            "event_id": tentative_event_id,
            "venue_id": grand_ballroom_id,
            "status": "confirmed",
            "requested_by": requested_by_id,
            "setup_minutes": 30,
            "turnaround_minutes": 30,
            "booking_start": tentative_start.isoformat(),
            "booking_end": (tentative_start + timedelta(hours=4)).isoformat(),
        }
    ).execute()

    reg_session = (
        supabase.table("events")
        .select("id, organizer_id, preferred_start_date, preferred_start_time, preferred_end_time")
        .eq("name", REGISTRATION_DEMO_NAME)
        .eq("status", "confirmed")
        .order("preferred_start_date")
        .limit(1)
        .execute()
    )
    if reg_session.data:
        session = reg_session.data[0]
        start = datetime.fromisoformat(f"{session['preferred_start_date']}T{session['preferred_start_time']}").replace(
            tzinfo=sgt
        )
        end = datetime.fromisoformat(f"{session['preferred_start_date']}T{session['preferred_end_time']}").replace(
            tzinfo=sgt
        )
        supabase.table("venue_bookings").insert(
            {
                "event_id": session["id"],
                "venue_id": grand_ballroom_id,
                "status": "confirmed",
                "requested_by": session["organizer_id"],
                "setup_minutes": 30,
                "turnaround_minutes": 30,
                "booking_start": (start - timedelta(minutes=30)).isoformat(),
                "booking_end": (end + timedelta(minutes=30)).isoformat(),
            }
        ).execute()

    print("Venue calendar demo ready: Grand Ballroom has 1 block, 1 tentatively-held booking, 1 confirmed booking.")


def seed_equipment_inventory() -> dict[str, dict]:
    """Equipment types and individual units (IS-18). Idempotent: a type or
    unit that already exists (by name / asset tag) is left alone. Returns
    the types by name so the demo below can reference them."""
    types_by_name = {}
    for type_name in sorted({unit[0] for unit in EQUIPMENT_UNITS}):
        existing = supabase.table("equipment_types").select("*").eq("name", type_name).execute()
        if existing.data:
            types_by_name[type_name] = existing.data[0]
        else:
            types_by_name[type_name] = supabase.table("equipment_types").insert({"name": type_name}).execute().data[0]

    for type_name, asset_tag, status, notes in EQUIPMENT_UNITS:
        existing = supabase.table("equipment").select("id").eq("asset_tag", asset_tag).execute()
        if not existing.data:
            supabase.table("equipment").insert(
                {
                    "equipment_type_id": types_by_name[type_name]["id"],
                    "asset_tag": asset_tag,
                    "status": status,
                    "notes": notes,
                }
            ).execute()
    print(f"Equipment ready: {len(EQUIPMENT_UNITS)} units across {len(types_by_name)} types (PRJ-003 in maintenance).")
    return types_by_name


def seed_equipment_demo(
    types_by_name: dict[str, dict], event_a: dict, event_b: dict, event_c: dict, requested_by_id: str
) -> None:
    """Demo requests for Check Equipment Availability (IS-18), so the check
    has something to show without the unbuilt Record/Accept stories:

      - Event A ("Annual Tech Symposium") holds a CONFIRMED request that
        reserves PRJ-001 and MIC-001/MIC-002 from 10:00-14:00, 14 days out.
      - Event B ("Product Launch Networking Night") has a PENDING request
        for the same day, 09:00-13:00: 2 projectors, 2 microphones,
        1 screen. Against the above: projectors are SHORT (PRJ-003 is in
        maintenance and PRJ-001 is held, leaving 1 of 2), microphones are
        fine (4 - 2 held = 2), the screen is fine -- one flagged line, two
        clear ones.
      - Event C ("Team Building Workshop") holds a CONFIRMED request three
        days later reserving PRJ-002: it shows on PRJ-002's occupancy but
        must NOT reduce Event B's availability (different period).

    FRESH EVERY RUN, same stance as seed_registration_demo and
    seed_venue_calendar_demo: deletes the demo events' prior equipment
    requests (their items and reservations cascade) before inserting.
    Reservations are inserted directly -- the "Accept an equipment request"
    story that would normally create them is not built.
    """
    sgt = timezone(timedelta(hours=8))
    today = date.today()
    day = datetime(today.year, today.month, today.day, tzinfo=sgt) + timedelta(days=14)

    for event in (event_a, event_b, event_c):
        supabase.table("equipment_requests").delete().eq("event_id", event["id"]).execute()

    def unit_ids(*asset_tags):
        rows = supabase.table("equipment").select("id, asset_tag").in_("asset_tag", list(asset_tags)).execute().data
        by_tag = {row["asset_tag"]: row["id"] for row in rows}
        return [by_tag[tag] for tag in asset_tags]

    def create_request(event, status, start, end, lines):
        request = (
            supabase.table("equipment_requests")
            .insert(
                {
                    "event_id": event["id"],
                    "requested_by": requested_by_id,
                    "status": status,
                    "needed_start": start.isoformat(),
                    "needed_end": end.isoformat(),
                }
            )
            .execute()
            .data[0]
        )
        items = {}
        for type_name, quantity, note in lines:
            items[type_name] = (
                supabase.table("equipment_request_items")
                .insert(
                    {
                        "request_id": request["id"],
                        "equipment_type_id": types_by_name[type_name]["id"],
                        "quantity": quantity,
                        "technical_requirements": note,
                    }
                )
                .execute()
                .data[0]
            )
        return request, items

    def reserve(items, type_name, asset_tags, start, end):
        for unit_id in unit_ids(*asset_tags):
            supabase.table("equipment_reservations").insert(
                {
                    "equipment_id": unit_id,
                    "request_item_id": items[type_name]["id"],
                    "reserved_start": start.isoformat(),
                    "reserved_end": end.isoformat(),
                }
            ).execute()

    a_start, a_end = day.replace(hour=10), day.replace(hour=14)
    _, a_items = create_request(
        event_a, "confirmed", a_start, a_end, [("projector", 1, "HDMI and USB-C inputs"), ("microphone", 2, None)]
    )
    reserve(a_items, "projector", ["PRJ-001"], a_start, a_end)
    reserve(a_items, "microphone", ["MIC-001", "MIC-002"], a_start, a_end)

    create_request(
        event_b,
        "pending",
        day.replace(hour=9),
        day.replace(hour=13),
        [
            ("projector", 2, "One for the main stage, one for the side room"),
            ("microphone", 2, None),
            ("screen", 1, "Pull-down, minimum 2.4 m wide"),
        ],
    )

    c_start = (day + timedelta(days=3)).replace(hour=9)
    c_end = c_start.replace(hour=12)
    _, c_items = create_request(event_c, "confirmed", c_start, c_end, [("projector", 1, None)])
    reserve(c_items, "projector", ["PRJ-002"], c_start, c_end)

    print(
        "Equipment demo ready: 1 pending request (short on projectors) for "
        f"'{event_b['name']}', 2 confirmed requests holding PRJ-001, MIC-001/002 and PRJ-002."
    )


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

    for tech in TECH_STAFF:
        uid = get_or_create_user(tech["email"], tech["name"])
        add_role(uid, "technical_support_staff")
        print(f"Tech staff ready:  {tech['name']} <{tech['email']}> -> {uid}")

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

    venues_by_name = {}
    for venue in VENUES:
        v = get_or_create_venue(venue)
        venues_by_name[v["name"]] = v
        print(f"Venue ready: {v['name']} ({v['status']})")

    seed_venue_calendar_demo(
        venues_by_name["Grand Ballroom"]["id"],
        tentative_event_id=event_a["id"],
        requested_by_id=organizer_id,
    )

    equipment_types = seed_equipment_inventory()
    seed_equipment_demo(
        equipment_types,
        event_a=event_a,
        event_b=event_b,
        event_c=event_c,
        requested_by_id=coordinator_ids[0],
    )

    print(
        "\nDone. 3 coordinators, 1 lead, 1 tech staff, 1 organizer, 3 attendees, "
        "4 events, 4 venues, 11 equipment units seeded."
    )


if __name__ == "__main__":
    main()
