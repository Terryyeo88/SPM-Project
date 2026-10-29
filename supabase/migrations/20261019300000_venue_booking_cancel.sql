-- ConnectSphere: cancelling one venue booking
-- Migration: venue_booking_cancel
-- Scope: IS-9 Update Event Information During Planning -- "Changes or
-- cancellation of one venue arrangement should not automatically remove
-- the other venue bookings."
--
-- A session may hold more than one venue booking (a main hall and a
-- breakout room, or a second venue requested while the first is still
-- pending). The assigned coordinator can now cancel ONE of them: that row
-- moves to 'cancelled' and every other booking for the session is left
-- exactly as it was (app.venues.booking_service.cancel_booking).
--
-- A new enum value, not a delete: the booking stays in the session's
-- history, and the cancellation (who, when, why) is recorded in
-- venue_booking_status_log like approve/reject already are -- whose
-- from_status/to_status columns use this same enum, so they take the new
-- value too.
--
-- No constraint changes: venue_bookings_no_confirmed_overlap (IS-16)
-- applies only WHERE status = 'confirmed', so a cancelled booking frees
-- its period for other events straight away. The venue calendar, the
-- conflict checks and the safety check all filter on pending/confirmed
-- already, so a cancelled booking drops out of each of them.

alter type public.venue_booking_status add value if not exists 'cancelled';

-- Rollback intent: Postgres can't drop an enum value. Move any cancelled
-- rows back (or delete them), then recreate the type without 'cancelled'
-- and re-point venue_bookings.status and venue_booking_status_log's two
-- columns at it.
