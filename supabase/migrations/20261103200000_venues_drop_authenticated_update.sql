-- ConnectSphere: only the backend changes a venue
-- Migration: venues_drop_authenticated_update
-- Scope: IS-61 CRUD in Venue Catalogue (found running its integration tests,
-- 3 Nov). 20261019010000_venue_settings_and_hold.sql added the RLS policy
-- "authenticated update venues", which lets ANY signed-in user -- an
-- attendee included -- change any venue's record by calling the database
-- directly with the publishable key, skipping the backend's Venue Staff
-- check (rules.py::rule_venue_edit). Caught by
-- test_venue_catalogue_crud_integration.py::test_a_signed_in_user_cannot_change_a_venue_directly.
--
-- Nothing relies on it: the frontend never writes venues itself, and Flask
-- writes with the service-role key, which bypasses RLS. Same stance as every
-- other table here -- RLS stays enabled with the read policy only
-- ("authenticated read venues", 20260923000000_venues.sql), and the backend
-- does the real authorisation.
--
-- Re-runnable.

drop policy if exists "authenticated update venues" on public.venues;

-- Rollback intent (manual; re-opens the gap above):
--   create policy "authenticated update venues" on public.venues
--     for update using (auth.role() = 'authenticated') with check (auth.role() = 'authenticated');
