// End-to-end tests against the real stack: a live Vite dev server talking
// to a live Flask backend talking to a LOCAL Supabase (`npx supabase start`,
// in Docker) -- never the shared project the team demos from, because every
// run creates real events, bookings and registrations.
//
// Settings come from `.env.e2e` at the repo root (copy `.env.e2e.example`),
// not from backend/.env or frontend/.env. e2e/support/env.js loads it and
// refuses to start if it points anywhere but a local Supabase. Values in
// .env.e2e override both servers' own .env files: python-dotenv and Vite
// both leave an already-set environment variable alone.
//
// This is deliberately separate from Vitest (npm test), which mocks
// everything and needs no servers. Playwright drives a real browser
// against real servers, so it proves the whole chain works together --
// routing, auth, and the actual API calls -- not just that each piece
// works in isolation.
//
// Needs the seeded accounts (SEED_PASSWORD='Password123!'), which
// `npx supabase db reset` loads from supabase/seed.sql.
//
// Run with: npm run test:e2e (from frontend/). Add --ui for Playwright's
// own interactive runner, or --headed to watch it drive a real browser
// window. See e2e/README.md for the one-time setup.
import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, devices } from '@playwright/test'
import { backendUrl, loadE2EEnv } from './e2e/support/env.js'

const env = loadE2EEnv()

// "localhost", not "127.0.0.1": Vite's own dev server (and Node in
// general, on this stack) resolves "localhost" to IPv6 "::1" first on
// some machines, so a readiness probe against the IPv4 literal can miss
// an already-running server. Must stay 5173: it's the one origin the
// backend's CORS allows (backend/app/__init__.py).
const FRONTEND_URL = 'http://localhost:5173'
// Port 5000 unless E2E_BACKEND_PORT (in .env.e2e) moves it -- see backendUrl.
const BACKEND_PORT = env.E2E_BACKEND_PORT || '5000'
const BACKEND_URL = backendUrl(env)
// The browser and support/api.js both call the backend Playwright starts,
// whatever .env.e2e or frontend/.env say.
env.VITE_API_BASE_URL = BACKEND_URL

// The backend's venv: `.venv` (README's Setup) or `venv`, whichever exists,
// in the right layout for this OS. Falls back to whatever `python` is on
// PATH (an activated venv or conda env).
const BACKEND_DIR = fileURLToPath(new URL('../backend', import.meta.url))
const VENV_PYTHON = ['.venv', 'venv']
  .map((dir) => (process.platform === 'win32' ? path.join(dir, 'Scripts', 'python.exe') : path.join(dir, 'bin', 'python')))
  .find((candidate) => existsSync(path.join(BACKEND_DIR, candidate)))
const PYTHON = VENV_PYTHON ?? 'python'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: Boolean(env.CI),
  retries: env.CI ? 1 : 0,
  workers: env.CI ? 1 : undefined,
  reporter: env.CI ? [['github'], ['html', { open: 'never' }]] : [['list'], ['html', { open: 'never' }]],
  timeout: 30_000,

  use: {
    baseURL: FRONTEND_URL,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },

  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],

  // Playwright always starts BOTH servers itself, with .env.e2e's settings,
  // and never reuses ones already running: your normal dev servers point
  // at the shared project, so reusing them would send the tests there. If
  // you have them running, Playwright stops with "port is already used" --
  // stop them first (Ctrl+C), then run the tests.
  webServer: [
    {
      command: `${PYTHON} -m flask --app wsgi run --port ${BACKEND_PORT}`,
      cwd: BACKEND_DIR,
      url: `${BACKEND_URL}/health`,
      env: { ...env },
      reuseExistingServer: false,
      timeout: 30_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      command: 'npm run dev -- --port 5173 --strictPort',
      cwd: '.',
      url: FRONTEND_URL,
      env: { ...env },
      reuseExistingServer: false,
      timeout: 60_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
})
