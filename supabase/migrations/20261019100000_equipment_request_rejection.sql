-- ConnectSphere: why an equipment request was rejected
-- Migration: equipment_request_rejection
-- Scope: Get warned and reject when requested quantity exceeds availability
-- (Nawaz, Sprint 3, IS-41). The story's third AC: "Rejecting requires an
-- explanation that's sent to the Event Coordinator". equipment_requests has a
-- `rejected` status (20261008000000_equipment.sql) but nowhere to put the
-- explanation, and the coordinator has to be able to read it afterwards.
--
-- Three nullable columns on the request itself, not a status-log table like
-- venue_bookings has: an equipment request is decided at most once (pending
-- -> confirmed or pending -> rejected, and nothing in this codebase moves it
-- again), so there is exactly one reason to keep and no history to log. If a
-- later story lets a rejected request be reopened, that is the moment to add a
-- log table and move these columns into it.
--
--   rejection_reason -- the explanation, set only when status = 'rejected'
--   decided_by       -- the Technical Support user who rejected it
--   decided_at       -- when
--
-- All three stay null for pending and confirmed requests. Accepting (IS-19)
-- does not write decided_by/decided_at: that story predates this one and its
-- confirmation is already visible through its reservation rows. A rejected
-- row is the only one these describe.
--
-- A CHECK keeps the reason and the status in step: a rejected request must
-- carry a non-blank reason, and only a rejected request may carry one. Rows
-- that are already rejected (none are expected: nothing could reject until
-- this story) would violate the first half, so it is added NOT VALID and
-- only enforced for new and updated rows.

alter table public.equipment_requests
  add column if not exists rejection_reason text,
  add column if not exists decided_by uuid references public.profiles (id),
  add column if not exists decided_at timestamptz;

alter table public.equipment_requests
  drop constraint if exists equipment_requests_rejection_reason_matches_status;
alter table public.equipment_requests
  add constraint equipment_requests_rejection_reason_matches_status
  check (
    (status = 'rejected' and rejection_reason is not null and btrim(rejection_reason) <> '')
    or (status <> 'rejected' and rejection_reason is null)
  ) not valid;

-- Rollback intent (no down-migration tooling is wired up yet):
--   alter table public.equipment_requests drop constraint if exists equipment_requests_rejection_reason_matches_status;
--   alter table public.equipment_requests drop column if exists decided_at;
--   alter table public.equipment_requests drop column if exists decided_by;
--   alter table public.equipment_requests drop column if exists rejection_reason;
