-- ConnectSphere: profile contact details and communication preferences
-- Migration: profile_contact_preferences
-- Scope: IS-68, User contact and preferences. The Edit Profile wireframe's
-- Phone Number, Organisation (optional) and Communication Preferences
-- (Email notifications / SMS notifications), stored on public.profiles.
-- The signed-in user reads them through GET /me and writes their own
-- through PATCH /me/profile (app/me).
--
-- EXISTING ROWS ARE UNTOUCHED. Every new column is NULLABLE, with no
-- default and no backfill: `add column` without a default only changes
-- the catalogue, so no existing profile is rewritten, and NULL is a valid
-- value for each column, so every existing profile stays valid. NULL means
-- "not given yet" -- for the two preferences it is distinct from false
-- ("chose not to"), which is why they have no default either. Proven
-- against the real database by
-- backend/tests/test_profile_contact_integration.py.
--
-- Adding these columns activates two pieces of existing code, on purpose
-- (see docs/design-decisions.md, IS-68):
--   - registration_service._db_profile_organisation (select "*") now finds
--     an organisation to copy into a registration when the attendee ticks
--     "include organisation";
--   - frontend lib/registrations.js prefillFromProfile now prefills the
--     register form's phone, organisation and notification choices from
--     GET /me. With all four NULL, both behave exactly as before.
--
-- The two preferences are stored and read back, and nothing else reads
-- them: notifications are in-app only (IS-69) and each registration keeps
-- its own notify_email / notify_sms (20261005000000_registrations.sql).
-- See docs/open-questions.md (IS-68).

-- ============================================================
-- 1. Columns
-- ============================================================

alter table public.profiles
  add column if not exists phone text,
  add column if not exists organisation text,
  add column if not exists notify_email boolean,
  add column if not exists notify_sms boolean;

-- Blank is stored as NULL by the app, never as ''. Both checks pass on
-- NULL, so they hold for every existing row; adding them scans profiles
-- once but rewrites nothing. The full phone format is checked in the app
-- (same pattern as registrations); the database only refuses a blank or
-- absurd value.
alter table public.profiles
  drop constraint if exists profiles_phone_present,
  add constraint profiles_phone_present
    check (phone is null or (btrim(phone) <> '' and char_length(phone) <= 32));

alter table public.profiles
  drop constraint if exists profiles_organisation_present,
  add constraint profiles_organisation_present
    check (organisation is null or (btrim(organisation) <> '' and char_length(organisation) <= 200));

-- ============================================================
-- 2. Row Level Security -- reviewed, unchanged
-- ============================================================
-- RLS was already enabled on profiles (20260911120000_init_users_events.sql)
-- with one placeholder policy, "authenticated read profiles": any signed-in
-- user may SELECT every profile row through the publishable key. That now
-- includes these columns, so a signed-in user going around Flask can read
-- another user's phone number. Not changed here: narrowing that policy
-- changes what every other feature may read about people (names in the
-- coordinator pickers, attendee lists) and needs its own story. Logged in
-- docs/open-questions.md (IS-68).
--
-- No insert/update/delete policy, as before: only the backend writes, and
-- app/me/profile_service.py scopes every write to the caller's own id.

-- Rollback intent (manual; no down-migration tooling yet). Dropping the
-- columns deletes what users have saved; the registration prefill and the
-- organisation copy then go back to finding nothing:
--   alter table public.profiles drop constraint if exists profiles_organisation_present;
--   alter table public.profiles drop constraint if exists profiles_phone_present;
--   alter table public.profiles
--     drop column if exists notify_sms,
--     drop column if exists notify_email,
--     drop column if exists organisation,
--     drop column if exists phone;
