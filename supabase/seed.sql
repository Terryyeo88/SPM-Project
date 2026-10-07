-- ConnectSphere seed data: 3 Event Coordinators, 1 Event Coordinator Lead,
-- 1 Event Organizer, 3 events.
-- Paste this whole file into the Supabase SQL Editor and run it.
--
-- NOTE: this inserts rows directly into auth.users to satisfy the
-- profiles -> auth.users foreign key. That's a common local-dev seeding
-- shortcut, not the officially supported way to create users (that's the
-- dashboard or Admin API) -- these accounts exist purely so events have
-- real coordinator_id/organizer_id rows to reference for testing, not
-- for actually logging in through whatever auth flow gets built later.
-- Safe to re-run: every insert is guarded by an existence check.

create extension if not exists pgcrypto;

do $$
declare
  v_id uuid;
  coord1_id uuid;
  coord2_id uuid;
  coord3_id uuid;
  org1_id uuid;
begin
  -- Coordinator 1: Alice Tan
  select id into v_id from public.profiles where email = 'coordinator1@example.com';
  if v_id is null then
    v_id := gen_random_uuid();
    insert into auth.users (
      instance_id, id, aud, role, email, encrypted_password,
      email_confirmed_at, raw_app_meta_data, raw_user_meta_data,
      created_at, updated_at, confirmation_token, email_change,
      email_change_token_new, recovery_token
    ) values (
      '00000000-0000-0000-0000-000000000000', v_id, 'authenticated', 'authenticated',
      'coordinator1@example.com', crypt('Password123!', gen_salt('bf')), now(),
      '{"provider":"email","providers":["email"]}'::jsonb, '{}'::jsonb,
      now(), now(), '', '', '', ''
    );
    insert into public.profiles (id, name, email) values (v_id, 'Alice Tan', 'coordinator1@example.com');
  end if;
  insert into public.user_roles (user_id, role) values (v_id, 'event_coordinator') on conflict do nothing;
  coord1_id := v_id;

  -- Coordinator 2: Brandon Lee
  select id into v_id from public.profiles where email = 'coordinator2@example.com';
  if v_id is null then
    v_id := gen_random_uuid();
    insert into auth.users (
      instance_id, id, aud, role, email, encrypted_password,
      email_confirmed_at, raw_app_meta_data, raw_user_meta_data,
      created_at, updated_at, confirmation_token, email_change,
      email_change_token_new, recovery_token
    ) values (
      '00000000-0000-0000-0000-000000000000', v_id, 'authenticated', 'authenticated',
      'coordinator2@example.com', crypt('Password123!', gen_salt('bf')), now(),
      '{"provider":"email","providers":["email"]}'::jsonb, '{}'::jsonb,
      now(), now(), '', '', '', ''
    );
    insert into public.profiles (id, name, email) values (v_id, 'Brandon Lee', 'coordinator2@example.com');
  end if;
  insert into public.user_roles (user_id, role) values (v_id, 'event_coordinator') on conflict do nothing;
  coord2_id := v_id;

  -- Coordinator 3: Chloe Wong
  select id into v_id from public.profiles where email = 'coordinator3@example.com';
  if v_id is null then
    v_id := gen_random_uuid();
    insert into auth.users (
      instance_id, id, aud, role, email, encrypted_password,
      email_confirmed_at, raw_app_meta_data, raw_user_meta_data,
      created_at, updated_at, confirmation_token, email_change,
      email_change_token_new, recovery_token
    ) values (
      '00000000-0000-0000-0000-000000000000', v_id, 'authenticated', 'authenticated',
      'coordinator3@example.com', crypt('Password123!', gen_salt('bf')), now(),
      '{"provider":"email","providers":["email"]}'::jsonb, '{}'::jsonb,
      now(), now(), '', '', '', ''
    );
    insert into public.profiles (id, name, email) values (v_id, 'Chloe Wong', 'coordinator3@example.com');
  end if;
  insert into public.user_roles (user_id, role) values (v_id, 'event_coordinator') on conflict do nothing;
  coord3_id := v_id;

  -- Organizer 1: Derek Ong
  select id into v_id from public.profiles where email = 'organizer1@example.com';
  if v_id is null then
    v_id := gen_random_uuid();
    insert into auth.users (
      instance_id, id, aud, role, email, encrypted_password,
      email_confirmed_at, raw_app_meta_data, raw_user_meta_data,
      created_at, updated_at, confirmation_token, email_change,
      email_change_token_new, recovery_token
    ) values (
      '00000000-0000-0000-0000-000000000000', v_id, 'authenticated', 'authenticated',
      'organizer1@example.com', crypt('Password123!', gen_salt('bf')), now(),
      '{"provider":"email","providers":["email"]}'::jsonb, '{}'::jsonb,
      now(), now(), '', '', '', ''
    );
    insert into public.profiles (id, name, email) values (v_id, 'Derek Ong', 'organizer1@example.com');
  end if;
  insert into public.user_roles (user_id, role) values (v_id, 'event_organizer') on conflict do nothing;
  org1_id := v_id;

  -- Event Coordinator Lead: Grace Lim (Week 7 change #5). Assigns the
  -- submitted, unassigned requests below (Events B and C) to coordinators.
  select id into v_id from public.profiles where email = 'lead1@example.com';
  if v_id is null then
    v_id := gen_random_uuid();
    insert into auth.users (
      instance_id, id, aud, role, email, encrypted_password,
      email_confirmed_at, raw_app_meta_data, raw_user_meta_data,
      created_at, updated_at, confirmation_token, email_change,
      email_change_token_new, recovery_token
    ) values (
      '00000000-0000-0000-0000-000000000000', v_id, 'authenticated', 'authenticated',
      'lead1@example.com', crypt('Password123!', gen_salt('bf')), now(),
      '{"provider":"email","providers":["email"]}'::jsonb, '{}'::jsonb,
      now(), now(), '', '', '', ''
    );
    insert into public.profiles (id, name, email) values (v_id, 'Grace Lim', 'lead1@example.com');
  end if;
  insert into public.user_roles (user_id, role) values (v_id, 'event_coordinator_lead') on conflict do nothing;

  -- Event A: already assigned to coordinator1, on 2026-11-10.
  -- Tests that assignment logic correctly skips an occupied coordinator.
  if not exists (select 1 from public.events where name = 'Annual Tech Symposium') then
    insert into public.events (
      organizer_id, coordinator_id, name, description, purpose, status,
      preferred_start_date, expected_attendance, room_layout
    ) values (
      org1_id, coord1_id, 'Annual Tech Symposium',
      'A symposium on emerging tech trends.', 'Knowledge sharing', 'planning',
      '2026-11-10', 200, 'theatre'
    );
  end if;

  -- Event B: unassigned, SAME date as Event A -- should skip coordinator1.
  if not exists (select 1 from public.events where name = 'Product Launch Networking Night') then
    insert into public.events (
      organizer_id, coordinator_id, name, description, purpose, status,
      preferred_start_date, expected_attendance, room_layout
    ) values (
      org1_id, null, 'Product Launch Networking Night',
      'Networking event for a new product line.', 'Marketing', 'submitted',
      '2026-11-10', 100, 'networking'
    );
  end if;

  -- Event C: unassigned, open date -- the plain case.
  if not exists (select 1 from public.events where name = 'Team Building Workshop') then
    insert into public.events (
      organizer_id, coordinator_id, name, description, purpose, status,
      preferred_start_date, expected_attendance, room_layout
    ) values (
      org1_id, null, 'Team Building Workshop',
      'Half-day workshop for staff bonding.', 'Team building', 'submitted',
      '2026-10-05', 40, 'classroom'
    );
  end if;
end $$;

-- ============================================================
-- Venues (View Venue Catalogue, Nawaz, Sprint 1)
-- ============================================================
-- No auth.users/profiles involved -- venues aren't owned by anyone, so
-- these are plain inserts, each guarded by name so re-running this file
-- is still safe.

-- operating_hours_start/end (View Venue Availability Calendar, Nawaz,
-- Sprint 2, IS-11) added below the original Sprint 1 columns -- NOT
-- backfilled onto an existing row (the `where not exists` guard means a
-- venue already in the DB from before this migration keeps NULL hours
-- until re-seeded), matching backend/seed.py's own values for the same
-- four venues. venue_blocks and the demo venue_bookings rows that
-- exercise "tentatively held"/"confirmed"/"blocked" are intentionally
-- NOT duplicated here -- they need real event/profile ids to reference,
-- which this static SQL file has no way to look up the way
-- seed_venue_calendar_demo() in seed.py does; run that script for the
-- full calendar demo data.

insert into public.venues (name, location, capacity, facilities, accessibility_features, supported_layouts, status, operating_hours_start, operating_hours_end)
select 'Grand Ballroom', 'Main Building, Level 3', 300,
  array['microphone', 'projector', 'screen', 'wifi'],
  array['wheelchair_access', 'lift_access'],
  array['theatre', 'banquet', 'networking']::public.room_layout[],
  'available', '07:00', '23:59'
where not exists (select 1 from public.venues where name = 'Grand Ballroom');

insert into public.venues (name, location, capacity, facilities, accessibility_features, supported_layouts, status, operating_hours_start, operating_hours_end)
select 'Innovation Hub', 'Tech Wing, Level 1', 80,
  array['projector', 'screen', 'wifi'],
  array['wheelchair_access', 'removable_seats'],
  array['classroom', 'seminar', 'boardroom']::public.room_layout[],
  'available', '08:00', '20:00'
where not exists (select 1 from public.venues where name = 'Innovation Hub');

insert into public.venues (name, location, capacity, facilities, accessibility_features, supported_layouts, status, operating_hours_start, operating_hours_end)
select 'Executive Boardroom', 'Main Building, Level 5', 20,
  array['screen', 'wifi'],
  array['wheelchair_access'],
  array['boardroom']::public.room_layout[],
  'occupied', '08:00', '18:00'
where not exists (select 1 from public.venues where name = 'Executive Boardroom');

-- Riverside Pavilion deliberately gets no operating hours (NULL/NULL) --
-- same "no restriction recorded" case backend/seed.py's own comment on
-- this venue explains.
insert into public.venues (name, location, capacity, facilities, accessibility_features, supported_layouts, status)
select 'Riverside Pavilion', 'East Campus, Ground Floor', 150,
  array['microphone', 'wifi'],
  array['wheelchair_access', 'lift_access', 'extra_legroom_seats'],
  array['banquet', 'networking', 'seminar']::public.room_layout[],
  'maintenance'
where not exists (select 1 from public.venues where name = 'Riverside Pavilion');


-- ============================================================
-- Attendee Registration demo (Justin)
-- ============================================================
-- Three attendee accounts and one CONFIRMED request with two sessions, so
-- registration can be tested before the venue and equipment stories exist
-- to confirm an event the normal way. Both sessions hold 2 people
-- (expected_attendance), so the third attendee to register is waitlisted.
--
--   14:00 session -- registration already open
--   10:00 session -- registration opens 2 hours after this runs
--
-- FRESH EVERY RUN: the demo request (and, by cascade, every registration
-- for it) is deleted and recreated, dates relative to now -- so re-running
-- gives a clean slate to test on. Also removes the older demo request
-- ("Registration Demo: Tech Talk Series"). Nothing else is touched.
-- Inserted directly as `confirmed` (a seed shortcut): there are no
-- event_status_log rows for how it got there.
do $$
declare
  v_id uuid;
  v_org uuid;
  v_coord uuid;
  r record;
begin
  for r in
    select * from (values
      ('attendee1@example.com', 'Ethan Koh'),
      ('attendee2@example.com', 'Fiona Ng'),
      ('attendee3@example.com', 'Gavin Tan')
    ) as t(email, name)
  loop
    select id into v_id from public.profiles where email = r.email;
    if v_id is null then
      v_id := gen_random_uuid();
      insert into auth.users (
        instance_id, id, aud, role, email, encrypted_password,
        email_confirmed_at, raw_app_meta_data, raw_user_meta_data,
        created_at, updated_at, confirmation_token, email_change,
        email_change_token_new, recovery_token
      ) values (
        '00000000-0000-0000-0000-000000000000', v_id, 'authenticated', 'authenticated',
        r.email, crypt('Password123!', gen_salt('bf')), now(),
        '{"provider":"email","providers":["email"]}'::jsonb, '{}'::jsonb,
        now(), now(), '', '', '', ''
      );
      insert into public.profiles (id, name, email) values (v_id, r.name, r.email);
    end if;
    insert into public.user_roles (user_id, role) values (v_id, 'attendee') on conflict do nothing;
  end loop;

  select id into v_org from public.profiles where email = 'organizer1@example.com';
  select id into v_coord from public.profiles where email = 'coordinator2@example.com';

  -- Clean slate: registrations, status history and assignment log rows
  -- cascade with their events.
  delete from public.events
  where name in ('Registration Demo: Tech Talk Series', 'Registration Demo: Community Workshop');

  insert into public.events (
    organizer_id, coordinator_id, shared_event_id, name, description, purpose, status,
    preferred_start_date, preferred_end_date, preferred_start_time, preferred_end_time,
    expected_attendance, room_layout, accessibility_needs, equipment_needed,
    registration_needs, registration_start_datetime, registration_end_datetime, special_requests
  )
  select v_org, v_coord, shared.id, 'Registration Demo: Community Workshop',
    'A hands-on community workshop in two sessions. Open to the public.', 'Community outreach', 'confirmed',
    current_date + s.start_in, current_date + s.start_in, s.start_t, s.end_t,
    2, 'classroom', '[]'::jsonb, '{"equipment": []}'::jsonb,
    true, s.opens, ((current_date + s.start_in - 1)::text || ' 23:59:00+08')::timestamptz, ''
  from (select gen_random_uuid() as id) as shared,
    (values
      (30, time '14:00', time '16:00', now() - interval '1 day'),
      (37, time '10:00', time '12:00', now() + interval '2 hours')
    ) as s(start_in, start_t, end_t, opens);
end $$;
