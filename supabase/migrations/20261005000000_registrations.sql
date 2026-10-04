-- ConnectSphere: attendee registrations
-- Migration: registrations
-- Scope: Attendee Registration (Justin). Acceptance criteria:
--   - register only for an event that is confirmed and enabled for registration
--   - register only during the permitted registration period
--   - provide the required registration information
--   - capacity available            -> registration recorded as `confirmed`
--   - capacity reached + waiting list -> registration recorded as `waitlisted`
-- Plus withdrawing / leaving the waiting list, from the attendee wireframe
-- and the Week 4 clarification ("Attendees can register, view status,
-- withdraw").
--
-- Decisions (see docs/design-decisions.md / docs/open-questions.md):
--   - Attendees register for a SESSION (one events row). The registration
--     window (registration_start/end_datetime) and registration_needs are
--     already per session, so registration is too.
--   - Capacity = the session's expected_attendance. NULL means no limit.
--   - Every session has a waiting list (Week 2/4 clarifications: "waiting
--     list supported", first come first served).
--   - Registration information, following the Edit Profile wireframe's
--     fields: email and phone (required), organisation (optional, only the
--     profile's own, which the attendee may include or leave out), which
--     notifications they want (email and/or SMS, at least one), and free-text
--     notes (optional). Name comes from the profile.
--   - Withdrawing frees the place for the FIRST waitlisted attendee, who is
--     moved up to confirmed in the same call.
--
-- Re-runnable: safe to run again on a database that already has an
-- earlier version of this file (it adds the newer columns, drops the
-- replaced one and replaces the functions).

do $$ begin
  create type public.registration_status as enum ('confirmed', 'waitlisted');
exception when duplicate_object then null;
end $$;

create table if not exists public.registrations (
  id uuid primary key default gen_random_uuid(),
  event_id uuid not null references public.events (id) on delete cascade,
  attendee_id uuid not null references public.profiles (id) on delete cascade,
  status public.registration_status not null,
  email text not null,
  phone text not null,
  organisation text,
  notify_email boolean not null default true,
  notify_sms boolean not null default false,
  notes text,
  registered_at timestamptz not null default now(),
  -- One registration per attendee per session.
  unique (event_id, attendee_id),
  constraint registrations_notify_at_least_one check (notify_email or notify_sms)
);

-- Upgrade a table created by an earlier version of this file.
alter table public.registrations add column if not exists email text;
update public.registrations r set email = p.email
  from public.profiles p where p.id = r.attendee_id and r.email is null;
alter table public.registrations alter column email set not null;
alter table public.registrations add column if not exists organisation text;
alter table public.registrations add column if not exists notify_email boolean not null default true;
alter table public.registrations add column if not exists notify_sms boolean not null default false;
do $$ begin
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'registrations' and column_name = 'communication_preference'
  ) then
    update public.registrations set notify_sms = true, notify_email = false
      where communication_preference = 'phone';
    alter table public.registrations drop column communication_preference;
  end if;
end $$;
do $$ begin
  alter table public.registrations add constraint registrations_notify_at_least_one
    check (notify_email or notify_sms);
exception when duplicate_object then null;
end $$;

-- Counting a session's confirmed places, and ordering its waiting list.
create index if not exists idx_registrations_event_status
  on public.registrations (event_id, status, registered_at);
create index if not exists idx_registrations_attendee on public.registrations (attendee_id);

-- RLS on with NO policies: nothing reaches this table through the anon or
-- authenticated keys at all. The Flask backend uses the service-role key
-- (which bypasses RLS) and does the per-role checks in app/authz. Stricter
-- than the placeholder "any authenticated user" policies on older tables,
-- which docs/open-questions.md flags for the RLS pass.
alter table public.registrations enable row level security;

-- Earlier versions of register_attendee.
drop function if exists public.register_attendee(uuid, uuid, text, text);
drop function if exists public.register_attendee(uuid, uuid, text, text, text, text);

-- register_attendee: decides confirmed vs waitlisted and inserts, as ONE
-- database call. Doing "count confirmed, then insert" from Python as two
-- requests would let two attendees racing for the last place both see it
-- free and both be confirmed. Here the session's events row is locked
-- (FOR UPDATE) first, so registrations for the same session queue up and
-- each sees the count the previous one left.
--
-- Returns jsonb {"outcome": ..., "registration": {...}} rather than raising,
-- so the backend can map each outcome to a clear message:
--   registered          -- inserted; registration.status is confirmed or waitlisted
--   not_found           -- no such session
--   not_open            -- session isn't confirmed, or registration isn't enabled
--   not_started         -- before registration_start_datetime
--   closed              -- after registration_end_datetime
--   already_registered  -- this attendee already has a registration for it
create or replace function public.register_attendee(
  p_event_id uuid,
  p_attendee_id uuid,
  p_email text,
  p_phone text,
  p_organisation text,
  p_notify_email boolean,
  p_notify_sms boolean,
  p_notes text default null
) returns jsonb
language plpgsql
as $$
declare
  v_event public.events%rowtype;
  v_confirmed integer;
  v_status public.registration_status;
  v_row public.registrations%rowtype;
begin
  select * into v_event from public.events where id = p_event_id for update;
  if not found then
    return jsonb_build_object('outcome', 'not_found');
  end if;

  if v_event.status <> 'confirmed' or v_event.registration_needs is not true then
    return jsonb_build_object('outcome', 'not_open');
  end if;
  if v_event.registration_start_datetime is not null and now() < v_event.registration_start_datetime then
    return jsonb_build_object('outcome', 'not_started');
  end if;
  if v_event.registration_end_datetime is not null and now() > v_event.registration_end_datetime then
    return jsonb_build_object('outcome', 'closed');
  end if;

  if exists (
    select 1 from public.registrations where event_id = p_event_id and attendee_id = p_attendee_id
  ) then
    return jsonb_build_object('outcome', 'already_registered');
  end if;

  select count(*) into v_confirmed
  from public.registrations
  where event_id = p_event_id and status = 'confirmed';

  if v_event.expected_attendance is null or v_confirmed < v_event.expected_attendance then
    v_status := 'confirmed';
  else
    v_status := 'waitlisted';
  end if;

  insert into public.registrations (
    event_id, attendee_id, status, email, phone, organisation, notify_email, notify_sms, notes
  ) values (
    p_event_id, p_attendee_id, v_status, p_email, p_phone, nullif(btrim(p_organisation), ''),
    p_notify_email, p_notify_sms, nullif(btrim(p_notes), '')
  )
  returning * into v_row;

  return jsonb_build_object('outcome', 'registered', 'registration', to_jsonb(v_row));
end;
$$;

-- withdraw_registration: the attendee withdraws (or leaves the waiting
-- list). If they held a confirmed place and the session is still confirmed,
-- the first waitlisted attendee (first come, first served) is moved up to
-- confirmed in the same call, under the same session lock as registering,
-- so a withdrawal and a new registration can't both take the freed place.
--
-- Returns jsonb {"outcome": ..., "promoted_registration_id": uuid|null}:
--   withdrawn       -- removed
--   not_registered  -- the attendee has no registration for this session
--   started         -- the session has already started (too late to withdraw)
create or replace function public.withdraw_registration(
  p_event_id uuid,
  p_attendee_id uuid
) returns jsonb
language plpgsql
as $$
declare
  v_event public.events%rowtype;
  v_removed public.registrations%rowtype;
  v_promoted uuid;
begin
  select * into v_event from public.events where id = p_event_id for update;
  if not found then
    return jsonb_build_object('outcome', 'not_registered');
  end if;
  if v_event.preferred_start_date is not null and v_event.preferred_start_date <= current_date then
    if exists (select 1 from public.registrations where event_id = p_event_id and attendee_id = p_attendee_id) then
      return jsonb_build_object('outcome', 'started');
    end if;
  end if;

  delete from public.registrations
  where event_id = p_event_id and attendee_id = p_attendee_id
  returning * into v_removed;
  if not found then
    return jsonb_build_object('outcome', 'not_registered');
  end if;

  if v_removed.status = 'confirmed' and v_event.status = 'confirmed' then
    update public.registrations set status = 'confirmed'
    where id = (
      select id from public.registrations
      where event_id = p_event_id and status = 'waitlisted'
      order by registered_at, id
      limit 1
    )
    returning id into v_promoted;
  end if;

  return jsonb_build_object('outcome', 'withdrawn', 'promoted_registration_id', v_promoted);
end;
$$;

-- Only the backend (service role) may call them.
revoke execute on function public.register_attendee(uuid, uuid, text, text, text, boolean, boolean, text) from public;
revoke execute on function public.withdraw_registration(uuid, uuid) from public;
do $$ begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    revoke execute on function public.register_attendee(uuid, uuid, text, text, text, boolean, boolean, text) from anon;
    revoke execute on function public.withdraw_registration(uuid, uuid) from anon;
  end if;
  if exists (select 1 from pg_roles where rolname = 'authenticated') then
    revoke execute on function public.register_attendee(uuid, uuid, text, text, text, boolean, boolean, text)
      from authenticated;
    revoke execute on function public.withdraw_registration(uuid, uuid) from authenticated;
  end if;
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    grant execute on function public.register_attendee(uuid, uuid, text, text, text, boolean, boolean, text)
      to service_role;
    grant execute on function public.withdraw_registration(uuid, uuid) to service_role;
  end if;
end $$;
