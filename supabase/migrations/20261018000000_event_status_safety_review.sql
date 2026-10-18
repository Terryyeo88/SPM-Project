-- ConnectSphere: safety_review event status
-- Migration: event_status_safety_review
-- Scope: Week 7 Customer Changes #6, Operational Feasibility Check --
-- "After the venue and technical arrangements have been confirmed, the
-- Safety Officer must conduct an Operational Safety Check before the event
-- can proceed to preparation." Adds one value to public.event_status,
-- between planning and confirmed:
--
--   ... planning -> safety_review -> confirmed ...
--
-- Status only. Nothing moves an event into safety_review yet: the Safety
-- Officer role and its approve / reject / request-changes actions are a
-- separate story (docs/open-questions.md). No new table, so there is no
-- new RLS policy to add; events keeps its existing policies.
--
-- Postgres can't use a newly added enum value inside the transaction that
-- added it, so any seed or backfill that writes 'safety_review' must live
-- in a later migration, not this one.

alter type public.event_status add value if not exists 'safety_review' after 'planning';

-- Rollback intent (manual): Postgres cannot drop a value from an enum.
-- To roll back, first move any events off it:
--   update public.events set status = 'planning' where status = 'safety_review';
-- then rebuild the type without the value (create a new type, alter
-- events.status and event_status_log.from_status/to_status to use it,
-- drop the old type, rename). Simpler in practice: leave the unused value
-- in place, since nothing can reach it without the transition edges.
