-- ConnectSphere: profile contact rules
-- Migration: profile_contact_rules
-- Scope: IS-68, tightening 20261030000000_profile_contact_preferences.sql to
-- the acceptance criteria agreed with Justin (31 Oct):
--   - phone is optional; when given it is +65 followed by 8 digits, stored
--     as '+6591234567' (no spaces)
--   - communication preferences: email selected by default, at least one of
--     email / SMS always on
--   - SMS can only be on when a phone number is saved
--   - organisation is read-only (not editable through PATCH /me/profile) --
--     an app rule, nothing changes in the schema for it
--
-- The earlier migration left the preferences NULL ("not chosen yet"). They
-- become NOT NULL with defaults (email on, SMS off), so a NULL is no longer
-- possible and "not chosen" simply reads as the default.
--
-- EXISTING ROWS, in this order:
--   1. phone: spaces and hyphens removed; 8 digits get '+65' in front;
--      '65' + 8 digits gets '+'. Anything that still isn't +65 + 8 digits
--      can't be fixed safely and is cleared to NULL.
--   2. preferences: NULL email -> true, NULL SMS -> false.
--   3. SMS turned off where there is no phone (including phones cleared in 1).
--   4. email turned on where both are off.
-- After that every row satisfies the new checks, which are then added.
--
-- Re-runnable: every step is idempotent.

-- ============================================================
-- 1. Phone: normalise, then the +65 format check
-- ============================================================

-- Replaced by profiles_phone_sg, which also refuses blank text.
alter table public.profiles drop constraint if exists profiles_phone_present;

update public.profiles
set phone = case
    when regexp_replace(phone, '[[:space:]-]', '', 'g') ~ '^\+65[0-9]{8}$'
      then regexp_replace(phone, '[[:space:]-]', '', 'g')
    when regexp_replace(phone, '[[:space:]-]', '', 'g') ~ '^65[0-9]{8}$'
      then '+' || regexp_replace(phone, '[[:space:]-]', '', 'g')
    when regexp_replace(phone, '[[:space:]-]', '', 'g') ~ '^[0-9]{8}$'
      then '+65' || regexp_replace(phone, '[[:space:]-]', '', 'g')
    else null
  end
where phone is not null
  and phone !~ '^\+65[0-9]{8}$';

alter table public.profiles
  drop constraint if exists profiles_phone_sg,
  add constraint profiles_phone_sg
    check (phone is null or phone ~ '^\+65[0-9]{8}$');

-- ============================================================
-- 2. Preferences: defaults, NOT NULL, at least one, SMS needs phone
-- ============================================================

update public.profiles
set notify_email = coalesce(notify_email, true),
    notify_sms = coalesce(notify_sms, false)
where notify_email is null or notify_sms is null;

update public.profiles set notify_sms = false where notify_sms and phone is null;

update public.profiles set notify_email = true where not notify_email and not notify_sms;

alter table public.profiles
  alter column notify_email set default true,
  alter column notify_email set not null,
  alter column notify_sms set default false,
  alter column notify_sms set not null;

alter table public.profiles
  drop constraint if exists profiles_notify_at_least_one,
  add constraint profiles_notify_at_least_one
    check (notify_email or notify_sms);

alter table public.profiles
  drop constraint if exists profiles_sms_needs_phone,
  add constraint profiles_sms_needs_phone
    check (not notify_sms or phone is not null);

-- Rollback intent (manual; no down-migration tooling yet). Puts the columns
-- back to the earlier migration's shape; the normalised phones and filled-in
-- preferences stay as they are:
--   alter table public.profiles drop constraint if exists profiles_sms_needs_phone;
--   alter table public.profiles drop constraint if exists profiles_notify_at_least_one;
--   alter table public.profiles drop constraint if exists profiles_phone_sg;
--   alter table public.profiles
--     alter column notify_email drop not null, alter column notify_email drop default,
--     alter column notify_sms drop not null, alter column notify_sms drop default;
--   alter table public.profiles add constraint profiles_phone_present
--     check (phone is null or (btrim(phone) <> '' and char_length(phone) <= 32));
