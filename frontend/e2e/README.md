# End-to-end tests (Playwright)

Real browser, real Flask backend, real Supabase project -- the whole
stack together, not mocked. This is deliberately separate from `npm test`
(Vitest), which mocks everything and needs no servers; Playwright proves
routing, auth, and the actual API calls work together, which unit tests
by design can't.

## Running locally

1. `backend/.env` and `frontend/.env` need real Supabase credentials (see
   the root `.env.example`).
2. Seed the test accounts once, if you haven't already:
   ```
   cd backend && source venv/bin/activate && python seed.py
   ```
3. From `frontend/`:
   ```
   npm run test:e2e        # headless, once
   npm run test:e2e:ui     # Playwright's own interactive runner
   ```

`playwright.config.js` starts both servers for you (`webServer`) and
reuses them if you already have `flask --app wsgi run` and `npm run dev`
running locally, so this doesn't fight your normal dev workflow -- it
just points the tests at whatever's already up.

If your backend runs on a non-default port (this repo's own `backend/.env`
sets `FLASK_RUN_PORT=5001`, working around macOS's AirPlay Receiver
squatting on 5000), tell Playwright the same way:
```
E2E_BACKEND_PORT=5001 npm run test:e2e
```

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
repo secrets. Without them configured, the job skips cleanly -- same
"skip without infra, don't fake it" stance the backend's own integration
tests already take.
