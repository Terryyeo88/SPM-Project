-- ConnectSphere: Event Coordinator Lead role
-- Migration: coordinator_lead_role
-- Scope: Week 7 customer change #5 -- "ConnectSphere has introduced a new
-- internal role, the Event Coordinator Lead, who is responsible for
-- overseeing incoming event requests and assigning them to individual
-- Event Coordinators."
--
-- Only the role value is new. No new table or column is needed:
--   - the Lead's "unassigned queue" is the events that are `submitted`
--     with coordinator_id null (submit no longer auto-assigns), and
--   - who assigned what is already recorded: coordinator_assignment_log
--     (reason "assigned by lead") and event_status_log (the
--     submitted -> under_review row's changed_by is the Lead).
-- Per-role access is enforced in the Flask backend (app/authz), same as
-- every other role -- see 20260911120000_init_users_events.sql section 6.

alter type public.app_role add value if not exists 'event_coordinator_lead';
