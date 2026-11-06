-- ConnectSphere: events.registration_needs can no longer be NULL
-- Migration: events_registration_needs_not_null
--
-- Scope: IS-21 (organiser requests a change to an event). Sessions created
-- before registration_needs was required on submission had NULL there. The
-- change-request form sends the session's current values back, and
-- event_service.validate_event_payload refuses a non-boolean
-- registration_needs ("registration_needs is required"), so the organiser
-- could not request any change to those old sessions.
--
-- Every reader already treats NULL as "no registration":
-- rules.rule_registration_create needs `is True`, register_attendee() needs
-- `is not true`, and the frontend shows `registration_needs || false`.
-- Setting those rows to false therefore changes nothing anyone sees; it
-- only makes the stored value match what the app already assumed.
--
-- The shared project was fixed by hand with these same statements on
-- 2026-11-05. This file brings the repo in line, so a fresh database
-- (npx supabase db reset, a new teammate's project) gets the same column.
--
-- Default false: an insert that leaves the column out (a half-filled draft)
-- gets "no registration" instead of failing the NOT NULL.
--
-- Safe to run twice: the update matches nothing the second time, and
-- setting an existing default or NOT NULL again is a no-op.

update public.events set registration_needs = false where registration_needs is null;

alter table public.events alter column registration_needs set default false;
alter table public.events alter column registration_needs set not null;

-- So the API sees the change straight away.
notify pgrst, 'reload schema';

-- Rollback intent (manual): the backfilled rows can't be told apart from
-- real "false" answers, so only the constraint and default come back --
--   alter table public.events alter column registration_needs drop not null;
--   alter table public.events alter column registration_needs drop default;
