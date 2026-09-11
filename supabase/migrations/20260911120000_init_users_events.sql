-- ConnectSphere: baseline schema for users/roles and events
-- Migration: init_users_events
-- Scope: minimal tables needed to unblock Coordinator Assignment (Justin, Sprint 1)
-- and give the rest of the team something to build on. Venue/equipment/booking/
-- notification/registration tables are intentionally NOT included here — those
-- belong to their respective feature owners and can be added in later migrations.

-- ============================================================
-- 1. Roles
-- ============================================================
-- Matches the roles named in the user stories doc: Event Organizer,
-- Event Coordinator, Venue Staff, Technical Support Staff, Attendee.
-- Clarification confirmed a single account can hold multiple roles,
-- so roles live in their own join table rather than a single column.

create type public.app_role as enum (
  'event_organizer',
  'event_coordinator',
  'venue_staff',
  'technical_support_staff',
  'attendee'
);

-- ============================================================
-- 2. Users
-- ============================================================
-- Supabase Auth already provides auth.users (handles login/credentials —
-- that's Josiah's User Authorisation & Authentication story). This table
-- extends it with the profile fields the rest of the app needs, and is
-- what other tables (events, etc.) should reference via foreign key —
-- never reference auth.users directly from app tables.

create table if not exists public.profiles (
  id uuid primary key references auth.users (id) on delete cascade,
  name text not null,
  email text not null unique,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.user_roles (
  user_id uuid not null references public.profiles (id) on delete cascade,
  role public.app_role not null,
  primary key (user_id, role)
);

-- Convenience view: coordinators only, used by the assignment logic to
-- pick a candidate. Recreate/replace freely as the assignment algorithm
-- evolves (e.g. once workload/availability columns are added).
create or replace view public.coordinators as
  select p.id, p.name, p.email
  from public.profiles p
  join public.user_roles ur on ur.user_id = p.id
  where ur.role = 'event_coordinator';

-- ============================================================
-- 3. Events
-- ============================================================
-- Statuses per the Event Status Management story + Week2 clarification:
-- draft -> submitted -> under_review -> approved -> planning -> confirmed
-- -> completed, with cancelled / rejected as terminal off-ramps.

create type public.event_status as enum (
  'draft',
  'submitted',
  'under_review',
  'approved',
  'planning',
  'confirmed',
  'completed',
  'cancelled',
  'rejected'
);

create type public.room_layout as enum (
  'theatre',
  'classroom',
  'boardroom',
  'seminar',
  'banquet',
  'networking'
);

create table if not exists public.events (
  id uuid primary key default gen_random_uuid(),

  -- ownership
  organizer_id uuid not null references public.profiles (id),
  coordinator_id uuid references public.profiles (id),  -- null until auto-assigned

  -- core request fields (Event Request Creation story)
  name text not null,
  description text,
  purpose text,
  status public.event_status not null default 'draft',

  preferred_date date,
  preferred_start_time time,
  preferred_end_time time,
  expected_attendance integer,

  accessibility_needs text,
  room_layout public.room_layout,
  registration_needs text,
  special_requests text,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_events_coordinator_id on public.events (coordinator_id);
create index if not exists idx_events_status on public.events (status);

-- ============================================================
-- 4. Coordinator assignment history
-- ============================================================
-- Backs both Coordinator Assignment stories: gives you an audit trail for
-- "who was assigned, when, and who reassigned it" (also satisfies the
-- general auditability requirement raised in the Week4 clarifications).

create table if not exists public.coordinator_assignment_log (
  id uuid primary key default gen_random_uuid(),
  event_id uuid not null references public.events (id) on delete cascade,
  previous_coordinator_id uuid references public.profiles (id),
  new_coordinator_id uuid not null references public.profiles (id),
  assigned_at timestamptz not null default now(),
  reason text  -- optional free-text, e.g. reassignment reason
);

-- ============================================================
-- 5. updated_at trigger (keeps events.updated_at honest)
-- ============================================================
create or replace function public.set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

drop trigger if exists trg_events_updated_at on public.events;
create trigger trg_events_updated_at
  before update on public.events
  for each row execute function public.set_updated_at();

-- ============================================================
-- 6. Row Level Security
-- ============================================================
-- Enabled now so the tables are never accidentally open to the public API.
-- Policies below are intentionally permissive ("any authenticated user")
-- as a Sprint 1 placeholder — tighten these once the auth/roles story
-- defines real per-role access rules (e.g. coordinators only editing
-- their own assigned events).

alter table public.profiles enable row level security;
alter table public.user_roles enable row level security;
alter table public.events enable row level security;
alter table public.coordinator_assignment_log enable row level security;

create policy "authenticated read profiles" on public.profiles
  for select using (auth.role() = 'authenticated');

create policy "authenticated read roles" on public.user_roles
  for select using (auth.role() = 'authenticated');

create policy "authenticated read events" on public.events
  for select using (auth.role() = 'authenticated');

create policy "authenticated write events" on public.events
  for all using (auth.role() = 'authenticated') with check (auth.role() = 'authenticated');

create policy "authenticated read assignment log" on public.coordinator_assignment_log
  for select using (auth.role() = 'authenticated');

create policy "authenticated write assignment log" on public.coordinator_assignment_log
  for insert with check (auth.role() = 'authenticated');
