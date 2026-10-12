-- ConnectSphere: room layouts managed by Venue Staff
-- Migration: room_layouts
-- Scope: room layouts (theatre, classroom, ...) were the fixed
-- public.room_layout enum. Venue Staff must now be able to add, rename and
-- delete them, which an enum can't support without a migration per change
-- (and a value can never be removed from a Postgres enum at all), so they
-- become rows in public.room_layouts.
--
-- Deleting is two steps:
--   1. Soft delete: is_active = false. The layout can no longer be picked
--      for a new request (the backend enforces that), but every event that
--      already uses it keeps it.
--   2. Hard delete: allowed only once the layout is soft-deleted AND every
--      event still using it is completed or cancelled (section 6 enforces
--      both, whoever runs the DELETE). Those events keep the layout's name.
--
-- How an event keeps the name of a hard-deleted layout:
-- events.room_layout stays, changed from the enum to plain text, and always
-- holds the layout's NAME; the new events.room_layout_id holds the
-- reference. A trigger keeps the two in step (section 5). When a layout is
-- hard-deleted, ON DELETE SET NULL clears room_layout_id and the name stays
-- in room_layout -- so a separate "room_layout_name" copy isn't needed, and
-- everything that reads room_layout as a name (the API, event_logs and
-- event_change_requests snapshots, venue suitability checks) is unchanged.
--
-- venues.supported_layouts likewise changes from room_layout[] to text[]
-- of layout names, kept in step on rename / hard delete (section 7).

-- ============================================================
-- 1. Room layouts
-- ============================================================
-- Unique on lower(name) so "Theatre" can't be added beside "theatre".

create table if not exists public.room_layouts (
  room_layout_id uuid not null default gen_random_uuid(),
  name varchar not null check (btrim(name) <> ''),
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint room_layouts_pkey primary key (room_layout_id)
);

create unique index if not exists room_layouts_name_key on public.room_layouts (lower(name));

drop trigger if exists trg_room_layouts_updated_at on public.room_layouts;
create trigger trg_room_layouts_updated_at
  before update on public.room_layouts
  for each row execute function public.set_updated_at();

-- Every value the old enum had, so every existing event and venue matches.
insert into public.room_layouts (name)
select unnest(enum_range(null::public.room_layout))::text
on conflict do nothing;

-- ============================================================
-- 2. Enum columns -> text, then drop the enum
-- ============================================================

alter table public.events
  alter column room_layout type varchar using room_layout::text;

alter table public.venues
  alter column supported_layouts drop default,
  alter column supported_layouts type text[] using supported_layouts::text[],
  alter column supported_layouts set default '{}';

drop type public.room_layout;

-- ============================================================
-- 3. events.room_layout_id
-- ============================================================

alter table public.events
  add column if not exists room_layout_id uuid
    references public.room_layouts (room_layout_id) on delete set null;

create index if not exists idx_events_room_layout_id on public.events (room_layout_id);

-- ============================================================
-- 4. Point existing events at their layout
-- ============================================================
-- updated_at is paused for the backfill: linking a row to its layout
-- isn't an edit anyone made to the event.

alter table public.events disable trigger trg_events_updated_at;

update public.events e
set room_layout_id = r.room_layout_id
from public.room_layouts r
where r.name = e.room_layout
  and e.room_layout_id is null;

alter table public.events enable trigger trg_events_updated_at;

do $$
begin
  if exists (select 1 from public.events where room_layout is not null and room_layout_id is null) then
    raise exception 'Backfill left events with a room_layout that matches no room_layouts row.';
  end if;
end $$;

-- ============================================================
-- 5. Keep events.room_layout (name) and room_layout_id in step
-- ============================================================
-- Whoever writes an event -- the API (which sends the name), seed scripts,
-- or someone editing in the dashboard -- can set either column:
--   - room_layout_id set/changed  -> room_layout becomes that layout's name
--   - room_layout set/changed     -> room_layout_id is looked up by name;
--                                    an unknown name is refused
--   - only room_layout_id cleared -> the name is kept. This is ON DELETE SET
--                                    NULL after a hard delete: the name is
--                                    the event's record of its layout.
-- Whether a layout may be CHOSEN (active, or the one the event already
-- has) is the backend's check -- see app.events.event_service.

create or replace function public.events_sync_room_layout() returns trigger
language plpgsql as $$
begin
  if new.room_layout_id is not null
     and (tg_op = 'INSERT' or new.room_layout_id is distinct from old.room_layout_id) then
    select name into new.room_layout
    from public.room_layouts
    where room_layout_id = new.room_layout_id;
    return new;
  end if;

  if tg_op = 'INSERT' or new.room_layout is distinct from old.room_layout then
    if new.room_layout is null then
      new.room_layout_id := null;
    else
      select room_layout_id into new.room_layout_id
      from public.room_layouts
      where name = new.room_layout;
      if not found then
        raise exception 'Unknown room layout "%".', new.room_layout
          using errcode = 'foreign_key_violation';
      end if;
    end if;
  end if;

  return new;
end $$;

drop trigger if exists trg_events_sync_room_layout on public.events;
create trigger trg_events_sync_room_layout
  before insert or update of room_layout, room_layout_id on public.events
  for each row execute function public.events_sync_room_layout();

