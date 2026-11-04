-- ConnectSphere: clarification thread on an event request
-- Migration: event_clarifications
--
-- Scope: Event Review and Approval -- "Has the option to decide whether to
-- approve, reject or request for clarification or amendments. Upon
-- choosing to request for clarification or amendments, the Event
-- Coordinator can enter comments and submit it for the Event Organizer to
-- view." and "Given that an event request is under review, when the Event
-- Coordinator sends feedback for amendments or clarification, then the
-- Event Organizer is able to answer to the Event Coordinator."
--
-- Week 9 clarification: the conversation itself "is happening offline but
-- the system should have a means for recording the comments for
-- tracking" -- so this is an append-only comment log, not a live chat.
-- Week 4: no separate status; clarification happens while the request is
-- "under review".
--
-- One thread per event REQUEST (shared_event_id), not per session: the
-- coordinator approves/rejects every session of a request together
-- (app.events.event_service._decide), so the conversation about it is one
-- conversation too. event_id records which session's page a message was
-- sent from, for reference only. shared_event_id has no foreign key for the
-- same reason as on event_change_requests (it isn't unique on events);
-- a legacy event with no shared_event_id uses its own id, the convention
-- app.events.event_log.group_id already follows.
--
-- author_role is stored, not derived: if the request is reassigned, the
-- previous coordinator's messages must still read as the coordinator's,
-- which comparing author_id with events.coordinator_id would get wrong.
--
-- Messages are never edited or deleted (AC: recorded for tracking), so
-- there is no updated_at and no delete path.
--
-- Safe to run twice: every statement is guarded, and nothing is dropped.

do $$ begin
  create type public.clarification_author_role as enum ('coordinator', 'organizer');
exception when duplicate_object then null;
end $$;

create table if not exists public.event_clarifications (
  clarification_id uuid not null default gen_random_uuid(),

  shared_event_id uuid not null,
  -- The session whose page the message was sent from.
  event_id uuid not null,

  author_id uuid not null,
  author_role public.clarification_author_role not null,
  message text not null,

  created_at timestamptz not null default now(),

  constraint event_clarifications_pkey primary key (clarification_id),
  constraint event_clarifications_event_id_fkey foreign key (event_id) references public.events (id) on delete cascade,
  constraint event_clarifications_author_id_fkey foreign key (author_id) references public.profiles (id),
  -- Same limits the API enforces (blank not allowed, 1000 characters max),
  -- held here too in case a write ever skips the API's check.
  constraint event_clarifications_message_check check (
    length(btrim(message)) > 0 and length(message) <= 1000
  )
);

-- A thread is always loaded as "every message of this request, oldest first".
create index if not exists idx_event_clarifications_shared_event_id
  on public.event_clarifications using btree (shared_event_id, created_at);

-- ============================================================
-- Row Level Security
-- ============================================================
-- Deliberately STRICTER than the placeholder "any authenticated user may
-- read/write" policies on the older tables: RLS is on with NO policies, so
-- only Flask's service-role key (which bypasses RLS) can touch this table.
-- That works because the frontend never queries tables directly -- it uses
-- Supabase only to sign in, and reads/writes everything through the Flask
-- API, where app/authz decides who may see or post in a thread. Without
-- this, any signed-in user could read every thread with the anon key.
alter table public.event_clarifications enable row level security;

-- Rollback intent (manual; no down-migration tooling yet):
--   drop table if exists public.event_clarifications;
--   drop type if exists public.clarification_author_role;
