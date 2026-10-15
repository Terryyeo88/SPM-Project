-- ConnectSphere: significant vs ordinary changes in the event audit trail
-- Migration: event_logs_significance
-- Scope: IS-9 Update Event Information During Planning -- "Changes to
-- date, time, expected attendance, venue requirements, or equipment
-- requirements are recorded as significant; changes to other fields are
-- recorded as ordinary." Two nullable columns on public.event_logs:
--
--   significance          'significant' | 'ordinary', set by
--                         app.events.event_log on every new entry.
--                         NULL on entries written before this migration;
--                         the API works it out from their `changes`.
--   acknowledged_impacts  the arrangements (venue, equipment, technical
--                         support, registration) the coordinator was shown
--                         and accepted before saving an update -- the same
--                         shape as event_change_requests.acknowledged_impacts.
--                         NULL when the update touched nothing arranged.
--
-- Must be applied before the backend that writes `significance` is
-- deployed: PostgREST refuses an insert naming a column that doesn't exist.

alter table public.event_logs
  add column if not exists significance text null,
  add column if not exists acknowledged_impacts jsonb null;

alter table public.event_logs drop constraint if exists event_logs_significance_check;
alter table public.event_logs
  add constraint event_logs_significance_check
  check (significance is null or significance in ('significant', 'ordinary'));

-- Rollback intent (manual):
--   alter table public.event_logs drop constraint if exists event_logs_significance_check;
--   alter table public.event_logs drop column if exists acknowledged_impacts;
--   alter table public.event_logs drop column if exists significance;
