-- ConnectSphere: venue bookings
-- Migration: venue_bookings
-- Scope: Venue Booking Request + Venue Booking Approval (Josiah, Sprint 2).
-- Booking Conflict Detection, Venue Availability Calendar, and Venue
-- Becomes Unavailable (blocking) are explicitly NOT built here -- those
-- are separate, unassigned stories. See docs/design-decisions.md for the
-- narrow conflict guard this migration's tables DO support (confirmed-vs-
-- confirmed overlap only, not the full conflict-detection story).
--
-- Originally timestamped 20261004000000 -- renamed after that collided
-- with main's 20261004000000_coordinator_lead_role.sql (same timestamp,
-- different filename, so git never flagged it as a conflict; caught only
-- because `db reset`/`db start` both fail on a duplicate
-- schema_migrations primary key). Terry's IS-16 migration
-- (20261006000000_venue_booking_no_overlap.sql) adds a constraint on
-- public.venue_bookings and depends on this file sorting before it --
-- do not rename this again without checking that ordering still holds.

-- ============================================================
-- 1. Setup/turnaround time -- per venue, not global
-- ============================================================
-- The Venue Booking Request story: "the system will automatically set a
-- configurable setup time (preparation before event) and turnaround time
-- (time afterwards to reset the venue for its next use) to the booked
-- period of a venue." Stored per venue (not an app-wide env var) because
-- different venues plausibly need different buffers (a boardroom resets
-- faster than a banquet hall) -- confirmed against the team's own
-- wireframe, which shows "Standard Turnaround" as a Venue Profile field.

alter table public.venues
  add column if not exists setup_minutes integer not null default 30,
  add column if not exists turnaround_minutes integer not null default 30;

-- ============================================================
-- 2. Venue bookings
-- ============================================================
-- Keyed to events.id (a SESSION row), not shared_event_id (the whole
-- multi-session request) -- room_layout/expected_attendance/
-- accessibility_needs are per-session fields in app.events.event_service
-- (SESSION_FIELDS), so "does this session have a suitable venue" is
-- inherently a per-session question. A multi-session request needing
-- different venues per session submits one booking per session.
--
-- No capacity/layout/accessibility columns here: those "requirements"
-- already live on the event session row and are read via the event_id
-- join (same pattern event_status_log's own join back to events uses in
-- app.events.event_service._attach_rejections) -- duplicating them here
-- would be exactly the kind of untraceable, unreconciled denormalisation
-- 20260927000000_reconcile_events_with_live.sql exists to clean up.

create type public.venue_booking_status as enum ('pending', 'confirmed', 'rejected');

create table if not exists public.venue_bookings (
  id uuid primary key default gen_random_uuid(),

  event_id uuid not null references public.events (id) on delete cascade,
  venue_id uuid not null references public.venues (id),

  status public.venue_booking_status not null default 'pending',
  requested_by uuid not null references public.profiles (id),

  -- Snapshotted from the venue's setup_minutes/turnaround_minutes at
  -- request time, NOT re-read from the venue row later -- so a later
  -- change to a venue's configured buffer never retroactively rewrites
  -- the meaning of an already-decided booking's blocked period. Same
  -- "config read once, at the decision point, then fixed in writing"
  -- principle event_status_log already applies to status decisions.
  setup_minutes integer not null,
  turnaround_minutes integer not null,

  -- The full period the venue is held UNAVAILABLE for, including the
  -- setup/turnaround buffer either side of the session's own
  -- preferred_start/end. This is what Approval AC1 ("the venue is marked
  -- unavailable for that period") and the confirmed-overlap guard in
  -- app.venues.booking_service both read -- not derived live from the
  -- event row on every query, so it stays fixed even if the event's own
  -- timing is later edited (rule_event_edit still permits a coordinator
  -- edit during planning).
  booking_start timestamptz not null,
  booking_end timestamptz not null,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_venue_bookings_event_id on public.venue_bookings (event_id);
create index if not exists idx_venue_bookings_venue_id on public.venue_bookings (venue_id);
create index if not exists idx_venue_bookings_status on public.venue_bookings (status);

drop trigger if exists trg_venue_bookings_updated_at on public.venue_bookings;
create trigger trg_venue_bookings_updated_at
  before update on public.venue_bookings
  for each row execute function public.set_updated_at();

-- ============================================================
-- 3. Venue booking status history
-- ============================================================
-- Mirrors event_status_log's shape exactly (from_status/to_status/
-- changed_by/reason), not coordinator_assignment_log's previous/new-id
-- shape -- a booking approve/reject is a status transition with a
-- reason (same question event_status_log already answers), not a
-- reassignment between two people (the question coordinator_assignment_log
-- answers). Keeping the two review-decision audit trails structurally
-- identical is deliberate.

create table if not exists public.venue_booking_status_log (
  id uuid primary key default gen_random_uuid(),
  booking_id uuid not null references public.venue_bookings (id) on delete cascade,
  from_status public.venue_booking_status,
  to_status public.venue_booking_status not null,
  changed_by uuid references public.profiles (id),
  reason text,  -- required by the app for rejections, optional otherwise
  changed_at timestamptz not null default now()
);

create index if not exists idx_venue_booking_status_log_booking_id
  on public.venue_booking_status_log (booking_id);

-- ============================================================
-- 4. Row Level Security
-- ============================================================
-- Same Sprint-1-placeholder stance as every other table (see
-- 20260911120000_init_users_events.sql section 6): Flask's service-role
-- key does the real per-role check in app/authz; RLS here is
-- defence-in-depth only. venue_bookings is a writable, user-facing
-- resource (coordinators create, venue staff update it), so it gets the
-- same read+write shape as events itself; venue_booking_status_log gets
-- the same read+insert-only shape as event_status_log.

alter table public.venue_bookings enable row level security;

create policy "authenticated read venue_bookings" on public.venue_bookings
  for select using (auth.role() = 'authenticated');

create policy "authenticated write venue_bookings" on public.venue_bookings
  for all using (auth.role() = 'authenticated') with check (auth.role() = 'authenticated');

alter table public.venue_booking_status_log enable row level security;

create policy "authenticated read venue_booking_status_log" on public.venue_booking_status_log
  for select using (auth.role() = 'authenticated');

create policy "authenticated write venue_booking_status_log" on public.venue_booking_status_log
  for insert with check (auth.role() = 'authenticated');

-- Rollback intent (no down-migration tooling is wired up yet -- recorded
-- here so a manual rollback is unambiguous if it's ever needed):
--   drop policy if exists "authenticated write venue_booking_status_log" on public.venue_booking_status_log;
--   drop policy if exists "authenticated read venue_booking_status_log" on public.venue_booking_status_log;
--   drop table if exists public.venue_booking_status_log;
--   drop policy if exists "authenticated write venue_bookings" on public.venue_bookings;
--   drop policy if exists "authenticated read venue_bookings" on public.venue_bookings;
--   drop trigger if exists trg_venue_bookings_updated_at on public.venue_bookings;
--   drop index if exists idx_venue_bookings_status;
--   drop index if exists idx_venue_bookings_venue_id;
--   drop index if exists idx_venue_bookings_event_id;
--   drop table if exists public.venue_bookings;
--   drop type if exists public.venue_booking_status;
--   alter table public.venues drop column if exists turnaround_minutes;
--   alter table public.venues drop column if exists setup_minutes;
