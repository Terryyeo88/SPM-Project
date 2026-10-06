-- ConnectSphere: no two confirmed bookings of one venue may overlap
-- Migration: venue_booking_no_overlap
-- Scope: IS-16 Detect conflicts in venue bookings (Terry, Sprint 2).
--
-- DEPENDS ON public.venue_bookings from 20261004000000_venue_bookings.sql
-- (Josiah, IS-14) and must sort AFTER it. That file is being renamed to fix
-- a version collision with main's 20261004000000_coordinator_lead_role.sql.
-- If its new name sorts later than 20261006000000, this file has to move
-- to a later timestamp too, or `db reset` fails here with "relation
-- public.venue_bookings does not exist".
--
-- Uses Josiah's columns exactly as they are; nothing in his table changes.
--
-- Why a constraint and not only the app check in
-- app.venues.booking_service.confirm_booking: that check reads, then a
-- separate statement writes. Two Venue Staff confirming two overlapping
-- pending bookings at the same moment both read "no confirmed overlap" and
-- both write. Postgres evaluates an exclusion constraint on UPDATE as well
-- as INSERT, so the second pending -> confirmed UPDATE is refused with
-- SQLSTATE 23P01 (exclusion_violation) whichever way the two interleave.
-- The app check stays: it gives the friendly message and the read-only
-- `conflict` flag. See docs/design-decisions.md, "Booking conflicts (IS-16)".
--
-- The period is booking_start..booking_end, which Josiah's code already
-- pads with the venue's setup and turnaround minutes, so turnaround between
-- events is enforced without a rule of its own.
--
-- '[)' (end-exclusive) matches booking_service._spans_overlap
-- (a_start < b_end and b_start < a_end): a booking ending at 14:00 and the
-- next starting at 14:00 do not clash, in the app check or here.
--
-- Only confirmed rows participate (the WHERE clause), the same scope as
-- booking_service._BLOCKING_STATUSES. A pending booking blocks nothing, and
-- a booking that moves from confirmed to any other status (rejected today;
-- whatever a cancelled event's booking becomes later) leaves the constraint
-- at once and frees its period. No trigger or cleanup is needed.
--
-- If confirmed bookings that already overlap exist when this runs, ADD
-- CONSTRAINT fails and names them. That is deliberate: they are real
-- double bookings to resolve, not rows to grandfather in.

-- btree_gist lets one GiST index combine `venue_id with =` (uuid equality)
-- with `&&` on a range. Supabase keeps extensions in the `extensions`
-- schema.
create extension if not exists btree_gist with schema extensions;

alter table public.venue_bookings
  add constraint venue_bookings_no_confirmed_overlap
  exclude using gist (
    venue_id with =,
    tstzrange(booking_start, booking_end, '[)') with &&
  )
  where (status = 'confirmed');