-- ============================================================
-- 6. Hard delete: only a soft-deleted layout no live event uses
-- ============================================================
-- Refused unless is_active is false (23514, check_violation) and every
-- event using the layout is completed or cancelled (23503,
-- foreign_key_violation). The backend turns both into a 409. Events that
-- used it keep its name in room_layout (section 5).

create or replace function public.before_room_layout_delete() returns trigger
language plpgsql as $$
declare
  live_events integer;
begin
  if old.is_active then
    raise exception 'Room layout "%" must be soft-deleted before it can be permanently deleted.', old.name
      using errcode = 'check_violation';
  end if;

  select count(*) into live_events
  from public.events e
  where e.room_layout_id = old.room_layout_id
    and e.status not in ('completed', 'cancelled');

  if live_events > 0 then
    raise exception 'Room layout "%" is still used by % event(s) that are not completed or cancelled.',
      old.name, live_events
      using errcode = 'foreign_key_violation';
  end if;

  return old;
end $$;

drop trigger if exists trg_room_layouts_before_delete on public.room_layouts;
create trigger trg_room_layouts_before_delete
  before delete on public.room_layouts
  for each row execute function public.before_room_layout_delete();

-- ============================================================
-- 7. Renames and hard deletes reach events and venues
-- ============================================================
-- A rename updates the name on every event still linked to the layout, in
-- every venue's supported_layouts, and in PENDING change requests (which
-- name the layout in JSON, so would otherwise ask for a name that no longer
-- exists and fail at approval). Decided change requests and event_logs are
-- history and keep the name as it was. A hard delete removes the name from
-- venues' supported_layouts (events keep it -- section 6).

create or replace function public.after_room_layout_rename() returns trigger
language plpgsql as $$
begin
  update public.events
  set room_layout = new.name
  where room_layout_id = new.room_layout_id;

  update public.venues
  set supported_layouts = array_replace(supported_layouts, old.name::text, new.name::text)
  where old.name::text = any (supported_layouts);

  update public.event_change_requests
  set requested_changes = case
        when requested_changes ->> 'room_layout' = old.name
        then jsonb_set(requested_changes, '{room_layout}', to_jsonb(new.name::text))
        else requested_changes
      end,
      previous_values = case
        when previous_values ->> 'room_layout' = old.name
        then jsonb_set(previous_values, '{room_layout}', to_jsonb(new.name::text))
        else previous_values
      end
  where status = 'pending'
    and (requested_changes ->> 'room_layout' = old.name or previous_values ->> 'room_layout' = old.name);

  return null;
end $$;

drop trigger if exists trg_room_layouts_after_rename on public.room_layouts;
create trigger trg_room_layouts_after_rename
  after update of name on public.room_layouts
  for each row when (old.name is distinct from new.name)
  execute function public.after_room_layout_rename();

create or replace function public.after_room_layout_delete() returns trigger
language plpgsql as $$
begin
  update public.venues
  set supported_layouts = array_remove(supported_layouts, old.name::text)
  where old.name::text = any (supported_layouts);
  return null;
end $$;

drop trigger if exists trg_room_layouts_after_delete on public.room_layouts;
create trigger trg_room_layouts_after_delete
  after delete on public.room_layouts
  for each row execute function public.after_room_layout_delete();

-- A venue may only list layouts that exist (soft-deleted ones included --
-- the room can still physically be set up that way). An array can't carry
-- a foreign key, so this check stands in for one.

create or replace function public.venues_check_supported_layouts() returns trigger
language plpgsql as $$
declare
  unknown text;
begin
  select layout into unknown
  from unnest(new.supported_layouts) as layout
  where not exists (select 1 from public.room_layouts r where r.name = layout)
  limit 1;
  if unknown is not null then
    raise exception 'Unknown room layout "%".', unknown
      using errcode = 'foreign_key_violation';
  end if;
  return new;
end $$;

drop trigger if exists trg_venues_check_supported_layouts on public.venues;
create trigger trg_venues_check_supported_layouts
  before insert or update of supported_layouts on public.venues
  for each row execute function public.venues_check_supported_layouts();

-- ============================================================
-- 8. Row Level Security
-- ============================================================
-- Same stance as every other table: Flask's service-role key does the
-- real per-role check in app/authz (Venue Staff manage, see
-- rule_room_layout_manage); RLS is defence in depth only. Read-only for
-- authenticated users, no write policy.

alter table public.room_layouts enable row level security;

create policy "authenticated read room_layouts" on public.room_layouts
  for select using (auth.role() = 'authenticated');

-- Rollback intent (no down-migration tooling is wired up yet -- recorded
-- here so a manual rollback is unambiguous if it's ever needed). Only
-- possible while every room_layouts name is one of the six original values:
--   drop trigger if exists trg_venues_check_supported_layouts on public.venues;
--   drop trigger if exists trg_events_sync_room_layout on public.events;
--   alter table public.events drop column room_layout_id;
--   create type public.room_layout as enum ('theatre', 'classroom', 'boardroom', 'seminar', 'banquet', 'networking');
--   alter table public.events alter column room_layout type public.room_layout using room_layout::public.room_layout;
--   alter table public.venues alter column supported_layouts drop default,
--     alter column supported_layouts type public.room_layout[] using supported_layouts::public.room_layout[],
--     alter column supported_layouts set default '{}';
--   drop table public.room_layouts;
--   drop function if exists public.events_sync_room_layout, public.before_room_layout_delete,
--     public.after_room_layout_rename, public.after_room_layout_delete, public.venues_check_supported_layouts;
