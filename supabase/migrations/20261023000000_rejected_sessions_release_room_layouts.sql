-- ConnectSphere: rejected sessions let go of a disabled room layout
-- Migration: rejected_sessions_release_room_layouts
-- Scope: IS-60 Venue Categories (room layouts are the venue categories).
-- A rejected session is with its organiser to fix and resubmit, like a
-- draft -- it is no longer "ongoing". So:
--
--   1. A rejected session no longer holds up permanently deleting a layout:
--      only events that aren't completed, cancelled or rejected do
--      (replaces before_room_layout_delete from 20261012000000_room_layouts.sql).
--   2. Disabling (soft-deleting) a layout clears it from rejected sessions
--      as well as drafts (replaces room_layout_soft_deleted from
--      20261012200000_clear_draft_layouts_on_soft_delete.sql).
--   3. A session rejected while its layout is disabled has it cleared at
--      that moment, and permanently deleting a layout clears it from any
--      rejected session still holding it -- so a rejected session never
--      keeps a layout that can't be chosen again.
--
-- Wherever a layout is cleared this way, events.room_layout_removed keeps
-- the name that was cleared, so the organiser's form can say why the field
-- is now empty ("... is no longer available"). It is cleared again as soon
-- as the session is given a layout. Completed and cancelled events are
-- untouched: they keep the name in room_layout, as before.
--
-- Not logged in event_logs: like the draft clearing it extends, this is the
-- database reacting to Venue Staff's change, with no user making the edit.

-- ============================================================
-- 1. events.room_layout_removed
-- ============================================================

alter table public.events add column if not exists room_layout_removed varchar;

comment on column public.events.room_layout_removed is
  'Name of the room layout cleared from this draft/rejected session because Venue Staff disabled or deleted it; null once a layout is chosen again.';

-- A layout chosen again clears the notice. Named to run after
-- trg_events_sync_room_layout (same-event triggers fire in name order), so
-- room_layout is already filled in when only room_layout_id was set.
create or replace function public.events_unflag_removed_room_layout() returns trigger
language plpgsql as $$
begin
  if new.room_layout is not null then
    new.room_layout_removed := null;
  end if;
  return new;
end $$;

drop trigger if exists trg_events_unflag_removed_room_layout on public.events;
create trigger trg_events_unflag_removed_room_layout
  before update of room_layout, room_layout_id on public.events
  for each row execute function public.events_unflag_removed_room_layout();

-- ============================================================
-- 2. Disabling clears the layout from drafts and rejected sessions
-- ============================================================

create or replace function public.room_layout_soft_deleted() returns trigger
language plpgsql as $$
begin
  update public.events
  set room_layout = null,
      room_layout_removed = room_layout
  where room_layout_id = new.room_layout_id
    and status in ('draft', 'rejected');
  return null;
end $$;

-- (trg_room_layouts_clear_drafts_on_soft_delete already calls this function.)

-- ============================================================
-- 3. A session rejected while its layout is disabled lets go of it
-- ============================================================
-- Sets both columns itself: trg_events_sync_room_layout only fires for
-- updates that name room_layout / room_layout_id, not status.

create or replace function public.events_release_disabled_layout_on_reject() returns trigger
language plpgsql as $$
begin
  if new.room_layout_id is not null and exists (
    select 1 from public.room_layouts r
    where r.room_layout_id = new.room_layout_id and not r.is_active
  ) then
    new.room_layout_removed := new.room_layout;
    new.room_layout := null;
    new.room_layout_id := null;
  end if;
  return new;
end $$;

drop trigger if exists trg_events_release_disabled_layout_on_reject on public.events;
create trigger trg_events_release_disabled_layout_on_reject
  before update of status on public.events
  for each row when (new.status = 'rejected' and old.status is distinct from 'rejected')
  execute function public.events_release_disabled_layout_on_reject();

-- ============================================================
-- 4. Permanent delete: rejected sessions don't count, and let go of it
-- ============================================================
-- Still refused unless soft-deleted (23514) and while any event that isn't
-- completed, cancelled or rejected uses it (23503). Rejected sessions still
-- holding it are cleared first; completed/cancelled keep the name (ON
-- DELETE SET NULL clears only room_layout_id).

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
    and e.status not in ('completed', 'cancelled', 'rejected');

  if live_events > 0 then
    raise exception 'Room layout "%" is still used by % event(s) that are not completed, cancelled or rejected.',
      old.name, live_events
      using errcode = 'foreign_key_violation';
  end if;

  update public.events
  set room_layout = null,
      room_layout_removed = room_layout
  where room_layout_id = old.room_layout_id
    and status = 'rejected';

  return old;
end $$;

-- (trg_room_layouts_before_delete already calls this function.)

-- Rollback intent (manual; no down-migration tooling yet): re-run the
-- previous definitions of room_layout_soft_deleted
-- (20261012200000_clear_draft_layouts_on_soft_delete.sql) and
-- before_room_layout_delete (20261012000000_room_layouts.sql), then:
--   drop trigger if exists trg_events_release_disabled_layout_on_reject on public.events;
--   drop trigger if exists trg_events_unflag_removed_room_layout on public.events;
--   drop function if exists public.events_release_disabled_layout_on_reject, public.events_unflag_removed_room_layout;
--   alter table public.events drop column if exists room_layout_removed;
