// End-to-end tests against the real stack: a live Vite dev server talking
// to a live Flask backend talking to a real Supabase project (whatever
// frontend/.env and backend/.env point at -- same credentials you already
// use for manual black box testing).
//
// This is deliberately separate from Vitest (npm test), which mocks
// everything and needs no servers. Playwright drives a real browser
// against real servers, so it proves the whole chain works together --
// routing, auth, and the actual API calls -- not just that each piece
// works in isolation.
//
// Needs seeded accounts (backend/seed.py, SEED_PASSWORD='Password123!')
// to exist in whatever Supabase project your .env files point at. Run
// `python seed.py` from backend/ once against your project if you haven't.
//
// Run with: npm run test:e2e (from frontend/). Add --ui for Playwright's
// own interactive runner, or --headed to watch it drive a real browser
// window.
import { defineConfig, devices } from '@playwright/test'

// "localhost", not "127.0.0.1": Vite's own dev server (and Node in
// general, on this stack) resolves "localhost" to IPv6 "::1" first on
// some machines, so a readiness probe against the IPv4 literal can miss
// an already-running server entirely and try to start a second one on
// the same port, which then fails to bind. Matching Vite's own default
// hostname keeps the probe and the actual bind looking at the same thing.
const FRONTEND_URL = 'http://localhost:5173'
// Matches backend/.env's FLASK_RUN_PORT when set (this repo moves off
// 5000 locally -- macOS's AirPlay Receiver squats on it); falls back to
// Flask's own default for a machine without that override (e.g. CI).
const BACKEND_PORT = process.env.E2E_BACKEND_PORT || '5000'
const BACKEND_URL = `http://localhost:${BACKEND_PORT}`

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? [['github'], ['html', { open: 'never' }]] : [['list'], ['html', { open: 'never' }]],
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

  // Starts both halves of the stack before the suite, and leaves an
  // already-running pair alone in local dev (reuseExistingServer) so this
  // doesn't fight the servers you're probably already running for manual
  // testing -- it just points the tests at them instead.
  webServer: [
    {
      command: `../backend/venv/bin/flask --app wsgi run --port ${BACKEND_PORT}`,
      cwd: '../backend',
      url: `${BACKEND_URL}/health`,
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
    {
      command: 'npm run dev -- --port 5173 --strictPort',
      cwd: '.',
      url: FRONTEND_URL,
      reuseExistingServer: !process.env.CI,
      timeout: 30_000,
      stdout: 'pipe',
      stderr: 'pipe',
    },
  ],
})
