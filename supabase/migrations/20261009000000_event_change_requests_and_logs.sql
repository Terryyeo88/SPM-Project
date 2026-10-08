-- ConnectSphere: event change requests and event logs
-- Migration: event_change_requests_and_logs
--
-- Timestamp: 20261009000000, NOT 20261008000000. It was first written as
-- 20261008000000, which collided with IS-18's
-- 20261008000000_equipment.sql once that merged to main -- different
-- filenames, so git never flagged it, but `supabase db reset` fails on a
-- duplicate schema_migrations version (the same trap as IS-14's rename).
-- Nothing here depends on the equipment tables, so sorting after them is
-- safe. Don't rename this again without re-checking main and open PRs.
-- Scope: IS-21 Request for Event Change -- "As an Event Organiser, I want
-- to request changes to an event, so that the event details can be
-- updated when requirements change."
--
-- Two tables, for two different things:
--
--   event_change_requests  what the organiser ASKED to change, and the
--                          coordinator's review of it. Linked to the whole
--                          request (shared_event_id) AND the session that
--                          needs to change (event_id).
--                          AC: "A submitted change request is recorded for
--                          the relevant event."
--   event_logs             the audit trail: what actually CHANGED on an
--                          event request, who changed it and when -- from an
--                          approved change request or a direct edit. Linked
--                          to the whole request (shared_event_id) only; one
--                          entry per change.
--
-- The requested values live in event_change_requests, never in events,
-- until the assigned coordinator approves -- that is how "the Event
-- Organiser cannot directly overwrite the current confirmed event details"
-- holds.
--
-- SOURCE OF TRUTH: the live database. Both tables were first created from
-- an earlier draft of this file and then adjusted in the dashboard (PKs
-- renamed to event_change_req_id / change_request_id; event_logs' event_id,
-- source and change_request_id link dropped; reviewed_at dropped). This file
-- now creates exactly that shape for a fresh environment, plus two agreed
-- fixes (section 3) that also bring the live database in line:
--   - event_logs.change_request_id -> event_log_id: it is the log entry's
--     own id, not a link to a change request.
--   - event_change_requests.reviewed_at restored, so a rejection records
--     when it was decided.
--
-- Why shared_event_id has no foreign key on either table:
-- events.shared_event_id is not unique (every session of a request carries
-- the same value), so there is nothing to reference -- the same reason
-- events.shared_event_id itself has none (see
-- 20260927000000_reconcile_events_with_live.sql). A legacy event with no
-- shared_event_id is recorded under its own id (a group of one, the
-- convention app.events.event_service already uses).
--
-- Safe to run twice, and safe against live: every statement is guarded,
-- and nothing is dropped.

-- ============================================================
-- 1. Change requests
-- ============================================================

do $$ begin
  create type public.event_change_status as enum ('pending', 'approved', 'rejected');
exception when duplicate_object then null;
end $$;

create table if not exists public.event_change_requests (
  event_change_req_id uuid not null default gen_random_uuid(),

  shared_event_id uuid not null,
  -- The session that needs to change.
  event_id uuid not null,

  -- the organiser's request
  requested_by uuid not null,
  -- {field: new value}, in the event API's field names
  -- (app.events.event_service.EVENT_FIELDS, e.g. "equipment" rather than
  -- the equipment_needed column).
  requested_changes jsonb not null,
  -- {field: value when the change was requested}, so the coordinator
  -- reviews a before/after.
  previous_values jsonb not null,
  reason text null,

  -- the coordinator's review
  status public.event_change_status not null default 'pending'::public.event_change_status,
  reviewed_by uuid null,
  review_comment text null,  -- required by the app for rejections, optional otherwise
  reviewed_at timestamptz null,
  -- On approval: the arrangements already made (venue booking,
  -- registrations, equipment, technical support) the coordinator was shown
  -- and accepted the change would disturb (app.events.change_impact).
  -- NULL when the change touched nothing already arranged.
  acknowledged_impacts jsonb null,

  created_at timestamptz not null default now(),

  constraint event_change_requests_pkey primary key (event_change_req_id),
  constraint event_change_requests_event_id_fkey foreign key (event_id) references public.events (id) on delete cascade,
  constraint event_change_requests_requested_by_fkey foreign key (requested_by) references public.profiles (id),
  constraint event_change_requests_reviewed_by_fkey foreign key (reviewed_by) references public.profiles (id)
);

create index if not exists idx_event_change_requests_shared_event_id
  on public.event_change_requests using btree (shared_event_id);
create index if not exists idx_event_change_requests_event_id
  on public.event_change_requests using btree (event_id);

-- At most one change request awaiting review per session: two pending
-- requests would each be reviewed against details the other is about to
-- change. The app checks first (and says so); this holds under a race.
create unique index if not exists uq_event_change_requests_one_pending_per_event
  on public.event_change_requests using btree (event_id)
  where (status = 'pending'::public.event_change_status);

-- ============================================================
-- 2. Event logs (audit trail)
-- ============================================================

create table if not exists public.event_logs (
  -- The log entry's own id.
  event_log_id uuid not null default gen_random_uuid(),

  shared_event_id uuid not null,

  -- WHAT changed: {field: {"from": old value, "to": new value}}, in the
  -- event API's field names. Only fields whose value actually changed.
  changes jsonb not null,
  -- WHO changed it.
  changed_by uuid null,
  -- WHEN.
  changed_at timestamptz not null default now(),

  constraint event_logs_pkey primary key (event_log_id),
  constraint event_logs_changed_by_fkey foreign key (changed_by) references public.profiles (id),
  constraint event_logs_changes_check check (
    jsonb_typeof(changes) = 'object'::text and changes <> '{}'::jsonb
  )
);

create index if not exists idx_event_logs_shared_event_id
  on public.event_logs using btree (shared_event_id, changed_at);

-- ============================================================
-- 3. Bring an existing (live) database in line
-- ============================================================
-- No-ops on a fresh environment, where section 1/2 already created these
-- shapes.

do $$
begin
  -- event_logs' primary key was created as change_request_id; it is the
  -- log entry's own id, so it's named for that. A rename keeps every value
  -- and the primary key constraint.
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'event_logs' and column_name = 'change_request_id'
  ) and not exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'event_logs' and column_name = 'event_log_id'
  ) then
    alter table public.event_logs rename column change_request_id to event_log_id;
  end if;
