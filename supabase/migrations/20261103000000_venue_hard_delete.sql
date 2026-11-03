-- ConnectSphere: deleting a venue removes its record
-- Migration: venue_hard_delete
-- Scope: IS-61 CRUD in Venue Catalogue, revised (Aaralyn, 3 Nov). Deleting a
-- venue was a soft delete (20261023100000_venue_catalogue_crud.sql) followed
-- by a separate permanent delete (20261023200000_venue_permanent_delete.sql).
-- Now one delete removes the venue's row from public.venues.
--
-- Past records keep the venue's name: every booking that pointed at the
-- venue -- completed and cancelled events' above all -- has the name copied
-- into venue_bookings.venue_name as plain text and loses only the link
-- (venue_id becomes NULL, ON DELETE SET NULL). Both were already in place
-- for the permanent delete (trigger before_venue_delete, constraint
-- venue_bookings_venue_known); this migration only changes when they run.
--
-- What still happens on delete, in the same transaction: ongoing events'
-- pending or confirmed bookings (event not completed, cancelled or
-- rejected) are released first -- 'cancelled', released_by_venue_deletion,
-- released_at, logged -- exactly as before, so the coordinator's "book
-- another venue" alert and notification are unchanged.
--
-- EXISTING ROWS: venues already soft-deleted are removed now, keeping their
-- name on their bookings. Their ongoing bookings were released when they
-- were soft-deleted, so before_venue_delete lets them go. Then deleted_at /
-- deleted_by are dropped: nothing is soft-deleted any more.
--
-- Re-runnable: every step is idempotent.

-- ============================================================
-- 1. Remove venues already soft-deleted
-- ============================================================
-- Guarded: on a second run the column is already gone.

do $$ begin
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'venues' and column_name = 'deleted_at'
  ) then
    execute 'delete from public.venues where deleted_at is not null';
  end if;
end $$;

-- ============================================================
-- 2. delete_venue(): release ongoing bookings, then remove the row
-- ============================================================
-- Called by app.venues.venue_service.delete_venue (service role only; the
-- grants from 20261023100000_venue_catalogue_crud.sql still apply).
--
-- Returns {"outcome": ...}:
--   not_found -- no such venue
--   deleted   -- plus "venue" (the row as it was) and "released":
--                [{booking_id, event_id, previous_status, event_status}]

create or replace function public.delete_venue(p_venue_id uuid, p_deleted_by uuid)
returns jsonb
language plpgsql
as $$
declare
  v_venue public.venues%rowtype;
  v_released jsonb;
begin
  select * into v_venue from public.venues where id = p_venue_id for update;
  if not found then
    return jsonb_build_object('outcome', 'not_found');
  end if;

  with targets as (
    select b.id, b.status, b.event_id, e.status as event_status
    from public.venue_bookings b
    join public.events e on e.id = b.event_id
    where b.venue_id = p_venue_id
      and b.status in ('pending', 'confirmed')
      and e.status not in ('completed', 'cancelled', 'rejected')
    for update of b
  ),
  released as (
    update public.venue_bookings b
    set status = 'cancelled', released_by_venue_deletion = true, released_at = now()
    from targets t
    where b.id = t.id
    returning b.id, b.event_id, t.status as previous_status, t.event_status
  ),
  logged as (
    insert into public.venue_booking_status_log (booking_id, from_status, to_status, changed_by, reason)
    select id, previous_status, 'cancelled', p_deleted_by,
      format('Venue "%s" was deleted from the venue catalogue, so this booking was released.', v_venue.name)
    from released
    returning booking_id
  )
  select coalesce(
    jsonb_agg(jsonb_build_object(
      'booking_id', id,
      'event_id', event_id,
      'previous_status', previous_status,
      'event_status', event_status
    )),
    '[]'::jsonb
  ) into v_released
  from released;

  -- A separate statement, so it sees the releases above: before_venue_delete
  -- copies the name onto every booking (and would refuse if a live booking
  -- of an ongoing event were somehow left), then ON DELETE SET NULL unlinks
  -- them.
  delete from public.venues where id = p_venue_id;

  return jsonb_build_object('outcome', 'deleted', 'venue', to_jsonb(v_venue), 'released', v_released);
end $$;

-- ============================================================
-- 3. A booking can't become live without a venue
-- ============================================================
-- As in 20261023200000_venue_permanent_delete.sql, without the soft-delete
-- check. A booking request racing the delete waits on the venue row's lock
-- and then fails its foreign key (23503), which the backend reports as
-- "venue does not exist".

create or replace function public.venue_bookings_refuse_deleted_venue() returns trigger
language plpgsql as $$
begin
  if new.status not in ('pending', 'confirmed') then
    return new;
  end if;
  if new.venue_id is not null then
    return new;
  end if;
  if tg_op = 'UPDATE' and new.status = old.status then
    return new;  -- the venue was deleted under it (ON DELETE SET NULL)
  end if;
  raise exception 'Venue "%" has been deleted from the venue catalogue and can no longer be booked.',
    coalesce(new.venue_name, 'unknown') using errcode = 'check_violation';
end $$;

-- ============================================================
-- 4. No soft-delete state any more
-- ============================================================

alter table public.venues drop column if exists deleted_by;
alter table public.venues drop column if exists deleted_at;

-- RLS: no change. venues has no delete policy, so only the service role
-- (Flask, after venue.delete) can delete one.

-- Rollback intent (manual; no down-migration tooling yet). Deleted venues
-- can't be brought back -- their rows are gone; their bookings keep the name:
--   alter table public.venues
--     add column if not exists deleted_at timestamptz,
--     add column if not exists deleted_by uuid references public.profiles (id);
--   -- re-run sections 2 and 3 of 20261023200000_venue_permanent_delete.sql
