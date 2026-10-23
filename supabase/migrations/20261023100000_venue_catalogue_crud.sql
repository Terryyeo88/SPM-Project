-- ConnectSphere: Venue Staff add, edit and delete venues
-- Migration: venue_catalogue_crud
-- Scope: IS-61 CRUD in Venue Catalogue -- "As a Venue staff, I want to add,
-- edit and delete venues so that I can easily manage what venues
-- ConnectSphere currently has."
--
--   AC4: "Once a venue is deleted, ongoing events that have booked the
--   venue will lose their booking and the coordinator will be alerted to
--   book another venue on the event details page."
--
-- Adding and editing need no schema change: the backend (service role)
-- writes public.venues directly, validated by app.venues.venue_service.
-- Deleting is what this migration is for.
--
-- A deleted venue is SOFT-deleted (deleted_at), not removed:
--   - venue_bookings.venue_id references it with no ON DELETE action, so a
--     hard delete is refused while any booking -- even a long-finished
--     one -- points at it; and cascading would erase completed events'
--     record of where they were held.
--   - the booking review page (VenueBookingReviewView.vue) loads a
--     booking's venue by id, which has to keep working for old bookings.
-- So a deleted venue leaves the catalogue (GET /venues) and can't be
-- booked, edited or approved against, but GET /venues/<id> still returns
-- it, flagged with deleted_at.
--
-- "Ongoing" is the IS-60 reading: an event that is not completed, cancelled
-- or rejected (see docs/design-decisions.md, "Venue Categories (IS-60)").

-- ============================================================
-- 1. Columns
-- ============================================================

alter table public.venues
  add column if not exists deleted_at timestamptz,
  add column if not exists deleted_by uuid references public.profiles (id);

-- The setup/turnaround buffers became editable with this story; a negative
-- buffer would shrink a booking's held period below the session itself.
alter table public.venues drop constraint if exists venues_buffers_non_negative;
alter table public.venues
  add constraint venues_buffers_non_negative
  check (setup_minutes >= 0 and turnaround_minutes >= 0);

-- Marks a booking that was released because its venue was deleted, as
-- opposed to one the coordinator cancelled themselves. It's what the
-- coordinator's "book another venue" alert reads (lib/venueBookings.js).
-- The release itself is an ordinary cancellation: status 'cancelled', with
-- who/when/why in venue_booking_status_log like every other cancel.
alter table public.venue_bookings
  add column if not exists released_by_venue_deletion boolean not null default false;

-- ============================================================
-- 2. A deleted venue can't be booked
-- ============================================================
-- Refuses a booking that would hold (pending) or holds (confirmed) a
-- deleted venue: a new request, an approval, or a booking moved onto it.
-- The backend checks first for a friendlier message; this is what holds
-- when a request races the delete. FOR SHARE waits for a delete_venue()
-- that has the venue locked, then sees its result; and delete_venue()
-- waits for a booking insert holding this lock, then releases that booking
-- too. Either way no live booking is left on a deleted venue.

create or replace function public.venue_bookings_refuse_deleted_venue() returns trigger
language plpgsql as $$
declare
  v_name text;
begin
  if new.status not in ('pending', 'confirmed') then
    return new;
  end if;
  if tg_op = 'UPDATE' and new.status = old.status and new.venue_id = old.venue_id then
    return new;
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

drop trigger if exists trg_venue_bookings_refuse_deleted_venue on public.venue_bookings;
create trigger trg_venue_bookings_refuse_deleted_venue
  before insert or update of status, venue_id on public.venue_bookings
  for each row execute function public.venue_bookings_refuse_deleted_venue();

-- ============================================================
-- 3. delete_venue: soft delete + release ongoing bookings, in one transaction
-- ============================================================
-- Called by app.venues.venue_service.delete_venue (service role only).
-- Releases every pending or confirmed booking of the venue whose event is
-- ongoing: status -> 'cancelled', released_by_venue_deletion = true, and a
-- venue_booking_status_log row (changed_by = the Venue Staff member, the
-- reason naming the venue). Bookings of completed, cancelled and rejected
-- events are left exactly as they were: that's their history.
--
-- Event status is NOT changed here. Status only ever moves through
-- app.events.transitions (ALLOWED + event_status_log), so the backend sends
-- confirmed / safety_review sessions back to planning afterwards, using the
-- `released` list this returns.
--
-- Returns {"outcome": ...}:
--   not_found        -- no such venue
--   already_deleted  -- deleted before (nothing changed)
--   deleted          -- plus "venue" (the row) and "released":
--                       [{booking_id, event_id, previous_status, event_status}]

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
    set status = 'cancelled', released_by_venue_deletion = true
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

-- Service role only, like register_attendee: Flask checks the caller is
-- Venue Staff (venue.delete) before calling it.
revoke execute on function public.delete_venue(uuid, uuid) from public;
do $$ begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    revoke execute on function public.delete_venue(uuid, uuid) from anon;
  end if;
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    revoke execute on function public.delete_venue(uuid, uuid) from authenticated;
  end if;
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    grant execute on function public.delete_venue(uuid, uuid) to service_role;
  end if;
end $$;

-- Rollback intent (manual; no down-migration tooling yet):
--   drop function if exists public.delete_venue(uuid, uuid);
--   drop trigger if exists trg_venue_bookings_refuse_deleted_venue on public.venue_bookings;
--   drop function if exists public.venue_bookings_refuse_deleted_venue();
--   alter table public.venue_bookings drop column if exists released_by_venue_deletion;
--   alter table public.venues drop constraint if exists venues_buffers_non_negative;
--   alter table public.venues drop column if exists deleted_by;
--   alter table public.venues drop column if exists deleted_at;
