-- ConnectSphere: equipment inventory, requests and reservations
-- Migration: equipment
-- Scope: Check Equipment Availability (Nawaz, Sprint 2, IS-18). The story's
-- AC needs four things that did not exist anywhere in the schema:
--
--   1. A unit-level equipment inventory. AC: "Track equipment based on
--      unit level (refers to a single, individual piece of equipment)".
--      The story's own Note says aggregate OR unit level is acceptable
--      and the team should propose one; the AC bullet then fixes it as
--      unit level, so that is what this builds. A quantity is therefore
--      never stored -- it is always COUNT(units), so it cannot drift out
--      of step with the units themselves.
--
--   2. Equipment requests an Event Coordinator raises for an event
--      session (AC: "Can select an equipment request and view the required
--      date and time", "Submitted equipment request is viewable later").
--      Row creation belongs to the separate "Record Equipment Request for
--      Event" story; this migration only gives that story somewhere to
--      write, and the availability check something to read.
--
--   3. Reservations of specific units for a period (AC: "subtracts
--      equipment already allocated to other confirmed event requests for
--      the same date and time", and "view when the equipment is occupied
--      along with the event that it is reserved for and its reservation
--      period"). Row creation belongs to the "Accept an equipment request
--      and reserve stock" story, also not built here.
--
--   4. Nothing in events.equipment_needed (jsonb) can serve as 2: it is a
--      free-form {item, quantity} list on the event row with no status, no
--      requester and no technical-requirements text, and the Reservation
--      stories need a request that can be confirmed or rejected on its own.
--      It is left exactly as it is.
--
-- This migration does NOT build creating a request, accepting one, or
-- releasing on cancellation -- see docs/open-questions.md.

-- ============================================================
-- 1. Equipment types
-- ============================================================
-- What a request asks for ("2 projectors"); a unit (section 2) is one
-- physical item OF a type. Rows, not an enum, because the catalogue of
-- kinds of equipment is data the Technical Support Staff will grow, not
-- a closed set the schema should hard-code. The four names the event
-- form already offers (app.events.event_service.EQUIPMENT) are seeded in
-- supabase/seed.sql so the two agree on day one.

create table if not exists public.equipment_types (
  id uuid primary key default gen_random_uuid(),
  name text not null unique,
  created_at timestamptz not null default now()
);

-- ============================================================
-- 2. Equipment units
-- ============================================================
-- One row per physical item. `asset_tag` is the human-readable "equipment
-- ID" the Reservation story's AC refers to ("Specific equipment IDs are
-- listed alongside the quantity"), unique so it can be used to identify a
-- unit unambiguously.
--
-- `status` records whether the unit can be lent out AT ALL, independent
-- of any reservation: occupancy is derived from equipment_reservations,
-- never stored here (same stance as the venue calendar deriving
-- "tentatively held" instead of adding a status). Only 'available' units
-- count toward availability. The three values are our own call -- no AC
-- names an out-of-service state, but a unit under repair being counted as
-- lendable would make the availability check wrong -- flagged in
-- docs/open-questions.md.

create type public.equipment_status as enum ('available', 'maintenance', 'retired');

create table if not exists public.equipment (
  id uuid primary key default gen_random_uuid(),
  equipment_type_id uuid not null references public.equipment_types (id),
  asset_tag text not null unique,
  status public.equipment_status not null default 'available',
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_equipment_type_id on public.equipment (equipment_type_id);

drop trigger if exists trg_equipment_updated_at on public.equipment;
create trigger trg_equipment_updated_at
  before update on public.equipment
  for each row execute function public.set_updated_at();

-- ============================================================
-- 3. Equipment requests
-- ============================================================
-- Keyed to events.id (a SESSION row, not shared_event_id) for the same
-- reason venue_bookings is: date/time are per-session fields, so "what
-- equipment does THIS session need, and when" is a per-session question.
--
-- needed_start/needed_end are snapshotted from the session's preferred
-- date/time at request time, not re-derived from the event row on every
-- read -- the same "fix it in writing at the decision point" principle
-- venue_bookings.booking_start/booking_end already follows, so a later
-- edit to the event's timing cannot silently change what an
-- already-submitted request, or a reservation made from it, meant.
--
-- status mirrors venue_booking_status: pending (just submitted -- the
-- Record Equipment Request AC says a new request is "Pending"), confirmed
-- (accepted by Technical Support Staff, units reserved), rejected.

create type public.equipment_request_status as enum ('pending', 'confirmed', 'rejected');

create table if not exists public.equipment_requests (
  id uuid primary key default gen_random_uuid(),
  event_id uuid not null references public.events (id) on delete cascade,
  requested_by uuid not null references public.profiles (id),
  status public.equipment_request_status not null default 'pending',
  needed_start timestamptz not null,
  needed_end timestamptz not null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint equipment_requests_period_valid check (needed_end > needed_start)
);

create index if not exists idx_equipment_requests_event_id on public.equipment_requests (event_id);
create index if not exists idx_equipment_requests_status on public.equipment_requests (status);

drop trigger if exists trg_equipment_requests_updated_at on public.equipment_requests;
create trigger trg_equipment_requests_updated_at
  before update on public.equipment_requests
  for each row execute function public.set_updated_at();

-- One line per kind of equipment asked for. `quantity` must be positive
-- (Record Equipment Request AC: "System prevents submitting a request if
-- quantity is missing or zero"); the CHECK is the database-level backstop
-- for whatever validation that story adds in the app.
-- `technical_requirements` is the free-text specification/setup-notes field
-- from the same AC.

create table if not exists public.equipment_request_items (
  id uuid primary key default gen_random_uuid(),
  request_id uuid not null references public.equipment_requests (id) on delete cascade,
  equipment_type_id uuid not null references public.equipment_types (id),
  quantity integer not null check (quantity > 0),
  technical_requirements text,
  constraint equipment_request_items_one_per_type unique (request_id, equipment_type_id)
);

create index if not exists idx_equipment_request_items_request_id
  on public.equipment_request_items (request_id);

-- ============================================================
-- 4. Equipment reservations
-- ============================================================
-- One row per UNIT reserved for one request line. A request for 3
-- projectors, once accepted, becomes 3 rows here, each naming a specific
-- unit -- which is exactly what the AC's "when the equipment is occupied
-- along with the event that it is reserved for and its reservation
-- period" and the Reservation story's "specific equipment IDs" both need.
-- Deleting the request (or its line) releases its units by cascade.
--
-- reserved_start/reserved_end are copied from the request's period when
-- the reservation is made, so a unit's occupancy can be answered from
-- this table alone, with no join, and stays fixed if the request row is
-- later touched.
--
-- The exclusion constraint is the database-level guarantee that one
-- physical unit is never reserved for two overlapping periods, whatever
-- the app does -- the same race the IS-16 constraint closes for venues
-- (two Technical Support Staff accepting two overlapping requests at
-- once would otherwise both read "free" and both write). '[)' matches the
-- app's own overlap test (a_start < b_end and b_start < a_end): a unit
-- returned at 14:00 can be reserved from 14:00. btree_gist is already
-- created by 20261006000000_venue_booking_no_overlap.sql; repeated here
-- with `if not exists` so this file does not depend on that one's order.

create extension if not exists btree_gist with schema extensions;

create table if not exists public.equipment_reservations (
  id uuid primary key default gen_random_uuid(),
  equipment_id uuid not null references public.equipment (id),
  request_item_id uuid not null references public.equipment_request_items (id) on delete cascade,
  reserved_start timestamptz not null,
  reserved_end timestamptz not null,
  created_at timestamptz not null default now(),
  constraint equipment_reservations_period_valid check (reserved_end > reserved_start),
  constraint equipment_reservations_no_unit_overlap
    exclude using gist (
      equipment_id with =,
      tstzrange(reserved_start, reserved_end, '[)') with &&
    )
);

create index if not exists idx_equipment_reservations_equipment_id
  on public.equipment_reservations (equipment_id);
create index if not exists idx_equipment_reservations_request_item_id
  on public.equipment_reservations (request_item_id);

-- ============================================================
-- 5. Row Level Security
-- ============================================================
-- Same stance as every other table (see 20260911120000_init_users_
-- events.sql section 6): Flask's service-role key does the real per-role
-- check in app/authz; RLS is defence in depth only. Read-only for
-- authenticated users, with NO write policy -- nothing in this story
-- writes any of these tables, and the stories that will (Record Request,
-- Accept Request) can add their own write policies when they land, the
-- way venue_blocks left its write side to the blocking story.

alter table public.equipment_types enable row level security;
alter table public.equipment enable row level security;
alter table public.equipment_requests enable row level security;
alter table public.equipment_request_items enable row level security;
alter table public.equipment_reservations enable row level security;

create policy "authenticated read equipment_types" on public.equipment_types
  for select using (auth.role() = 'authenticated');
create policy "authenticated read equipment" on public.equipment
  for select using (auth.role() = 'authenticated');
create policy "authenticated read equipment_requests" on public.equipment_requests
  for select using (auth.role() = 'authenticated');
create policy "authenticated read equipment_request_items" on public.equipment_request_items
  for select using (auth.role() = 'authenticated');
create policy "authenticated read equipment_reservations" on public.equipment_reservations
  for select using (auth.role() = 'authenticated');

-- Rollback intent (no down-migration tooling is wired up yet -- recorded
-- here so a manual rollback is unambiguous if it's ever needed):
--   drop table if exists public.equipment_reservations;
--   drop table if exists public.equipment_request_items;
--   drop table if exists public.equipment_requests;
--   drop table if exists public.equipment;
--   drop table if exists public.equipment_types;
--   drop type if exists public.equipment_request_status;
--   drop type if exists public.equipment_status;
