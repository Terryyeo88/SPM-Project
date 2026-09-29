-- ConnectSphere: event status history
-- Migration: event_status_log
-- Scope: Event Review and Approval -- the coordinator's Approve / Reject
-- decision on an under_review event request.
--
-- Why a log table rather than a `rejection_reason` column on events:
--   - Week 4 clarification: "Rejected or returned requests should retain
--     an appropriate record of the decision" and rejected requests may be
--     resubmitted, so one event can be rejected more than once -- a single
--     column would overwrite the earlier reason.
--   - Auditability requirement (briefing 8f / Week 4): record who changed
--     the status and when. Other status changes (confirm, cancel, ...) can
--     write to this same table as those stories are built.

create table if not exists public.event_status_log (
  id uuid primary key default gen_random_uuid(),
  event_id uuid not null references public.events (id) on delete cascade,
  from_status public.event_status,
  to_status public.event_status not null,
  changed_by uuid references public.profiles (id),
  reason text,  -- required by the app for rejections, optional otherwise
  changed_at timestamptz not null default now()
);

create index if not exists idx_event_status_log_event_id on public.event_status_log (event_id);

-- Same Sprint 1 placeholder RLS stance as the other tables (see
-- 20260911120000_init_users_events.sql section 6): the Flask backend uses
-- the service-role key and does the real per-role checks in app/authz.
alter table public.event_status_log enable row level security;

create policy "authenticated read status log" on public.event_status_log
  for select using (auth.role() = 'authenticated');

create policy "authenticated write status log" on public.event_status_log
  for insert with check (auth.role() = 'authenticated');
