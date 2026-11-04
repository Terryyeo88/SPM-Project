// Login helper for E2E tests -- matches backend/seed.py's accounts
// exactly (same emails, same SEED_PASSWORD), so these tests work against
// any Supabase project seed.py has been run against, not just one
// specific one.
export const SEED_PASSWORD = 'Password123!'

// One representative seeded account per role seed.py creates.
export const USERS = Object.freeze({
  organizer: { email: 'organizer1@example.com', name: 'Derek Ong' },
  coordinator: { email: 'coordinator1@example.com', name: 'Alice Tan' },
  lead: { email: 'lead1@example.com', name: 'Grace Lim' },
  attendee: { email: 'attendee1@example.com', name: 'Ethan Koh' },
  technicalSupport: { email: 'techsupport1@example.com', name: 'Ivan Goh' },
  safetyOfficer: { email: 'safety1@example.com', name: 'Hannah Lee' },
  venueStaff: { email: 'venuestaff1@example.com', name: 'Vanessa Lim' },
})

/** Logs in through the real UI (not a shortcut) and waits for the
 * dashboard to load, so every test starts from a genuinely authenticated
 * session the same way a person would get one. */
export async function loginAs(page, user) {
  await page.goto('/login')
  await page.getByLabel('Email').fill(user.email)
  await page.getByLabel('Password').fill(SEED_PASSWORD)
  await page.getByRole('button', { name: 'Log In' }).click()
  await page.waitForURL('/')
}

/** Sign out lives on the profile page (every role can reach it), not the
 * nav bar -- see ProfileView.vue's own comment on why. */
export async function signOut(page) {
  await page.goto('/profile')
  await page.getByRole('button', { name: 'Sign out' }).click()
  await page.waitForURL(/\/login$/)
}
