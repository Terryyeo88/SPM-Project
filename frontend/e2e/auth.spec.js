import { expect, test } from '@playwright/test'
import { SEED_PASSWORD, USERS, loginAs, signOut } from './support/auth.js'

test.describe('Login', () => {
  test('rejects the wrong password with a message, not a crash', async ({ page }) => {
    await page.goto('/login')
    await page.getByLabel('Email').fill(USERS.coordinator.email)
    await page.getByLabel('Password').fill('definitely-not-the-password')
    await page.getByRole('button', { name: 'Log In' }).click()

    await expect(page.getByText(/sign in failed|invalid/i)).toBeVisible()
    await expect(page).toHaveURL(/\/login$/)
  })

  test('signs in and reaches the dashboard', async ({ page }) => {
    await loginAs(page, USERS.coordinator)
    await expect(page).toHaveURL('/')
  })

  test('refuses an unauthenticated visitor on a protected route, sending them to login', async ({ page }) => {
    await page.goto('/venues')
    await expect(page).toHaveURL(/\/login$/)
  })

  test('signing out returns to login and re-protects the app', async ({ page }) => {
    await loginAs(page, USERS.coordinator)
    await signOut(page)
    await expect(page).toHaveURL(/\/login$/)

    // The idle-session / auth guard actually re-engages, not just the UI.
    await page.goto('/venues')
    await expect(page).toHaveURL(/\/login$/)
  })

  test('a second login as a different role starts a clean session, not a mix of both', async ({ page }) => {
    await loginAs(page, USERS.coordinator)
    await signOut(page)
    await loginAs(page, USERS.safetyOfficer)

    // The weak version of this test just checks we landed on '/', which
    // loginAs's own waitForURL already guarantees -- it wouldn't catch a
    // stale Pinia auth store carrying the coordinator role into the new
    // session. Assert the actually-displayed role instead: the nav's role
    // badge (AppNavBar.vue's roleText) must say the NEW role, and must not
    // still say the old one.
    const roleBadge = page.getByRole('banner').locator('.role-badge')
    await expect(roleBadge).toHaveText('Safety Officer')
    await expect(roleBadge).not.toContainText('Event Coordinator')
  })
})

test.describe('Seeded accounts cover every role the app routes by', () => {
  for (const [role, user] of Object.entries(USERS)) {
    test(`${role} (${user.email}) can sign in`, async ({ page }) => {
      await loginAs(page, user)
      await expect(page).toHaveURL('/')
    })
  }
})

test('the password field is masked', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByLabel('Password')).toHaveAttribute('type', 'password')
})

test.skip('seed password constant stays in sync with backend/seed.py and supabase/seed.sql', () => {
  // Reminder, not an automated check: if backend/seed.py's SEED_PASSWORD
  // or supabase/seed.sql's crypt('Password123!', ...) (what e2e runs
  // against locally) ever changes, update support/auth.js's SEED_PASSWORD (currently
  // 'Password123!') to match, or every test above starts failing for a
  // reason that has nothing to do with the app itself.
  expect(SEED_PASSWORD).toBe('Password123!')
})
