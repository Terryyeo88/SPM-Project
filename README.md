# SPM-Project (ConnectSphere)

IS212 Software Project Management team project (AY2026/27 T1).
Event planning and venue booking: Vue 3 SPA -> Flask API -> Supabase (Postgres).
The frontend never talks to Supabase directly and never holds the service role key.

**Repository:** https://github.com/Terryyeo88/SPM-Project

Architecture: `docs/c4/` (C1 context, C2 container, C3 component -- .puml sources
with rendered .png/.svg). CI pipeline: `.github/workflows/ci.yml`.

## Quick start

The five-minute path from clone to a running app. "Setup" below is the
reference for each step.

**There are two env files, and you need both.** The backend reads `.env` at
the repo root (holds the SECRET service role key). The frontend reads its own
`frontend/.env` (publishable anon key only). Copying just one is the most
common way this goes wrong.

```bash
git clone https://github.com/Terryyeo88/SPM-Project.git
cd SPM-Project
cp .env.example .env                    # backend: fill in SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY
cp frontend/.env.example frontend/.env  # frontend: fill in VITE_SUPABASE_URL + VITE_SUPABASE_ANON_KEY
```

Backend (terminal 1), serves http://127.0.0.1:5000:

```bash
cd backend
python -m venv .venv
source .venv/bin/activate               # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python check_env.py                     # confirms which project and key type, never prints the secret
flask --app wsgi run
```

Frontend (terminal 2), needs Node `^22.18.0 || >=24.12.0`, serves http://localhost:5173:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 (use `localhost`, not `127.0.0.1`: the API only
accepts requests from `http://localhost:5173`). `VITE_API_BASE_URL` in
`frontend/.env` must point at the backend, `http://127.0.0.1:5000` by default.

Seed the throwaway accounts with `python seed.py` from `backend/`, then sign
in as one of them (emails and the shared password are in `backend/seed.py`).

## Setup

Prerequisites: Python 3.12+ (CI runs 3.13), Node `^22.18.0 || >=24.12.0`,
and Docker Desktop if you want to run the local Supabase stack (needed for
integration and end-to-end tests).

```bash
git clone https://github.com/Terryyeo88/SPM-Project.git
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

Migrations live in `supabase/migrations/`. How they get applied depends on
where:

- **Local Supabase (Docker):** automatic. `npx supabase db reset` applies
  every migration in order and loads `supabase/seed.sql` (see "Reproducible
  from empty" below).
- **The hosted Supabase project:** manual, by pasting each file into the SQL
  Editor (details below).

**For the hosted project there is no tooling applying them automatically** —
each one is pasted by hand into the Supabase SQL Editor (Project -> SQL Editor -> paste the file's contents -> Run), in
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
verified no-op on a second run, and the integration tests pass against the
result (20 at the time; 206 as of 2026-11-06, all passing). To run it yourself (needs Docker Desktop running; the CLI runs
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
both create the same 11 throwaway accounts (3 coordinators, 1 coordinator
lead, 1 organiser, 3 attendees, 1 technical support, 1 safety officer,
1 venue staff; all share the password in `backend/seed.py`), the sample events (including a confirmed
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

Windows PowerShell equivalent (from the repo root, after `start` + `db reset`):

```powershell
npx supabase status -o env | Select-String '^(API_URL|SERVICE_ROLE_KEY)=' | ForEach-Object {
  $k, $v = $_.Line -split '=', 2; Set-Item "env:LOCAL_$k" $v.Trim('"') }
$env:SUPABASE_URL = $env:LOCAL_API_URL
$env:SUPABASE_SERVICE_ROLE_KEY = $env:LOCAL_SERVICE_ROLE_KEY
cd backend
.\.venv\Scripts\python.exe -m pytest -m integration
```

These variables override your `.env` for that terminal only (python-dotenv
never overwrites a variable that's already set), so your `.env` can keep
pointing at the shared project.

If `supabase start` can't bind its ports on Windows, a reserved port range is in the way. The range changes (reboots, updates), so check it with `netsh interface ipv4 show excludedportrange protocol=tcp`, move the ports in `supabase/config.toml` outside it for that session, and don't commit the change.

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

### Frontend

```bash
cd frontend
npm test                 # Vitest unit and component tests -- no servers needed
npm run test:e2e         # Playwright end-to-end tests (frontend/e2e/)
```

**End-to-end tests run against a local Supabase only** (`npx supabase start`,
Docker), never the shared project: they write real data. Settings come from
`.env.e2e` at the repo root (copy `.env.e2e.example`), and the suite refuses to
start if it points anywhere else. Playwright starts its own backend (5000) and
frontend (5173) with those settings, so stop your normal dev servers first.
One-time setup (Docker, a local signing key, `.env.e2e`) is in
`frontend/e2e/README.md`.

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
- `docs/definition-of-done.md` — the team's Definition of Done.
- `docs/c4/` — C4 model: context, container and component diagrams.
