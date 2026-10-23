-- ConnectSphere: permanently deleting a venue
-- Migration: venue_permanent_delete
-- Scope: IS-61 CRUD in Venue Catalogue. Deleting a venue is a soft delete
-- (20261023100000_venue_catalogue_crud.sql); this adds the second step,
-- permanently removing an already-deleted venue so it isn't left as a stale
-- row in public.venues. Same two-step shape as IS-60's room layouts.
--
-- What a permanent delete keeps: every booking that pointed at the venue --
-- completed and cancelled events' bookings above all -- keeps the venue's
-- NAME (venue_bookings.venue_name) and loses only the link (venue_id becomes
-- NULL, ON DELETE SET NULL). So past events still say where they were held.
-- An event's own room layout (events.room_layout) never depended on the
-- venue and is unaffected.
--
-- Guarded by the database, whoever runs the DELETE: never while a pending or
-- confirmed booking of an ongoing event (not completed, cancelled or
-- rejected) still uses the venue. The soft delete releases those, so this
-- only bites if one was written around it.
--
-- "Deleted from the catalogue first" is the app's rule
-- (venue_service.permanently_delete_venue), NOT the database's: other
-- stories' integration tests remove their throwaway venues with a plain
-- DELETE once their bookings are gone, and must keep working. Unlike IS-60's
-- room layouts, a venue that nothing uses is safe to remove either way.
--
-- Also: released bookings get their own released_at. The coordinator's
-- "book another venue" alert used updated_at as the release time, and the
-- SET NULL above rewrites every booking of the venue, which would have moved
-- that time and could bring back an alert the coordinator had dealt with.

-- ============================================================
-- 1. Bookings keep the venue's name when its row goes
-- ============================================================

alter table public.venue_bookings
  add column if not exists venue_name text,
  add column if not exists released_at timestamptz;

alter table public.venue_bookings alter column venue_id drop not null;

alter table public.venue_bookings drop constraint if exists venue_bookings_venue_id_fkey;
alter table public.venue_bookings
  add constraint venue_bookings_venue_id_fkey
  foreign key (venue_id) references public.venues (id) on delete set null;

-- A booking always says which venue it is (or was) for.
alter table public.venue_bookings drop constraint if exists venue_bookings_venue_known;
alter table public.venue_bookings
  add constraint venue_bookings_venue_known
  check (venue_id is not null or venue_name is not null);

-- ============================================================
-- 2. released_at for bookings released by a venue deletion
-- ============================================================
-- Existing released bookings: the release's own log entry, else updated_at
-- (they haven't been written since the release).

update public.venue_bookings b
set released_at = coalesce(
  (select max(l.changed_at) from public.venue_booking_status_log l
   where l.booking_id = b.id and l.to_status = 'cancelled'),
  b.updated_at
)
where b.released_by_venue_deletion and b.released_at is null;

-- delete_venue() as in 20261023100000_venue_catalogue_crud.sql, now also
-- stamping released_at.
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
  if v_venue.deleted_at is not null then
    return jsonb_build_object('outcome', 'already_deleted');
  end if;

  update public.venues
  set deleted_at = now(), deleted_by = p_deleted_by
  where id = p_venue_id
  returning * into v_venue;

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

  return jsonb_build_object('outcome', 'deleted', 'venue', to_jsonb(v_venue), 'released', v_released);
end $$;

-- ============================================================
-- 3. A booking can't become live without a venue
-- ============================================================
-- Extends trg_venue_bookings_refuse_deleted_venue: a pending booking left on
-- a permanently deleted venue (a finished event's) has venue_id NULL, and
-- must not be approved. The SET NULL itself doesn't change status, so it
-- passes.

create or replace function public.venue_bookings_refuse_deleted_venue() returns trigger
language plpgsql as $$
declare
  v_name text;
begin
  if new.status not in ('pending', 'confirmed') then
    return new;
  end if;
  if tg_op = 'UPDATE' and new.status = old.status and new.venue_id is not distinct from old.venue_id then
    return new;
  end if;
  if new.venue_id is null then
    if tg_op = 'UPDATE' and new.status = old.status then
      return new;  -- the venue was permanently deleted under it
    end if;
    raise exception 'Venue "%" has been permanently deleted and can no longer be booked.',
      coalesce(new.venue_name, 'unknown') using errcode = 'check_violation';
  end if;
  select name into v_name from public.venues
  where id = new.venue_id and deleted_at is not null
  for share;
  if found then
    raise exception 'Venue "%" has been deleted from the venue catalogue and can no longer be booked.', v_name
      using errcode = 'check_violation';
  end if;
  return new;
end $$;

-- ============================================================
-- 4. Permanent delete: never a venue an ongoing event still uses
-- ============================================================

create or replace function public.before_venue_delete() returns trigger
language plpgsql as $$
begin
  if exists (
    select 1
    from public.venue_bookings b
    join public.events e on e.id = b.event_id
    where b.venue_id = old.id
      and b.status in ('pending', 'confirmed')
      and e.status not in ('completed', 'cancelled', 'rejected')
  ) then
    raise exception 'Venue "%" still has bookings for ongoing events, so it can''t be permanently deleted.', old.name
      using errcode = 'foreign_key_violation';
  end if;
  update public.venue_bookings set venue_name = old.name where venue_id = old.id;
  return old;
end $$;

drop trigger if exists trg_venues_before_delete on public.venues;
create trigger trg_venues_before_delete
  before delete on public.venues
  for each row execute function public.before_venue_delete();

-- RLS: no change. venues and venue_bookings keep RLS enabled with their
-- existing policies; venues has no delete policy, so only the service role
-- (Flask, after venue.delete) can delete one.

-- Rollback intent (manual; no down-migration tooling yet). Only possible
-- while no venue has been permanently deleted (venue_id would be NULL):
--   drop trigger if exists trg_venues_before_delete on public.venues;
--   drop function if exists public.before_venue_delete();
--   -- re-run section 2/3 functions from 20261023100000_venue_catalogue_crud.sql
--   alter table public.venue_bookings drop constraint if exists venue_bookings_venue_known;
--   alter table public.venue_bookings drop constraint if exists venue_bookings_venue_id_fkey;
--   alter table public.venue_bookings
--     add constraint venue_bookings_venue_id_fkey foreign key (venue_id) references public.venues (id);
--   alter table public.venue_bookings alter column venue_id set not null;
--   alter table public.venue_bookings drop column if exists released_at;
--   alter table public.venue_bookings drop column if exists venue_name;
