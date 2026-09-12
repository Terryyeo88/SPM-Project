-- ConnectSphere: session activity tracking, for server-side idle timeout
-- Migration: session_activity
-- Scope: adds ONE new table needed by IS-1 (User Authorisation and
-- Authentication, Terry, Sprint 1) to enforce "idle session timeout" --
-- does not touch or alter 20260911120000_init_users_events.sql.
--
-- Design decision behind this table (full write-up in
-- docs/design-decisions.md): idle timeout is enforced server-side, keyed
-- by the Supabase access token's own `session_id` claim -- a UUID
-- present on every Supabase-issued JWT, correlating 1:1 with a row in
-- Supabase's own auth.sessions table. We do NOT reference auth.sessions
-- directly, matching the convention the init migration already follows
-- for auth.users -> public.profiles (app tables reference
-- public.profiles, never auth.* directly). This table exists purely to
-- record "when did Flask last see an authenticated request carrying
-- this session_id" -- auth.sessions doesn't track that granularity; it
-- only updates on refresh-token rotation, not on every API call.

create table if not exists public.session_activity (
  session_id uuid primary key,
  user_id uuid not null references public.profiles (id) on delete cascade,
  last_active_at timestamptz not null default now()
);

create index if not exists idx_session_activity_user_id on public.session_activity (user_id);

-- ============================================================
-- Row Level Security
-- ============================================================
-- Enabled for the same reason as every other table in this schema: never
-- leave a table open to the public API by omission. In practice, Flask
-- holds the SERVICE ROLE key and is the only thing that ever reads or
-- writes this table, which bypasses RLS entirely -- Flask, not RLS, is
-- the authoritative check for idle timeout (see "why Flask is
-- authoritative over RLS" in docs/design-decisions.md). The read policy
-- below is defence-in-depth only, matching the stance the init migration
-- already takes: an intentionally permissive Sprint 1 placeholder, not
-- real per-row access control. There is deliberately no insert/update
-- policy -- with RLS on and no write policy, only a role that bypasses
-- RLS (service_role) can write here, which is exactly right: nothing
-- other than Flask should ever write session_activity.
alter table public.session_activity enable row level security;

create policy "authenticated read session activity" on public.session_activity
  for select using (auth.role() = 'authenticated');

-- Rollback intent (no down-migration tooling is wired up yet -- recorded
-- here so a manual rollback is unambiguous if it's ever needed):
--   drop policy if exists "authenticated read session activity" on public.session_activity;
--   drop index if exists idx_session_activity_user_id;
--   drop table if exists public.session_activity;
