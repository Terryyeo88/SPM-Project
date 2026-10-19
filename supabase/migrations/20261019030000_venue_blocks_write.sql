-- ConnectSphere: venue_blocks gains a write path
-- Migration: venue_blocks_write
-- Scope: "Venue Becomes Unavailable After Booking" (Josiah, Sprint 3,
-- Week 7 change #2). 20261007000000_venue_calendar.sql created
-- venue_blocks as READ-ONLY (only seed.py/seed.sql wrote it, and that
-- migration's own header named "Venue Becomes Unavailable (blocking)"
-- as the separate, unassigned story that would build creation) -- this
-- is that story, landing the INSERT side.
--
-- INSERT only: no UPDATE/DELETE policy. No story asks for editing or
-- removing a block once created -- flagged in docs/open-questions.md,
-- same as any other scope boundary in this codebase.
--
-- No new trigger: considered a BEFORE UPDATE guard on venue_bookings
-- (refusing a pending -> confirmed update that would land inside an
-- already-blocked period), mirroring IS-16's exclusion-constraint
-- precedent for a similar race. Decided against it for this sprint --
-- see docs/design-decisions.md "Venue block vs. confirm race" for the
-- full trade-off. The confirm path is guarded at the application layer
-- instead (app.venues.booking_service._blocked_period_exists, checked by
-- confirm_booking before deciding).

create policy "authenticated insert venue_blocks" on public.venue_blocks
  for insert with check (auth.role() = 'authenticated');

-- Rollback intent:
--   drop policy if exists "authenticated insert venue_blocks" on public.venue_blocks;
