import { expect, test } from '@playwright/test'
import { USERS, loginAs } from './support/auth.js'

// lib/roles.js's ROUTE_ACCESS is the single source of truth this exercises
// end to end: a real login, a real nav render, a real route guard --
// proving the role gate actually works through the whole stack, not just
// that the unit-tested table says it should.

test.describe('Role-based navigation', () => {
  // lib/roles.js's _DASHBOARD_ONLY_ROLES deliberately strips nav links
  // for event_coordinator (among others): a coordinator works entirely
  // from "My Assigned Events" on their dashboard, per the wireframe. The
  // /venues ROUTE is still reachable -- just never offered as a nav
  // link -- so this proves the route, not a link that doesn't exist for
  // this role by design.
  test('a coordinator has no nav links, but can still reach Venues directly', async ({ page }) => {
    await loginAs(page, USERS.coordinator)
    await expect(page.getByRole('banner').getByRole('link', { name: 'Venues' })).toHaveCount(0)

    await page.goto('/venues')
    await expect(page).toHaveURL(/\/venues$/)
  })

  test('an organizer, a role that does keep its nav links, sees Events there', async ({ page }) => {
    await loginAs(page, USERS.organizer)
    await expect(page.getByRole('banner').getByRole('link', { name: 'Events' })).toBeVisible()
  })

  test('an attendee has no Venues link, and the route itself refuses them', async ({ page }) => {
    await loginAs(page, USERS.attendee)
    await expect(page.getByRole('banner').getByRole('link', { name: 'Venues' })).toHaveCount(0)

    // meta.roles gate, not just a hidden link -- direct navigation is
    // bounced to the dashboard, not left open.
    await page.goto('/venues')
    await expect(page).toHaveURL('/')
  })

  test('technical support staff see Equipment, not Venues, in the nav', async ({ page }) => {
    await loginAs(page, USERS.technicalSupport)
    await expect(page.getByRole('banner').getByRole('link', { name: 'Equipment', exact: true })).toBeVisible()
    await expect(page.getByRole('banner').getByRole('link', { name: 'Venues' })).toHaveCount(0)
  })

  // One test per seeded role, so the name means what it says -- the earlier
  // version only ever logged in as the attendee.
  for (const [role, user] of Object.entries(USERS)) {
    test(`${role} can reach their own profile`, async ({ page }) => {
      await loginAs(page, user)
      await page.goto('/profile')
      await expect(page).toHaveURL(/\/profile$/)
      await expect(page.getByRole('heading', { name: 'My Profile' })).toBeVisible()
      await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible()
    })
  }
})

test.describe('Venue catalogue journey', () => {
  test('a coordinator can open the catalogue and drill into one venue', async ({ page }) => {
    await loginAs(page, USERS.coordinator)
    await page.goto('/venues')
    await expect(page).toHaveURL(/\/venues$/)

    // backend/seed.py always seeds 4 venues (Grand Ballroom, Innovation
    // Hub, Executive Boardroom, Riverside Pavilion) unconditionally on
    // every run, so this is a hard assertion, not a "skip if empty"
    // fallback -- a previous version of this test silently skipped the
    // drill-in on an empty catalogue, which would have reported "passed"
    // while testing nothing if the seed ever regressed.
    const firstVenue = page.locator('a.row').first()
    await expect(firstVenue).toBeVisible()
    const venueName = (await firstVenue.locator('.row-name').innerText()).trim()

    await firstVenue.click()
    // The URL alone isn't proof: /venues/new and /venues/bookings also match
    // /venues/.+, so a link pointing at the wrong page would still pass. The
    // detail page must show the venue that was clicked.
    await expect(page).toHaveURL(/\/venues\/[0-9a-f-]{36}$/)
    await expect(page.getByRole('heading', { level: 1, name: venueName })).toBeVisible()
  })
})
