# SPM-Project (ConnectSphere)

IS212 Software Project Management team project. Vue frontend (not built yet)
-> Flask backend -> Supabase. The frontend never talks to Supabase directly
and never holds the service role key.

## Setup

```bash
git clone <repo-url>
cd SPM-Project/backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Copy the env template to the **repo root** (not `backend/`) and fill it in:

```bash
cp ../.env.example ../.env
```

Get the real values from the Supabase dashboard (Project Settings -> API).
Then confirm they're wired up correctly without ever printing the secret:

```bash
python check_env.py
```

### Apply migrations

Migrations live in `supabase/migrations/`. **There is currently no tooling
applying them automatically** — each one is pasted by hand into the Supabase
SQL Editor (Project -> SQL Editor -> paste the file's contents -> Run), in
filename order. Nothing enforces that every environment (your local dev
project, a teammate's, staging) is actually at the same migration version —
if you've just pulled new commits, check `supabase/migrations/` for new
files and apply any you haven't run yet.

**What went wrong in Sprint 1.** Because nothing enforced parity, schema
changes were made directly in the dashboard, and the migration files were
never written. By 2026-09-27 the live `events` table had six columns that no
migration described: `equipment_needed`, `shared_event_id`,
`registration_start_datetime` and `registration_end_datetime` didn't exist
in the files at all, and `accessibility_needs`/`registration_needs` had
different types (jsonb/boolean live, text in the files). A fresh environment
built from the files couldn't create an event.
`20260927000000_reconcile_events_with_live.sql` closes that gap. It is
idempotent and a no-op against the live database. See
`docs/design-decisions.md` ("Live schema was the source of truth when
reconciling migrations") for why the files were changed to match live
rather than the other way round.

**The rule from now on: migration file first, then apply. Never
dashboard-first.** Any schema change (new table, new column, type change,
new enum value, new policy) is written as a new timestamped file in
`supabase/migrations/` and committed. Only then is it applied to the
database, by pasting that exact file into the SQL Editor. If you find
yourself about to click "add column" in the Table Editor, write the
migration instead. Never edit a migration that's already been applied;
add a new one. The same rule applies to exploratory changes: if a column
turns out to be unnecessary, remove it with its own migration rather than
deleting it in the dashboard.

**Reproducible from empty: verified.** As of 2026-09-27 the migration set
builds the full schema from an empty database with `npx supabase db reset`.
All migrations apply in order with no errors, the reconcile migration is a
verified no-op on a second run, and all 20 integration tests pass against
the result. To run it yourself (needs Docker Desktop running; the CLI runs
through `npx`, so there's nothing to install globally):

```bash
npx supabase start       # first run pulls images; a few minutes
npx supabase db reset    # drop local DB, apply every migration in order, run seed.sql
npx supabase status      # local API URL + keys (these are local demo keys, not the real project's)
npx supabase stop        # when you're done
```

Before you open a PR that adds a migration, run `npx supabase db reset`
and confirm it finishes cleanly. That's the whole check. The same local
stack is what integration tests run against. See "Running tests" below.

The file-first rule itself is still **enforced only by discipline** until
everyone works this way. Nothing stops a dashboard edit, and nothing yet
runs `db reset` in CI. When in doubt, open the dashboard and check which
tables/columns actually exist before assuming a migration ran.

### Seed data

Either run the Python seeder or paste the SQL version into the SQL Editor —
both create the same throwaway accounts (3 coordinators, 1 coordinator lead,
1 organiser, 3 attendees), the sample events (including a confirmed
"Registration Demo" request for testing registration, recreated fresh on
every run, registrations included), and the venues,
and are safe to re-run:

```bash
python seed.py
# or paste supabase/seed.sql into the SQL Editor
```

## Running the app

```bash
cd backend
flask --app wsgi run
```

`GET /health` should return `{"status": "ok"}` with **no** `.env` at all —
if it doesn't, something is wrong with the app factory itself, not your
credentials. `GET /health/db` additionally checks real database
connectivity and returns 503 (not a crash) if that fails.

Every other route requires a valid Supabase-issued bearer token
(`Authorization: Bearer <token>`) — routes are protected by default.
`GET /me` returns the authenticated caller's id/email/name/roles.

## Running tests

```bash
cd backend
pytest                                    # everything that can run
pytest -m "not integration"               # unit tests only -- no DB, no network, no .env needed
pytest -m integration                     # integration tests only -- against a LOCAL Supabase (below)
pytest --cov=app --cov-report=term-missing   # with coverage
```

**Unit tests cannot reach any database.** If one tries, it fails with
`UnitTestDatabaseAccessError` naming the test. Fake the call it missed.

**Integration tests** (marked `@pytest.mark.integration`) create and delete
real rows, so **they only run against a local Supabase**:

```bash
npx supabase start && npx supabase db reset       # from the repo root
eval "$(npx supabase status -o env | grep -E '^(API_URL|SERVICE_ROLE_KEY)=' | sed 's/^/LOCAL_/')"
SUPABASE_URL="$LOCAL_API_URL" SUPABASE_SERVICE_ROLE_KEY="$LOCAL_SERVICE_ROLE_KEY"   pytest -m integration                           # from backend/
```

Otherwise they skip themselves, with a message saying why:
- **No credentials** (CI): skipped.
- **`SUPABASE_URL` is not local**, e.g. your `.env` pointing at the shared
  project: **skipped**. A bare `pytest` on a machine with `.env` therefore
  does not write to the database the team demos from. "Local" means
  `localhost` or a loopback IP (what `npx supabase status` reports).
- **Deliberately running against the shared project** needs an explicit,
  exact opt-in:
  `INTEGRATION_TESTS_WRITE_TO_REMOTE_SUPABASE=yes-write-test-data-to-the-shared-project`.
  Don't set this casually.

pytest's header line says which case you're in (e.g.
`integration tests: RUN against 127.0.0.1 [local]`). Integration tests
rely on `supabase/seed.sql`, which `db reset` loads.

## Secrets

`SUPABASE_SERVICE_ROLE_KEY` bypasses Row Level Security entirely and is
**server-side only**. It must never reach the frontend, never appear in a
Vue env var (those are prefixed `VITE_` and get bundled into client-shipped
JS), and never get logged or printed. The frontend only ever gets
`VITE_SUPABASE_ANON_KEY`, which is safe to expose because it's constrained
by RLS. `.env` is gitignored — copy `.env.example`, never commit the real
file.

## Documentation

- `docs/design-decisions.md` — why things are built the way they are, written
  to be defended out loud.
- `docs/traceability.md` — acceptance criterion -> test -> implementation.
- `docs/authz-usage.md` — how to use the authorisation policy module
  (`app/authz`) when building new routes.
- `docs/open-questions.md` — decisions made that still need customer
  confirmation.
