-- ConnectSphere: a pending venue booking has no tentative hold yet
-- Migration: venue_booking_hold_minutes_nullable
-- Scope: fixes 20261019010000_venue_settings_and_hold.sql, which made
-- venue_bookings.hold_minutes NOT NULL and then dropped its default. The
-- hold is only snapshotted when Venue Staff CONFIRM a booking
-- (app.venues.booking_service.confirm_booking); a coordinator's new request
-- (create_booking_request) is pending and has no hold, so every new request
-- was refused with a not-null violation -- the "Internal server error" when
-- requesting a venue.
--
-- NULL means "not confirmed yet", the same as confirmed_at, and
-- app.venues.booking_release.release_expired_hold already skips a booking
-- with no hold_minutes. Existing rows are unchanged.
--
-- Re-runnable.

alter table public.venue_bookings alter column hold_minutes drop not null;

-- So the API sees the change straight away.
notify pgrst, 'reload schema';

-- Rollback intent (manual): only once every pending booking has a value --
--   alter table public.venue_bookings alter column hold_minutes set not null;
