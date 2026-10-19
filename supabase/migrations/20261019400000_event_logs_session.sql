-- ConnectSphere: which session a change history entry is about
-- Migration: event_logs_session
-- Scope: the Change History on an event request names the session each
-- change was made to (or requested for). event_logs was keyed by the whole
-- request only (shared_event_id; its original event_id column was dropped
-- in the dashboard -- see 20261009000000_event_change_requests_and_logs.sql),
-- so a multi-session request's history couldn't say which session changed.
--
-- event_id is the session the change was made on. Nullable:
--   - entries written before this migration have none, except where the
--     request has exactly one session, so there is only one it can be
--     (backfilled below);
--   - ON DELETE SET NULL keeps the entry if a session is ever removed: the
--     audit trail outlives the row it describes.
-- shared_event_id stays the key the history is read by; event_id only
-- labels the entry.

alter table public.event_logs
  add column if not exists event_id uuid null references public.events (id) on delete set null;

create index if not exists idx_event_logs_event_id on public.event_logs (event_id);

-- Backfill the unambiguous entries: a request with a single session (a
-- legacy event is a group of one under its own id).
update public.event_logs as log
set event_id = only_session.id
from (
  select coalesce(shared_event_id, id) as group_id, min(id::text)::uuid as id
  from public.events
  group by coalesce(shared_event_id, id)
  having count(*) = 1
) as only_session
where log.event_id is null
  and log.shared_event_id = only_session.group_id;

-- Rollback intent:
--   drop index if exists idx_event_logs_event_id;
--   alter table public.event_logs drop column if exists event_id;
