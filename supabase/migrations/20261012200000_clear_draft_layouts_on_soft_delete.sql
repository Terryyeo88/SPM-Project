-- ConnectSphere: soft-deleting a room layout clears it from drafts
-- Migration: clear_draft_layouts_on_soft_delete
-- Scope: when Venue Staff soft-delete a room layout (is_active true ->
-- false), every DRAFT event using it has its layout cleared (room_layout
-- and room_layout_id both NULL), so the organiser picks a layout that is
-- still offered before submitting.
--
-- Only drafts: every other status has already been submitted, and keeps
-- the layout it was submitted with (see 20261012000000_room_layouts.sql --
-- a session keeps a soft-deleted layout; submitting needs an active one).
-- Restoring the layout does not put it back on those drafts: nothing
-- records which drafts had it.
--
-- Setting room_layout to NULL is enough: trg_events_sync_room_layout clears
-- room_layout_id with it. Draft edits aren't written to event_logs (see
-- app.events.routes._log_direct_edit), so neither is this.

create or replace function public.room_layout_soft_deleted() returns trigger
language plpgsql as $$
begin
  update public.events
  set room_layout = null
  where room_layout_id = new.room_layout_id
    and status = 'draft';
  return null;
end $$;

drop trigger if exists trg_room_layouts_clear_drafts_on_soft_delete on public.room_layouts;
create trigger trg_room_layouts_clear_drafts_on_soft_delete
  after update of is_active on public.room_layouts
  for each row when (old.is_active and not new.is_active)
  execute function public.room_layout_soft_deleted();

-- Rollback intent (manual):
--   drop trigger if exists trg_room_layouts_clear_drafts_on_soft_delete on public.room_layouts;
--   drop function if exists public.room_layout_soft_deleted();
