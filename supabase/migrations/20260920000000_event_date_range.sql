-- ConnectSphere: event date range (multi-day support), 24-hour availability
-- Migration: event_date_range
-- Scope: events.preferred_date -> events.preferred_start_date (rename),
-- plus a new nullable events.preferred_end_date column. This was applied
-- directly against the live database ahead of this migration file being
-- written -- it's added here so a fresh environment (or anyone running
-- `supabase db reset`) ends up with the same schema, rather than the
-- rename only existing as tribal knowledge.
--
-- Why a real end-date column instead of continuing to infer everything
-- from one date + two times: the events table used to have exactly one
-- preferred_date shared by both preferred_start_time and
-- preferred_end_time, which made a genuinely multi-day event
-- inexpressible -- an event running from one evening into the next
-- morning had no way to say its end time landed on a LATER calendar day.
-- preferred_end_date fixes that directly. It's nullable because a
-- single-day event still just omits it -- app.events.event_service
-- treats a missing end date as "ends the same day it starts".
--
-- Also removes the 8am-10pm venue-hours restriction that had briefly been
-- added to app.events.event_service's own validation logic -- that was
-- never expressed as a DB constraint, so no schema change is needed here
-- to remove it; venues are available 24 hours.

alter table public.events
  rename column preferred_date to preferred_start_date;

alter table public.events
  add column if not exists preferred_end_date date;

-- Rollback intent (no down-migration tooling is wired up yet -- recorded
-- here so a manual rollback is unambiguous if it's ever needed):
--   alter table public.events drop column if exists preferred_end_date;
--   alter table public.events rename column preferred_start_date to preferred_date;
