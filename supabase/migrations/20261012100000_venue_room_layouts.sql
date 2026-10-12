-- ConnectSphere: venues reference room layouts through a join table
-- Migration: venue_room_layouts
-- Scope: venues.supported_layouts was a text[] of layout names (see
-- 20261012000000_room_layouts.sql), kept in step with room_layouts by
-- triggers because an array can't carry a foreign key. Which layouts a
-- venue supports now lives in public.venue_room_layouts, one row per
-- (venue, layout), with real foreign keys to both:
--   - a venue can only list layouts that exist (FK, no trigger needed)
--   - a rename needs nothing: venues reference the layout, not its name
--   - a permanent delete of a layout removes it from every venue
--     (ON DELETE CASCADE) -- still only possible once the layout is
--     soft-deleted and no live event uses it (room_layouts' own trigger)
-- Venue Staff set a venue's layouts through POST /venues/<id>/room-layouts.
-- The API still returns a venue's layouts as `supported_layouts` (names),
-- so existing readers are unchanged.

-- ============================================================
-- 1. The join table
-- ============================================================

create table if not exists public.venue_room_layouts (
  venue_id uuid not null references public.venues (id) on delete cascade,
  room_layout_id uuid not null references public.room_layouts (room_layout_id) on delete cascade,
  created_at timestamptz not null default now(),
  constraint venue_room_layouts_pkey primary key (venue_id, room_layout_id)
);

-- The primary key covers lookups by venue; this covers lookups by layout
-- (the cascade on a layout's delete, and "which venues offer X").
create index if not exists idx_venue_room_layouts_room_layout_id
  on public.venue_room_layouts (room_layout_id);

-- ============================================================
-- 2. Move every venue's current layouts across
-- ============================================================
-- Every name in supported_layouts matches a room_layouts row (the previous
-- migration's venues_check_supported_layouts trigger guaranteed it); the
-- check below proves nothing was dropped on the way.

insert into public.venue_room_layouts (venue_id, room_layout_id)
select v.id, r.room_layout_id
from public.venues v
cross join lateral unnest(v.supported_layouts) as layout(name)
join public.room_layouts r on r.name = layout.name
on conflict do nothing;

do $$
begin
  if exists (
    select 1
    from public.venues v
    cross join lateral unnest(v.supported_layouts) as layout(name)
    where not exists (
      select 1
      from public.venue_room_layouts vrl
      join public.room_layouts r using (room_layout_id)
      where vrl.venue_id = v.id and r.name = layout.name
    )
  ) then
    raise exception 'A venue layout did not match any room_layouts row; nothing was changed.';
  end if;
end $$;

-- ============================================================
-- 3. Retire the array and the triggers that kept it in step
-- ============================================================

drop trigger if exists trg_venues_check_supported_layouts on public.venues;
drop function if exists public.venues_check_supported_layouts();

drop trigger if exists trg_room_layouts_after_delete on public.room_layouts;
drop function if exists public.after_room_layout_delete();

-- Same as before minus the venues update: venues now follow a rename
-- through the foreign key.
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

alter table public.venues drop column supported_layouts;

-- ============================================================
-- 4. Row Level Security
-- ============================================================
-- Same stance as every other table: Flask's service-role key does the real
-- per-role check (rule_venue_edit_layouts: Venue Staff); RLS is defence in
-- depth only. Read-only for authenticated users, no write policy.

alter table public.venue_room_layouts enable row level security;

create policy "authenticated read venue_room_layouts" on public.venue_room_layouts
  for select using (auth.role() = 'authenticated');

-- Rollback intent (manual; no down-migration tooling yet):
--   alter table public.venues add column supported_layouts text[] not null default '{}';
--   update public.venues v set supported_layouts = coalesce((
--     select array_agg(r.name order by r.name) from public.venue_room_layouts vrl
--     join public.room_layouts r using (room_layout_id) where vrl.venue_id = v.id), '{}');
--   drop table public.venue_room_layouts;
--   then re-run section 7's venue triggers from 20261012000000_room_layouts.sql.
