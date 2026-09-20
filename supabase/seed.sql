-- ConnectSphere seed data: 3 Event Coordinators, 1 Event Organizer, 3 events.
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
