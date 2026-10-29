-- ConnectSphere: in-app notifications
-- Migration: notifications
-- Scope: IS-69, Notification System infrastructure. Every story that said
-- "the coordinator is notified" / "sent to the Event Coordinator" so far
-- called a print() placeholder (_notify_* in coordinator_service,
-- booking_service, equipment_service, safety_service, venue_service --
-- see docs/open-questions.md). This table is where those notifications
-- now land, and what the bell in the web app reads.
--
-- In-app only. The container diagram (docs/c4/02-container.puml) has the
-- API owning "in-app notifications" and the SPA showing them; email/SMS
-- delivery is deferred (docs/open-questions.md, IS-69).
--
-- One row per RECIPIENT: a notification fanned out to every Safety Officer
-- is one row each, so each person's read state is their own.
--
-- entity_type / entity_id point at what the notification is about (an
-- event session, a safety review) so the app can link to it. It is
-- POLYMORPHIC and deliberately has NO foreign key: one column can't
-- reference several tables. The cost is that deleting the entity leaves
-- the notification pointing at nothing; the app treats a dangling link as
-- plain text (see docs/design-decisions.md, IS-69).

-- ============================================================
-- 1. Notifications
-- ============================================================

create table if not exists public.notifications (
  id uuid primary key default gen_random_uuid(),

  -- Deleting a user deletes their notifications with them (nobody else
  -- can read them).
  recipient_id uuid not null references public.profiles (id) on delete cascade,

  -- What happened, e.g. 'coordinator_assigned', 'venue_booking_confirmed'.
  -- Text, not an enum: the vocabulary lives in
  -- app/notifications/notification_service.py, so a new notification
  -- type doesn't need a migration (and an enum value can never be removed).
  type text not null,
  message text not null,

  entity_type text,
  entity_id uuid,

  -- NULL = unread. Set once, by the recipient (the app conditions the
  -- update on it still being NULL, so the first read time is kept).
  read_at timestamptz,

  created_at timestamptz not null default now(),

  constraint notifications_type_present check (btrim(type) <> ''),
  constraint notifications_message_present check (btrim(message) <> ''),
  -- A link is both halves or neither.
  constraint notifications_entity_complete check ((entity_type is null) = (entity_id is null))
);

-- The bell's list: one recipient's notifications, newest first.
create index if not exists idx_notifications_recipient_created
  on public.notifications (recipient_id, created_at desc);

-- The bell's count: one recipient's unread notifications.
create index if not exists idx_notifications_recipient_unread
  on public.notifications (recipient_id) where read_at is null;

-- ============================================================
-- 2. Row Level Security
-- ============================================================
-- Flask's service-role key bypasses RLS and does the real check in
-- app/authz (a recipient sees and marks only their own). Unlike the
-- placeholder "any authenticated user" policies on older tables, this
-- read policy is scoped to the recipient: a notification names events and
-- people, and a signed-in caller going around Flask must not be able to
-- read anyone else's. No insert/update/delete policy: only the backend
-- writes. Proven, and mutation-tested, by
-- backend/tests/test_notifications_integration.py.

alter table public.notifications enable row level security;

drop policy if exists "recipient reads own notifications" on public.notifications;
create policy "recipient reads own notifications" on public.notifications
  for select using (recipient_id = auth.uid());

-- Rollback intent (manual; no down-migration tooling yet):
--   drop policy if exists "recipient reads own notifications" on public.notifications;
--   drop index if exists idx_notifications_recipient_unread;
--   drop index if exists idx_notifications_recipient_created;
--   drop table if exists public.notifications;
