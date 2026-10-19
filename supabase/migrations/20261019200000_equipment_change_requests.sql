-- ConnectSphere: change requests on an already-confirmed equipment reservation
-- Migration: equipment_change_requests
-- Scope: Update quantity on an existing equipment reservation
-- (Nawaz, Sprint 3, IS-43).
--
-- The story: the Event Coordinator asks for a different quantity on a request
-- that was already accepted; the system recalculates availability for that
-- date/time; Technical Support accepts (the event record then shows the new
-- quantity) or rejects with an explanation sent to the Coordinator. That
-- needs the coordinator's ask to be stored somewhere Technical Support can
-- review it, and it must NOT touch the confirmed request until it is
-- accepted -- the same "change goes through review first" stance the Event
-- Change Request story takes for event details.
--
-- One row per ask, against ONE line of the request (equipment_request_items):
--   old_quantity     -- the line's quantity when the ask was made, kept so the
--                       history still reads correctly after the line changes
--   new_quantity     -- what the coordinator wants
--   status           -- pending -> accepted | rejected (decided once)
--   rejection_reason -- required when rejected, null otherwise
--   decided_by/at    -- the Technical Support user and when
--
-- Only one pending ask per line (partial unique index): a second ask while
-- the first is waiting would leave Technical Support comparing two numbers
-- for the same line. The coordinator can ask again once it is decided.

create type public.equipment_change_status as enum ('pending', 'accepted', 'rejected');

create table if not exists public.equipment_change_requests (
  id uuid primary key default gen_random_uuid(),
  request_item_id uuid not null references public.equipment_request_items (id) on delete cascade,
  requested_by uuid not null references public.profiles (id),
  old_quantity integer not null check (old_quantity > 0),
  new_quantity integer not null check (new_quantity > 0),
  status public.equipment_change_status not null default 'pending',
  rejection_reason text,
  decided_by uuid references public.profiles (id),
  decided_at timestamptz,
  created_at timestamptz not null default now(),
  constraint equipment_change_requests_quantity_differs check (new_quantity <> old_quantity),
  constraint equipment_change_requests_reason_matches_status check (
    (status = 'rejected' and rejection_reason is not null and btrim(rejection_reason) <> '')
    or (status <> 'rejected' and rejection_reason is null)
  )
);

create unique index if not exists equipment_change_requests_one_pending_per_item
  on public.equipment_change_requests (request_item_id)
  where status = 'pending';

create index if not exists idx_equipment_change_requests_status
  on public.equipment_change_requests (status);
create index if not exists idx_equipment_change_requests_request_item_id
  on public.equipment_change_requests (request_item_id);

-- Same stance as the other equipment tables: Flask's service-role key does the
-- real per-role check in app/authz; RLS is defence in depth, read-only.
alter table public.equipment_change_requests enable row level security;

create policy "authenticated read equipment_change_requests" on public.equipment_change_requests
  for select using (auth.role() = 'authenticated');

-- Rollback intent (no down-migration tooling is wired up yet):
--   drop table if exists public.equipment_change_requests;
--   drop type if exists public.equipment_change_status;
