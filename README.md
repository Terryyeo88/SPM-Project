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
files and apply any you haven't run yet. **This is a known gap, raised at
standup, not yet closed.** Until it is: when in doubt, open the dashboard and
check which tables/columns actually exist before assuming a migration ran.

### Seed data

Either run the Python seeder or paste the SQL version into the SQL Editor —
both create the same 3 throwaway coordinators, 1 organiser, and 3 events,
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
pytest -m integration                     # integration tests only -- needs .env with real credentials
pytest --cov=app --cov-report=term-missing   # with coverage
```

Integration tests (marked `@pytest.mark.integration`) talk to the real
Supabase project and **skip themselves automatically** if `SUPABASE_URL` /
`SUPABASE_SERVICE_ROLE_KEY` aren't set — this is what lets CI run without any
secrets configured at all. They also expect the seed data above to exist
(some skip individually if specific seeded rows aren't found).

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
