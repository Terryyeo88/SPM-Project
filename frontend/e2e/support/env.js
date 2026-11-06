// Which Supabase the e2e suite is allowed to write to, and where its
// settings come from.
//
// Every run creates real events, bookings and registrations and signs in
// as the seeded accounts, so it must never point at the shared project
// the team demos from. Settings come from ONE file, `.env.e2e` at the repo
// root (copy `.env.e2e.example`), never from `backend/.env` /
// `frontend/.env`, which point at the shared project for manual testing.
//
// Same stance as the backend's integration tests (backend/tests/conftest.py):
// local Supabase only (`npx supabase start`), and a remote project needs an
// exact, deliberate opt-in. The shared project's ref is refused outright,
// opt-in or not.
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { parseEnv } from 'node:util'

export const ENV_FILE = fileURLToPath(new URL('../../../.env.e2e', import.meta.url))

// The shared project (see backend/app/auth/jwt.py). Never a test target.
const SHARED_PROJECT_REF = 'cbnzjcfosvgzoecekjxg'

// Exact value E2E_WRITE_TO_REMOTE_SUPABASE must have to allow a remote
// (non-local) project, e.g. a dedicated cloud test project in CI.
export const REMOTE_OPT_IN = 'yes-write-test-data-to-a-dedicated-test-project'

/** True only for localhost or a loopback IP -- what `npx supabase status`
 * reports (http://127.0.0.1:54321). Anything unparseable counts as remote. */
export function isLocalSupabase(url) {
  let host
  try {
    host = new URL(url).hostname
  } catch {
    return false
  }
  return host === 'localhost' || host === '[::1]' || /^127(\.\d{1,3}){3}$/.test(host)
}

/** Throws, naming the problem, unless `env` points the backend and the
 * frontend at the SAME Supabase, and that Supabase is safe to write to. */
export function assertSafeTarget(env) {
  for (const key of ['SUPABASE_URL', 'VITE_SUPABASE_URL']) {
    if (!env[key]) throw new Error(`${key} is not set. Put it in .env.e2e at the repo root (see .env.e2e.example).`)
  }
  if (env.SUPABASE_URL.replace(/\/$/, '') !== env.VITE_SUPABASE_URL.replace(/\/$/, '')) {
    throw new Error(
      `SUPABASE_URL (${env.SUPABASE_URL}) and VITE_SUPABASE_URL (${env.VITE_SUPABASE_URL}) differ: ` +
        'the backend and the browser would be talking to different databases.',
    )
  }
  const url = env.SUPABASE_URL
  if (url.includes(SHARED_PROJECT_REF)) {
    throw new Error('Refusing to run e2e tests against the shared Supabase project. Point .env.e2e at a local Supabase.')
  }
  if (!isLocalSupabase(url) && env.E2E_WRITE_TO_REMOTE_SUPABASE !== REMOTE_OPT_IN) {
    throw new Error(
      `${url} is not a local Supabase. E2E tests write real data, so they only run against ` +
        '`npx supabase start` (http://127.0.0.1:54321) unless E2E_WRITE_TO_REMOTE_SUPABASE is set to ' +
        `"${REMOTE_OPT_IN}".`,
    )
  }
}

/** The backend Playwright starts: 127.0.0.1 (Flask binds IPv4 only), port
 * 5000 unless E2E_BACKEND_PORT moves it (macOS: AirPlay squats on 5000). */
export function backendUrl(env) {
  return `http://127.0.0.1:${env.E2E_BACKEND_PORT || '5000'}`
}

/** Loads `.env.e2e` into process.env (its values win over anything already
 * set, so a stray shell variable can't redirect the run), then checks the
 * target. CI has no file: there the values come from the job's env. */
export function loadE2EEnv() {
  if (existsSync(ENV_FILE)) {
    Object.assign(process.env, parseEnv(readFileSync(ENV_FILE, 'utf8')))
  } else if (!process.env.CI) {
    throw new Error(
      'No .env.e2e at the repo root. Copy .env.e2e.example to .env.e2e and fill it in from ' +
        '`npx supabase status -o env` (see frontend/e2e/README.md).',
    )
  }
  assertSafeTarget(process.env)
  return process.env
}
