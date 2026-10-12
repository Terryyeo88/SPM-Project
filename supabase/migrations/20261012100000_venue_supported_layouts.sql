-- ConnectSphere: venues list their supported room layouts by name
-- Migration: venue_supported_layouts
-- Scope: a venue's supported room layouts live in venues.supported_layouts,
-- a text[] of room layout names -- as they always have (it was a
-- public.room_layout[] until 20261012000000_room_layouts.sql replaced that
-- enum with the room_layouts table and turned the column into text[]).
--
-- CONVERGES, like 20261012000000_room_layouts.sql: on the live database
-- this column had been dropped and a venue_room_layouts join table made by
-- hand instead. Here the column is restored, filled from that table, and
-- the table is dropped. From the migration files the column already exists
-- and there is no join table, so those steps do nothing.
--
-- An array can't carry a foreign key, so triggers keep venues' names in
-- step with room_layouts:
--   - a venue may only list layouts that exist (soft-deleted ones included;
--     the room can still physically be set up that way)
--   - renaming a layout renames it in every venue's list
--   - permanently deleting a layout removes it from every venue's list

-- ============================================================
-- 1. The column
-- ============================================================

alter table public.venues
  add column if not exists supported_layouts text[] not null default '{}';

-- ============================================================
-- 2. Fill it from a hand-made venue_room_layouts table, then drop that
-- ============================================================
-- Only venues whose list is still empty are filled, so nothing already in
-- the column is overwritten. updated_at is paused: restoring data isn't an
-- edit anyone made to the venue.

do $$ begin
  if exists (select 1 from pg_trigger where tgname = 'trg_venues_updated_at' and tgrelid = 'public.venues'::regclass) then
    alter table public.venues disable trigger trg_venues_updated_at;
  end if;
end $$;

do $$
begin
  if to_regclass('public.venue_room_layouts') is not null then
    execute $copy$
      update public.venues v
      set supported_layouts = links.names
      from (
        select vrl.venue_id, array_agg(r.name::text order by r.name) as names
        from public.venue_room_layouts vrl
        join public.room_layouts r using (room_layout_id)
        group by vrl.venue_id
      ) as links
      where links.venue_id = v.id
        and v.supported_layouts = '{}'
    $copy$;
    drop table public.venue_room_layouts;
  end if;
end $$;

-- Names spelled differently from their room layout only in case take the
-- layout's spelling, so the exact-name checks below match.
update public.venues v
set supported_layouts = (
  select array_agg(coalesce(r.name::text, listed.name) order by listed.position)
  from unnest(v.supported_layouts) with ordinality as listed(name, position)
  left join public.room_layouts r on lower(r.name) = lower(listed.name)
)
where exists (
  select 1
  from unnest(v.supported_layouts) as listed(name)
  join public.room_layouts r on lower(r.name) = lower(listed.name)
  where r.name <> listed.name
);

do $$ begin
  if exists (select 1 from pg_trigger where tgname = 'trg_venues_updated_at' and tgrelid = 'public.venues'::regclass) then
    alter table public.venues enable trigger trg_venues_updated_at;
  end if;
end $$;

do $$
declare
  unmatched text;
begin
  select string_agg(distinct listed.name, ', ') into unmatched
  from public.venues v
  cross join lateral unnest(v.supported_layouts) as listed(name)
  where not exists (select 1 from public.room_layouts r where r.name = listed.name);
  if unmatched is not null then
    raise exception 'These venue layouts match no room_layouts row: %', unmatched;
  end if;
end $$;

-- ============================================================
-- 3. A venue may only list layouts that exist
-- ============================================================

create or replace function public.venues_check_supported_layouts() returns trigger
language plpgsql as $$
declare
  unknown text;
begin
  select listed.name into unknown
  from unnest(new.supported_layouts) as listed(name)
  where not exists (select 1 from public.room_layouts r where r.name = listed.name)
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
-- 4. Renames and permanent deletes reach venues' lists
-- ============================================================
-- (Events and pending change requests follow a rename through
-- after_room_layout_rename, in the previous migration.)

create or replace function public.after_room_layout_rename_venues() returns trigger
language plpgsql as $$
begin
  update public.venues
  set supported_layouts = array_replace(supported_layouts, old.name::text, new.name::text)
  where old.name::text = any (supported_layouts);
  return null;
end $$;

drop trigger if exists trg_room_layouts_after_rename_venues on public.room_layouts;
create trigger trg_room_layouts_after_rename_venues
  after update of name on public.room_layouts
  for each row when (old.name is distinct from new.name)
  execute function public.after_room_layout_rename_venues();

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

-- Rollback intent (manual; no down-migration tooling yet):
--   drop trigger if exists trg_venues_check_supported_layouts on public.venues;
--   drop trigger if exists trg_room_layouts_after_rename_venues on public.room_layouts;
--   drop trigger if exists trg_room_layouts_after_delete on public.room_layouts;
--   drop function if exists public.venues_check_supported_layouts, public.after_room_layout_rename_venues,
--     public.after_room_layout_delete;
