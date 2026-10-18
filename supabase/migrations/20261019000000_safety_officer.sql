-- ConnectSphere: Safety Officer role and safety reviews
-- Migration: safety_officer
-- Scope: Week 7 customer change #6, Operational Feasibility Check --
-- "ConnectSphere has introduced a new internal role, the Safety Officer,
-- who is responsible for reviewing the operational safety of planned
-- events. After the venue and technical arrangements have been confirmed,
-- the Safety Officer must conduct an Operational Safety Check before the
-- event can proceed to preparation. ... The Safety Officer may approve the
-- event, reject the safety arrangement, or request changes."
-- Week 9: "It is similar to Venue and technical approval. The safety
-- officer role will pick up the event request and perform the necessary
-- checks and update the status of approval with a comment. The
-- co-ordinator will decide on the subsequent action."
--
-- Two things:
--   1. app_role gets 'safety_officer' (same pattern as
--      20261004000000_coordinator_lead_role.sql).
--   2. public.safety_reviews: one row per SUBMISSION of one event session
--      for a safety check. Shaped like venue_bookings (request -> pending
--      -> decided, with who/when/why), because Week 9 says the check works
--      the same way. A rejected or changes-requested session goes back to
--      planning and the coordinator submits it again, which is a NEW row --
--      the earlier decision and its comment stay as history (Week 4:
--      "Resubmission counts as new booking for audit").
--
-- Keyed to events.id (a SESSION row), not shared_event_id: each session
-- has its own venue (Week 9: "separate venue requests for each session"),
-- capacity, layout, equipment and status, which is what gets checked.
--
-- The event's own status is still written only by
-- app.events.transitions (planning -> safety_review on submit,
-- safety_review -> planning on reject / request changes, safety_review ->
-- confirmed when the coordinator confirms an approved session). This
-- table records the review itself; it never stands in for event status.

-- ============================================================
-- 1. Role
-- ============================================================

alter type public.app_role add value if not exists 'safety_officer';

-- ============================================================
-- 2. Safety reviews
-- ============================================================

do $$
begin
  if not exists (select 1 from pg_type where typname = 'safety_review_status') then
    create type public.safety_review_status as enum ('pending', 'approved', 'rejected', 'changes_requested');
  end if;
end $$;

create table if not exists public.safety_reviews (
  id uuid primary key default gen_random_uuid(),

  event_id uuid not null references public.events (id) on delete cascade,
  status public.safety_review_status not null default 'pending',

  submitted_by uuid not null references public.profiles (id),
  submitted_at timestamptz not null default now(),

  -- Filled in when the Safety Officer decides. The comment is required by
  -- the app for rejected / changes_requested (it tells the coordinator
  -- what to fix) and optional for approved.
  reviewed_by uuid references public.profiles (id),
  reviewed_at timestamptz,
  comment text,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  constraint safety_reviews_decision_complete check (
    (status = 'pending' and reviewed_by is null and reviewed_at is null)
    or (status <> 'pending' and reviewed_by is not null and reviewed_at is not null)
  )
);

create index if not exists idx_safety_reviews_event_id on public.safety_reviews (event_id);
create index if not exists idx_safety_reviews_status on public.safety_reviews (status);

-- At most one PENDING review per session. Two "Submit for safety check"
-- clicks racing each other can't both create one: the second insert
-- fails here, and app.safety.safety_service turns that into a clear
-- error. Decided reviews are unlimited (the resubmission history).
create unique index if not exists safety_reviews_one_pending_per_event
  on public.safety_reviews (event_id) where status = 'pending';

drop trigger if exists trg_safety_reviews_updated_at on public.safety_reviews;
create trigger trg_safety_reviews_updated_at
  before update on public.safety_reviews
  for each row execute function public.set_updated_at();

-- ============================================================
-- 3. Row Level Security
-- ============================================================
-- Same placeholder stance as every other table (see
-- 20260911120000_init_users_events.sql section 6): Flask's service-role
-- key does the real per-role check in app/authz; RLS here is
-- defence in depth only. Read + write, same shape as venue_bookings.

alter table public.safety_reviews enable row level security;

drop policy if exists "authenticated read safety_reviews" on public.safety_reviews;
create policy "authenticated read safety_reviews" on public.safety_reviews
  for select using (auth.role() = 'authenticated');

drop policy if exists "authenticated write safety_reviews" on public.safety_reviews;
create policy "authenticated write safety_reviews" on public.safety_reviews
  for all using (auth.role() = 'authenticated') with check (auth.role() = 'authenticated');

-- Rollback intent (manual; no down-migration tooling yet):
--   drop policy if exists "authenticated write safety_reviews" on public.safety_reviews;
--   drop policy if exists "authenticated read safety_reviews" on public.safety_reviews;
--   drop trigger if exists trg_safety_reviews_updated_at on public.safety_reviews;
--   drop index if exists safety_reviews_one_pending_per_event;
--   drop index if exists idx_safety_reviews_status;
--   drop index if exists idx_safety_reviews_event_id;
--   drop table if exists public.safety_reviews;
--   drop type if exists public.safety_review_status;
-- The 'safety_officer' app_role value cannot be dropped from the enum;
-- remove the role from users instead:
--   delete from public.user_roles where role = 'safety_officer';
