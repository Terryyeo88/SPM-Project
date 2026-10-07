-- ConnectSphere: venue availability calendar
-- Migration: venue_calendar
-- Scope: View Venue Availability Calendar (Nawaz, Sprint 2, IS-11) --
-- read-only. This migration adds the two pieces of data the story's AC
-- needs that nothing else already provides:
--
--   1. Per-venue operating hours (AC: "periods outside the venue's
--      operating hours are shown as unavailable"). Not present on
--      `venues` anywhere -- 20260923000000_venues.sql never needed it,
--      and venue_bookings.setup_minutes/turnaround_minutes (Josiah) is a
--      different concept (a buffer around a booking, not the venue's
--      daily opening window).
--
--   2. venue_blocks: manual, reason-carrying unavailability periods
--      (AC: "blocked periods show the reason recorded for the block,
--      e.g. maintenance, renovation, internal activity"). The OLD
--      `venues.status = 'maintenance'` flag (Sprint 1) can't serve this:
--      it's a single current-status value with no date range and no
--      reason text, explicitly documented in 20260923000000_venues.sql
--      as a placeholder "until [booking tables] exist" -- they now do,
--      so this table is the real thing that flag was always meant to be
--      superseded by (see that migration's own section 1 comment).
--
-- This migration does NOT build the ability to CREATE a block --
-- "Venue Becomes Unavailable (blocking)" is explicitly its own,
-- unassigned story (see 20261005100000_venue_bookings.sql's and
-- app.venues.booking_service's module docstrings, both of which already
-- name it as out of scope). IS-11 only has to READ blocks and display
-- them; who gets to write one is that other story's call to make. Until
-- it's built, rows here are seed/service-role only, same stance
-- venues.status took for exactly one Sprint.

-- ============================================================
-- 1. Venue operating hours
-- ============================================================
-- Nullable, not defaulted to a guessed 24-hour window: a NULL pair means
-- "no operating-hours restriction recorded for this venue" (every period
-- is within hours), which is a more honest default than inventing a
-- business rule (e.g. 9-to-5) no story specified. Time-of-day only
-- (public.time, not timestamptz) -- the restriction is a daily recurring
-- window ("7:00 AM - 12:00 AM daily", per the team's own wireframe), not
-- tied to a specific date.

alter table public.venues
  add column if not exists operating_hours_start time,
  add column if not exists operating_hours_end time;

alter table public.venues
  add constraint venues_operating_hours_consistent
  check (
    (operating_hours_start is null) = (operating_hours_end is null)
  );

-- ============================================================
-- 2. Venue blocks
-- ============================================================
-- One row per manually-blocked period on a venue. A closed set of
-- reasons (not free text, unlike venue_booking_status_log.reason) --
-- the AC gives an explicit example list ("maintenance, renovation,
-- internal activity") and the team's wireframe's own "Reason" dropdown
-- matches it closely enough that treating it as the intended closed set
-- is a reasonable Sprint 2 call, same spirit as venues.facilities being
-- left open-ended in Sprint 1 only where the story gave no such list.
-- `note` is free text alongside it for anything the fixed reason doesn't
-- capture (the wireframe's own "Optional note (e.g. dates affected)"
-- field).

create type public.venue_block_reason as enum (
  'maintenance',
  'renovation',
  'safety_issue',
  'internal_activity',
  'other'
);

create table if not exists public.venue_blocks (
  id uuid primary key default gen_random_uuid(),

  venue_id uuid not null references public.venues (id) on delete cascade,

  reason public.venue_block_reason not null,
  note text,

  block_start timestamptz not null,
  block_end timestamptz not null,

  created_by uuid references public.profiles (id),
  created_at timestamptz not null default now(),

  constraint venue_blocks_range_valid check (block_end > block_start)
);

create index if not exists idx_venue_blocks_venue_id on public.venue_blocks (venue_id);
create index if not exists idx_venue_blocks_range on public.venue_blocks (block_start, block_end);

-- ============================================================
-- 3. Row Level Security
-- ============================================================
-- Same defence-in-depth stance as every other table here: Flask holds
-- the service-role key and is the real gate (rule_venue_calendar_view in
-- app/authz/rules.py, same event_coordinator/venue_staff pair as
-- rule_venue_view). Read policy mirrors venues' own. No write policy --
-- see this migration's header: creating a block is a separate,
-- unbuilt story, so only the service role (seed.py/seed.sql) writes
-- here for now, same posture venues.status took in Sprint 1 before
-- venue_bookings existed.

alter table public.venue_blocks enable row level security;

create policy "authenticated read venue_blocks" on public.venue_blocks
  for select using (auth.role() = 'authenticated');

-- Rollback intent (no down-migration tooling is wired up yet -- recorded
-- here so a manual rollback is unambiguous if it's ever needed):
--   drop policy if exists "authenticated read venue_blocks" on public.venue_blocks;
--   drop index if exists idx_venue_blocks_range;
--   drop index if exists idx_venue_blocks_venue_id;
--   drop table if exists public.venue_blocks;
--   drop type if exists public.venue_block_reason;
--   alter table public.venues drop constraint if exists venues_operating_hours_consistent;
--   alter table public.venues drop column if exists operating_hours_end;
--   alter table public.venues drop column if exists operating_hours_start;
