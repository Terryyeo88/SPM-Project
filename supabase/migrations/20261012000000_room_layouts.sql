-- ConnectSphere: room layouts managed by Venue Staff
-- Migration: room_layouts
-- Scope: room layouts (theatre, classroom, ...) were the fixed
-- public.room_layout enum. Venue Staff must now be able to add, rename and
-- delete them, which an enum can't support without a migration per change
-- (and a value can never be removed from a Postgres enum at all), so they
-- become rows in public.room_layouts.
--
-- CONVERGES, like 20260927000000_reconcile_events_with_live.sql: the live
-- database already had part of this made by hand (a room_layouts table
-- with rows, events.room_layout as varchar with no enum, room_layout_id and
-- room_layout_name on events). Every step here checks what already exists,
-- so this file brings both an empty database and the live one to the same
-- end state, and re-running it changes nothing.
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
-- events.room_layout stays (as plain text) and always holds the layout's
-- NAME; events.room_layout_id holds the reference. A trigger keeps the two
-- in step (section 5). When a layout is hard-deleted, ON DELETE SET NULL
-- clears room_layout_id and the name stays in room_layout -- so a separate
-- room_layout_name copy isn't needed (one made by hand is folded into
-- room_layout and dropped, section 2), and everything that reads
-- room_layout as a name (the API, event_logs and event_change_requests
-- snapshots, venue suitability checks) is unchanged.
--
-- Venues keep listing their layouts by name in venues.supported_layouts
-- (converted to text[] here); 20261012100000_venue_supported_layouts.sql
-- keeps those names in step with room_layouts.

-- ============================================================
-- 1. Room layouts
-- ============================================================

create table if not exists public.room_layouts (
  room_layout_id uuid not null default gen_random_uuid(),
  name varchar not null,
  is_active boolean not null default true,
  constraint room_layouts_pkey primary key (room_layout_id)
);

-- Whatever a hand-made table lacks.
alter table public.room_layouts
  add column if not exists is_active boolean not null default true,
  add column if not exists created_at timestamptz not null default now(),
  add column if not exists updated_at timestamptz not null default now();

do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'room_layouts_name_not_blank' and conrelid = 'public.room_layouts'::regclass
  ) then
    alter table public.room_layouts add constraint room_layouts_name_not_blank check (btrim(name) <> '');
  end if;
end $$;

-- Unique regardless of case, so "Theatre" can't be added beside "theatre".
-- Replaces a plain unique(name) a hand-made table may have.
alter table public.room_layouts drop constraint if exists room_layouts_name_key;
drop index if exists public.room_layouts_name_key;
create unique index if not exists room_layouts_name_lower_key on public.room_layouts (lower(name));

drop trigger if exists trg_room_layouts_updated_at on public.room_layouts;
create trigger trg_room_layouts_updated_at
  before update on public.room_layouts
  for each row execute function public.set_updated_at();

-- ============================================================
-- 2. events.room_layout and venues.supported_layouts -> text; drop the enum
-- ============================================================
-- Only converted where it isn't varchar already: once section 5's trigger
-- exists it depends on the column, so re-running an unconditional type
-- change would fail. Same for the venue array (the next migration's
-- trigger depends on it), which may also not exist at all; it's only
-- converted if it exists and isn't text[] yet.

do $$
begin
  if (
    select data_type from information_schema.columns
    where table_schema = 'public' and table_name = 'events' and column_name = 'room_layout'
  ) <> 'character varying' then
    alter table public.events
      alter column room_layout type varchar using room_layout::text;
  end if;
end $$;

do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'venues' and column_name = 'supported_layouts'
      and udt_name <> '_text'
  ) then
    alter table public.venues
      alter column supported_layouts drop default,
      alter column supported_layouts type text[] using supported_layouts::text[],
      alter column supported_layouts set default '{}';
  end if;
end $$;

drop type if exists public.room_layout;

-- A hand-made events.room_layout_name is folded into room_layout (where
-- room_layout is empty) and dropped -- room_layout already is the name.
-- updated_at is paused: this isn't an edit anyone made to the event.
do $$ begin
  if exists (select 1 from pg_trigger where tgname = 'trg_events_updated_at' and tgrelid = 'public.events'::regclass) then
    alter table public.events disable trigger trg_events_updated_at;
  end if;
end $$;

do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'events' and column_name = 'room_layout_name'
  ) then
    execute 'update public.events set room_layout = room_layout_name
             where room_layout is null and room_layout_name is not null';
    alter table public.events drop column room_layout_name;
  end if;
end $$;

