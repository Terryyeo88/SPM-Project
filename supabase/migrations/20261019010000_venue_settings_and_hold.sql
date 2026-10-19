-- ConnectSphere: venue settings editing + tentative hold duration
-- Migration: venue_settings_and_hold
-- Scope: "Request Venue Booking with Setup and Turnaround Time" (the
-- editing half -- auto-apply-at-booking-time already shipped in
-- 20261005100000_venue_bookings.sql) and "Venue Availability Calendar
-- Tentative Hold" (Josiah, Sprint 3, Week 7 changes #1 and #4).
--
-- Adds the ONE thing both stories need: a way to change setup_minutes/
-- turnaround_minutes after venue creation (today impossible -- no venue
-- write route or RLS write policy exists at all, confirmed by reading
-- every prior migration touching public.venues), plus a third per-venue
-- timing value, tentative_hold_minutes, for how long a Venue-Staff-
-- approved booking stays "tentatively held" before it must either become
-- a real confirmed event or expire. See docs/design-decisions.md for why
-- hold duration is a third field on this same screen rather than its own
-- separate concept.
--
-- venue_bookings.hold_minutes / confirmed_at are the PER-BOOKING anchor
-- for the lazy expiry check app.venues.booking_release performs -- see
-- that module. Snapshotted at confirm time, same immutability stance
-- setup_minutes/turnaround_minutes already took at request time: editing
-- a venue's tentative_hold_minutes later never retroactively changes an
-- already-confirmed booking's own hold deadline.

-- ============================================================
-- 1. Venue settings: tentative hold duration
-- ============================================================
-- Default 1440 (24h) is a guessed Sprint default, same posture as
-- setup_minutes/turnaround_minutes defaulting to 30 in
-- 20261005100000_venue_bookings.sql -- flagged in docs/open-questions.md
-- for confirmation, not asserted as the customer's intended value.

alter table public.venues
  add column if not exists tentative_hold_minutes integer not null default 1440;

alter table public.venues
  add constraint venues_tentative_hold_minutes_positive check (tentative_hold_minutes > 0);

-- ============================================================
-- 2. Per-booking hold snapshot + expiry anchor
-- ============================================================
-- hold_minutes is snapshotted onto the booking the moment it's CONFIRMED
-- (not at request time, like setup/turnaround -- the hold only starts
-- once Venue Staff approve it; see app.venues.booking_service.confirm_booking),
-- so a later edit to venues.tentative_hold_minutes never changes an
-- already-confirmed booking's own deadline. The transient default below
-- exists only so the column can be added NOT NULL against any existing
-- rows; it is dropped immediately after, so every future write must
-- supply the value explicitly, same two-step pattern setup_minutes/
-- turnaround_minutes used in 20261005100000_venue_bookings.sql.
--
-- confirmed_at is nullable: null for a booking that was never confirmed
-- (still pending, or rejected without ever being approved). It is the
-- expiry anchor: a confirmed booking has expired once
-- now() >= confirmed_at + hold_minutes AND its event has not already
-- reached "confirmed"/"completed" status (see booking_release.py --
-- once the event itself confirms, the hold has "graduated" and must
-- never be revisited, regardless of elapsed time).

alter table public.venue_bookings
  add column if not exists hold_minutes integer not null default 1440,
  add column if not exists confirmed_at timestamptz;

alter table public.venue_bookings
  alter column hold_minutes drop default;

-- Backfill: every row that is ALREADY confirmed gets its real
-- confirmed_at from the audit trail (genuinely recoverable -- the latest
-- venue_booking_status_log row with to_status='confirmed' for that
-- booking). hold_minutes for these pre-existing rows keeps the transient
-- default above (1440) since there is no historical value to recover --
-- a one-time, documented exception to "always snapshotted explicitly",
-- unavoidable for data that predates this migration. See
-- docs/design-decisions.md.

update public.venue_bookings vb
set confirmed_at = latest_confirm.changed_at
from (
  select booking_id, max(changed_at) as changed_at
  from public.venue_booking_status_log
  where to_status = 'confirmed'
  group by booking_id
) as latest_confirm
where latest_confirm.booking_id = vb.id
  and vb.status = 'confirmed';

-- ============================================================
-- 3. Row Level Security: venues gains a write policy (it had none)
-- ============================================================
-- Same defence-in-depth stance as every other table here: Flask holds
-- the service-role key and enforces the real check
-- (rule_venue_manage in app/authz/rules.py, venue_staff only) before a
-- query ever reaches this table. No INSERT/DELETE policy -- no story
-- creates or deletes a venue, only edits settings on an existing one.

create policy "authenticated update venues" on public.venues
  for update using (auth.role() = 'authenticated') with check (auth.role() = 'authenticated');

-- Rollback intent (no down-migration tooling is wired up yet -- recorded
-- here so a manual rollback is unambiguous if it's ever needed):
--   drop policy if exists "authenticated update venues" on public.venues;
--   alter table public.venue_bookings drop column if exists confirmed_at;
--   alter table public.venue_bookings drop column if exists hold_minutes;
--   alter table public.venues drop constraint if exists venues_tentative_hold_minutes_positive;
--   alter table public.venues drop column if exists tentative_hold_minutes;
