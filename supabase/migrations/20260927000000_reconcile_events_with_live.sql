-- ConnectSphere: reconcile migration files with the live database
-- Migration: reconcile_events_with_live
--
-- WHAT DRIFTED: six columns on public.events existed in the live database
-- with no migration file behind them. The previous migrations declared:
--   - accessibility_needs  text     -- live is jsonb
--   - registration_needs   text     -- live is boolean
--   - equipment_needed              -- absent; live is jsonb
--   - shared_event_id               -- absent; live is uuid (no FK)
--   - registration_start_datetime   -- absent; live is timestamptz
--   - registration_end_datetime     -- absent; live is timestamptz
-- All six are nullable with no default, both here and live. Every other
-- table, column, type, nullability, default, FK and enum matched on
-- comparison (live schema read through PostgREST's OpenAPI endpoint on
-- 2026-09-27).
--
-- SOURCE OF TRUTH: the live database, not the files. Application code
-- (app.events.event_service, CreateEventView/EventDetailsView) already
-- reads and writes the live shapes, and live rows already hold jsonb
-- lists / booleans in these columns. See docs/design-decisions.md,
-- "Live schema was the source of truth when reconciling migrations".
--
-- WHY THIS FILE EXISTS: to make a fresh environment (`supabase db reset`,
-- or applying every file in order by hand) produce the schema production
-- already has. Before this file, a fresh environment had no
-- equipment_needed column, and event creation failed against it.
--
-- HOW IT HAPPENED: these changes were applied dashboard-first and the
-- migration file was never written (20260920000000_event_date_range.sql
-- was the same pattern, but it was caught and written up afterwards).
-- The team rule from here on: a schema change goes into a migration file
-- first, and only then gets applied. Never dashboard-first. See README,
-- "Apply migrations".
--
-- SAFE AGAINST LIVE: every statement below is guarded, and against the
-- live database it's a no-op. `add column if not exists` skips existing
-- columns. Each type change runs only when information_schema says the
-- column isn't already the target type. Nothing is dropped.

-- ============================================================
-- 1. Type changes (load-bearing -- used by app.events.event_service)
-- ============================================================

do $$
begin
  -- accessibility_needs: text -> jsonb. event_service writes a list of
  -- {"item", "quantity"?, "notes"?} objects here (see
  -- _validate_item_list). The conversion helper keeps any pre-existing
  -- text that isn't valid JSON as a JSON string rather than failing or
  -- discarding it -- lossless, though the app will then reject that row
  -- on edit until someone fixes it by hand. Blank text becomes NULL.
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'events'
      and column_name = 'accessibility_needs' and data_type <> 'jsonb'
  ) then
    create function pg_temp.reconcile_text_to_jsonb(value text)
    returns jsonb language plpgsql immutable as $f$
    begin
      if value is null or btrim(value) = '' then
        return null;
      end if;
      return value::jsonb;
    exception when others then
      return to_jsonb(value);
    end;
    $f$;

    alter table public.events alter column accessibility_needs type jsonb using pg_temp.reconcile_text_to_jsonb(accessibility_needs);
  end if;

  -- registration_needs: text -> boolean. event_service requires a real
  -- bool here. Uses Postgres's own text->boolean cast, which accepts
  -- true/false/t/f/yes/no/y/n/on/off/1/0 (case-insensitive) and RAISES on
  -- anything else -- deliberately: failing the migration loudly beats
  -- silently turning unrecognised data into NULL. Blank text becomes NULL.
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'public' and table_name = 'events'
      and column_name = 'registration_needs' and data_type <> 'boolean'
  ) then
    alter table public.events alter column registration_needs type boolean using nullif(btrim(registration_needs), '')::boolean;
  end if;
end;
$$;

-- ============================================================
-- 2. Missing column (load-bearing)
-- ============================================================

-- equipment_needed: jsonb, shaped {"equipment": [{"item", "quantity"}]}
-- by event_service._to_database_payload / _draft_payload.
alter table public.events
  add column if not exists equipment_needed jsonb;

-- ============================================================
-- 3. Missing columns (ORPHANS -- included only for parity)
-- ============================================================
-- None of the three columns below is referenced by any code, test,
-- migration or doc on any branch or in any commit in this repository.
-- Every live row has NULL in all three (7 rows checked 2026-09-27). They
-- are added here ONLY so a fresh environment matches live.
--
-- Ownership unconfirmed. Candidates for removal. Do not build on them
-- until an owner claims them -- tracked in docs/open-questions.md.

-- ORPHAN: no code references it. Ownership unconfirmed; candidate for
-- removal. Live has no foreign key on it (so none is added here either).
alter table public.events
  add column if not exists shared_event_id uuid;

-- ORPHAN: no code references it. Ownership unconfirmed; candidate for
-- removal.
alter table public.events
  add column if not exists registration_start_datetime timestamptz;

-- ORPHAN: no code references it. Ownership unconfirmed; candidate for
-- removal.
alter table public.events
  add column if not exists registration_end_datetime timestamptz;

-- Rollback intent (no down-migration tooling is wired up yet -- recorded
-- here so a manual rollback is unambiguous if it's ever needed). NOTE:
-- rolling this back on the LIVE database would destroy real data and
-- break event creation -- this is for a local/fresh environment only:
--   alter table public.events drop column if exists registration_end_datetime;
--   alter table public.events drop column if exists registration_start_datetime;
--   alter table public.events drop column if exists shared_event_id;
--   alter table public.events drop column if exists equipment_needed;
--   alter table public.events alter column registration_needs type text using registration_needs::text;
--   alter table public.events alter column accessibility_needs type text using accessibility_needs::text;
