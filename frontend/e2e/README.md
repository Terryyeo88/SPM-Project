# End-to-end tests (Playwright)

Real browser, real Flask backend, real Supabase -- the whole stack
together, not mocked. This is deliberately separate from `npm test`
(Vitest), which mocks everything and needs no servers; Playwright proves
routing, auth, and the actual API calls work together, which unit tests
by design can't.

**They run against a local Supabase in Docker, never the shared project.**
Every run creates real events, bookings and registrations, so
`support/env.js` refuses to start unless `.env.e2e` points at
`npx supabase start` (localhost / 127.0.0.1). The shared project is refused
outright.

## One-time setup

1. Install **Docker Desktop** (Windows: let it turn on WSL 2) and start it.
2. Generate a local signing key (from the repo root). The backend only
   accepts tokens signed with an asymmetric key (`backend/app/auth/jwt.py`),
   and `supabase/config.toml` points local auth at this file:
   ```
   npx supabase gen signing-key --algorithm ES256
   ```
   It should write `supabase/signing_keys.json` (gitignored). If it prints
   the key instead, save the output into that file as a JSON array:
   `[ { ...the key... } ]`.
3. Start local Supabase and build the database from the migrations and
   `supabase/seed.sql` (the seeded accounts, venues and stock):
   ```
   npx supabase start
   npx supabase db reset
   ```
4. Copy `.env.e2e.example` (repo root) to `.env.e2e` and fill in
   `SECRET_KEY` (`sb_secret_...`) and `PUBLISHABLE_KEY` (`sb_publishable_...`)
   from the command below -- not the legacy `SERVICE_ROLE_KEY` / `ANON_KEY`
   JWTs, which local PostgREST rejects once a signing key is set:
   ```
   npx supabase status -o env
   ```

## Running

1. Make sure local Supabase is up (`npx supabase start`; Docker running).
2. **Stop your normal dev servers** (Ctrl+C on `flask run` and
   `npm run dev`). Playwright starts its own pair with `.env.e2e`'s settings
   and never reuses yours, because yours point at the shared project. If
   they're still running it stops with "port is already used".
3. From `frontend/`:
   ```
   npm run test:e2e        # headless, once
   npm run test:e2e:ui     # Playwright's own interactive runner
   ```

`npx supabase db reset` wipes the local database back to the seed whenever
you want a clean slate. `npx supabase stop` shuts it down when you're done.

If your backend can't use port 5000 (macOS's AirPlay Receiver squats on
it), set `E2E_BACKEND_PORT=5001` in `.env.e2e`.

## What's covered

- `auth.spec.js` -- login (success/failure), sign-out, session
  re-protection, and that every role `backend/seed.py` creates can
  actually sign in.
- `navigation.spec.js` -- role-based nav visibility and route guards
  (`lib/roles.js`'s `ROUTE_ACCESS` / `NAV_LINKS`), proven through a real
  login and a real route, not just the unit-tested table.

Every role has a seeded account in `backend/seed.py`, including
`venue_staff` (`venuestaff1@example.com`), so the "every role can sign in"
test covers all seven.

## CI

`e2e-test` in `.github/workflows/ci.yml` runs this against three
`E2E_SUPABASE_URL` / `E2E_SUPABASE_SERVICE_ROLE_KEY` / `E2E_SUPABASE_ANON_KEY`
repo secrets, which must be a **dedicated test project**, never the shared
one (refused by `support/env.js` whatever the job says). Without them
configured, the job skips cleanly -- same "skip without infra, don't fake
it" stance the backend's own integration tests already take.
