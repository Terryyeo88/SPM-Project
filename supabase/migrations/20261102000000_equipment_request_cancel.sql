-- ConnectSphere: the coordinator cancelling an equipment request
-- Migration: equipment_request_cancel
-- Scope: cancel an equipment booking (Nawaz, Sprint 3, follow-up to IS-17/IS-19).
-- Teammate feedback: "allow the coordinator to cancel the equipment booking
-- as well so the coordinator can make a new request for equipment at a
-- different date and time if needed".
--
-- A request is cancelled by moving it to 'cancelled', not by deleting it, so
-- it stays in the event's history (the same choice IS-9 made for venue
-- bookings in 20261019300000_venue_booking_cancel.sql). Cancelling a
-- confirmed request also deletes its equipment_reservations rows in the
-- app (app.equipment.equipment_service.cancel_request), which is what frees
-- the units: availability is counted from those rows, never stored, so the
-- units are available to other events the moment they are gone.
--
-- No new table and no constraint changes: equipment_requests already has RLS
-- and its read policy (20261008000000_equipment.sql), and the rejection
-- CHECK from 20261019100000 only constrains status = 'rejected'.

alter type public.equipment_request_status add value if not exists 'cancelled';

-- Rollback intent: Postgres can't drop an enum value. Move any cancelled
-- rows to another status (or delete them), then recreate the type without
-- 'cancelled' and re-point equipment_requests.status at it.