do $$ begin
  if exists (select 1 from pg_trigger where tgname = 'trg_events_updated_at' and tgrelid = 'public.events'::regclass) then
    alter table public.events enable trigger trg_events_updated_at;
  end if;
end $$;

-- ============================================================
-- 3. Every layout name already in use becomes a room layout
-- ============================================================
-- The six the original enum defined, every name an event holds, and every
-- name a venue still lists. A name that only differs in case from an
-- existing layout is skipped (the unique index), and linked to it below.

insert into public.room_layouts (name)
select distinct on (lower(layout)) layout
from (
  select unnest(array['theatre', 'classroom', 'boardroom', 'seminar', 'banquet', 'networking']) as layout
  union all
  select room_layout from public.events where room_layout is not null
) as layouts
where btrim(layout) <> ''
order by lower(layout), layout
on conflict do nothing;

do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'venues' and column_name = 'supported_layouts'
  ) then
    execute $insert$
      insert into public.room_layouts (name)
      select distinct on (lower(layout)) layout
      from (select unnest(supported_layouts) as layout from public.venues) as layouts
      where btrim(layout) <> ''
      order by lower(layout), layout
      on conflict do nothing
    $insert$;
  end if;
end $$;

-- ============================================================
-- 4. events.room_layout_id, and point every event at its layout
-- ============================================================
-- The foreign key is (re)created with ON DELETE SET NULL whatever it was
-- before (a hand-made one may restrict deletes, which would block every
-- permanent delete forever).

alter table public.events add column if not exists room_layout_id uuid;
alter table public.events drop constraint if exists events_room_layout_id_fkey;
alter table public.events
  add constraint events_room_layout_id_fkey
  foreign key (room_layout_id) references public.room_layouts (room_layout_id) on delete set null;

create index if not exists idx_events_room_layout_id on public.events (room_layout_id);

do $$ begin
  if exists (select 1 from pg_trigger where tgname = 'trg_events_updated_at' and tgrelid = 'public.events'::regclass) then
    alter table public.events disable trigger trg_events_updated_at;
  end if;
end $$;

-- Already linked: the name follows the linked layout.
update public.events e
set room_layout = r.name
from public.room_layouts r
where r.room_layout_id = e.room_layout_id
  and e.room_layout is distinct from r.name;

-- Not linked yet: link by name, ignoring case, and use the layout's spelling.
update public.events e
set room_layout_id = r.room_layout_id,
    room_layout = r.name
from public.room_layouts r
where e.room_layout_id is null
  and lower(r.name) = lower(e.room_layout);

do $$ begin
  if exists (select 1 from pg_trigger where tgname = 'trg_events_updated_at' and tgrelid = 'public.events'::regclass) then
    alter table public.events enable trigger trg_events_updated_at;
  end if;
end $$;

do $$
declare
  unmatched text;
begin
  select string_agg(distinct room_layout, ', ') into unmatched
  from public.events
  where room_layout is not null and room_layout_id is null;
  if unmatched is not null then
    raise exception 'These event room layouts match no room_layouts row: %', unmatched;
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
-- 7. Renames reach events and pending change requests
-- ============================================================
-- A rename updates the name on every event still linked to the layout, and
-- in PENDING change requests (which name the layout in JSON, so would
-- otherwise ask for a name that no longer exists and fail at approval).
-- Decided change requests and event_logs are history and keep the name as
-- it was. (Venues' lists follow through their own trigger -- next migration.)

create or replace function public.after_room_layout_rename() returns trigger
language plpgsql as $$
begin
  update public.events
  set room_layout = new.name
  where room_layout_id = new.room_layout_id;

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

-- ============================================================
-- 8. Row Level Security
-- ============================================================
-- Same stance as every other table: Flask's service-role key does the
-- real per-role check in app/authz (Venue Staff manage, see
-- rule_room_layout_manage); RLS is defence in depth only. Read-only for
-- authenticated users, no write policy.

alter table public.room_layouts enable row level security;

drop policy if exists "authenticated read room_layouts" on public.room_layouts;
create policy "authenticated read room_layouts" on public.room_layouts
  for select using (auth.role() = 'authenticated');

-- Rollback intent (manual; no down-migration tooling yet). The enum can
-- only come back while every room_layouts name is one of its six values:
--   drop trigger if exists trg_events_sync_room_layout on public.events;
--   drop trigger if exists trg_room_layouts_after_rename on public.room_layouts;
--   drop trigger if exists trg_room_layouts_before_delete on public.room_layouts;
--   alter table public.events drop column room_layout_id;
--   drop table public.room_layouts;
--   drop function if exists public.events_sync_room_layout, public.before_room_layout_delete,
--     public.after_room_layout_rename;