end;
$$;

-- When the coordinator approved or rejected the change.
alter table public.event_change_requests add column if not exists reviewed_at timestamptz null;

-- ============================================================
-- 4. Row Level Security
-- ============================================================
-- Same Sprint 1 placeholder stance as the other tables (see
-- 20260911120000_init_users_events.sql section 6): Flask uses the
-- service-role key (which bypasses RLS) and does the real per-role checks
-- in app/authz. event_change_requests is updated on review, so read +
-- write. event_logs is an audit trail, so read + insert only, like
-- event_status_log.
--
-- Each policy is created only if it doesn't exist yet, so a second run
-- changes nothing (Postgres has no "create policy if not exists").

alter table public.event_change_requests enable row level security;
alter table public.event_logs enable row level security;

do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'event_change_requests'
      and policyname = 'authenticated read event_change_requests'
  ) then
    create policy "authenticated read event_change_requests" on public.event_change_requests
      for select using (auth.role() = 'authenticated');
  end if;

  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'event_change_requests'
      and policyname = 'authenticated write event_change_requests'
  ) then
    create policy "authenticated write event_change_requests" on public.event_change_requests
      for all using (auth.role() = 'authenticated') with check (auth.role() = 'authenticated');
  end if;

  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'event_logs'
      and policyname = 'authenticated read event_logs'
  ) then
    create policy "authenticated read event_logs" on public.event_logs
      for select using (auth.role() = 'authenticated');
  end if;

  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'event_logs'
      and policyname = 'authenticated write event_logs'
  ) then
    create policy "authenticated write event_logs" on public.event_logs
      for insert with check (auth.role() = 'authenticated');
  end if;
end;
$$;

-- Rollback intent (no down-migration tooling is wired up yet -- recorded
-- here so a manual rollback is unambiguous if it's ever needed):
--   remove both tables (event_logs first), then the event_change_status type.
