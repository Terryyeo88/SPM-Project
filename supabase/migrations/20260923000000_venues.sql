-- ConnectSphere: venues table
-- Migration: venues
-- Scope: minimal table needed for View Venue Catalogue (Nawaz, Sprint 1).
-- Venue booking/search/suitability-checking tables are intentionally NOT
-- included here -- those stories (Venue Search and Filtering, Venue
-- Suitability Checking, Venue Booking Request/Approval, Booking Conflict
-- Detection) were explicitly pushed out of Sprint 1 in planning, and this
-- table only needs to support the read-only catalogue view.

-- ============================================================
-- 1. Venue availability status
-- ============================================================
-- ASSUMPTION, flagged in docs/open-questions.md for customer
-- confirmation: the View Venue Catalogue story's acceptance criterion
-- ("the availability of the venue tells the Event Coordinator when the
-- venue is occupied and when it is available") reads like it wants a
-- real occupied/free CALENDAR. That calendar is what the separate Venue
-- Availability Calendar story (Terry) builds, driven by actual bookings
-- -- and the booking tables it would read from (Venue Booking
-- Request/Approval) are explicitly out of scope for Sprint 1. Modelling
-- true time-based occupancy here would require those tables to exist.
-- Until they do, availability is simplified to a single current-status
-- flag per venue, set by whoever manages the catalogue (not derived from
-- any booking data) -- this is a Sprint 1 placeholder, not the intended
-- final behaviour, and should be revisited once the booking tables land.

create type public.venue_status as enum (
  'available',
  'occupied',
  'maintenance'
);

-- ============================================================
-- 2. Venues
-- ============================================================
-- Fields per the View Venue Catalogue acceptance criteria: location,
-- maximum capacity, available facilities, accessibility provisions,
-- supported room layouts, and availability.
--
-- facilities / accessibility_features are plain text[] rather than a
-- fixed enum (unlike events.room_layout / events.equipment_needed, which
-- validate against a closed set in app.events.event_service) -- deciding
-- the canonical list of what a venue's amenities are actually called is
-- a catalogue-management decision outside this story's scope, and
-- constraining it to today's guessed set would make adding a new
-- facility a migration instead of a data entry. supported_layouts DOES
-- reuse the existing public.room_layout enum, since that type already
-- is the closed set both an event's requested layout and a venue's
-- supported layouts must agree on.

create table if not exists public.venues (
  id uuid primary key default gen_random_uuid(),

  name text not null,
  location text not null,
  capacity integer not null check (capacity > 0),

  facilities text[] not null default '{}',
  accessibility_features text[] not null default '{}',
  supported_layouts public.room_layout[] not null default '{}',

  status public.venue_status not null default 'available',

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_venues_status on public.venues (status);

drop trigger if exists trg_venues_updated_at on public.venues;
create trigger trg_venues_updated_at
  before update on public.venues
  for each row execute function public.set_updated_at();

-- ============================================================
-- 3. Row Level Security
-- ============================================================
-- Same Sprint 1 placeholder stance as every other table in this schema
-- (see 20260911120000_init_users_events.sql's own RLS section): enabled
-- now so the table is never accidentally open to the public API, with an
-- intentionally permissive "any authenticated user" read policy. Flask
-- holds the service role key and enforces the real per-role check
-- (rule_venue_list / rule_venue_view in app/authz/rules.py) before a
-- query ever reaches this table -- RLS here is defence-in-depth, not the
-- authoritative check, matching the stance already documented for
-- session_activity. There is no write policy: nothing in Sprint 1 writes
-- to this table from a user-facing request, so only the service role
-- (which bypasses RLS) can write, via seed.py/seed.sql only.

alter table public.venues enable row level security;

create policy "authenticated read venues" on public.venues
  for select using (auth.role() = 'authenticated');

-- Rollback intent (no down-migration tooling is wired up yet -- recorded
-- here so a manual rollback is unambiguous if it's ever needed):
--   drop policy if exists "authenticated read venues" on public.venues;
--   drop trigger if exists trg_venues_updated_at on public.venues;
--   drop index if exists idx_venues_status;
--   drop table if exists public.venues;
--   drop type if exists public.venue_status;
