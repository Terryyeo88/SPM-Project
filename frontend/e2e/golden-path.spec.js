// The happy path end to end, one event request through every role:
//
//   organiser creates + submits -> lead assigns a coordinator ->
//   coordinator asks a clarification, organiser replies -> coordinator
//   approves and starts planning -> coordinator requests a venue, venue
//   staff approve -> coordinator requests equipment, tech support accept ->
//   coordinator submits for the safety check, safety officer approves ->
//   coordinator confirms -> attendee registers -> coordinator marks it
//   completed (IS-38)
//
// Each role gets its own browser context (its own login), so one test can
// hand the request from role to role exactly as people would. test.step()
// names every handoff, so a failure report says WHICH one broke.
//
// Runs against the real stack on a LOCAL Supabase (.env.e2e; see
// support/env.js): every run creates a fresh request named
// "E2E Golden <timestamp>" on a far-future date, so runs don't collide with
// each other's venue bookings or with real data, and are easy to spot.
//
// Needs the seeded accounts (support/auth.js), the "Grand Ballroom" venue
// and the projector stock -- all loaded by `npx supabase db reset`.
import { expect, test } from '@playwright/test'
import { USERS, loginAs } from './support/auth.js'

const pad = (n) => String(n).padStart(2, '0')
const localDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`

// A different far-future day each run (1-8 years out), so this run's venue
// booking and equipment reservation never clash with an earlier run's.
function sessionDay() {
  const day = new Date()
  day.setDate(day.getDate() + 365 + (Math.floor(Date.now() / 1000) % 2500))
  return day
}

async function asRole(browser, user) {
  const context = await browser.newContext()
  const page = await context.newPage()
  await loginAs(page, user)
  return { context, page }
}

test.describe('Golden path: from event request to registration', () => {
  test.describe.configure({ timeout: 240_000 })

  test('one request goes through every role and an attendee registers', async ({ browser }) => {
    const name = `E2E Golden ${Date.now()}`
    const day = sessionDay()
    const dayBefore = new Date(day)
    dayBefore.setDate(day.getDate() - 1)
    let eventId

    const organiser = await asRole(browser, USERS.organizer)
    const lead = await asRole(browser, USERS.lead)
    const coordinator = await asRole(browser, USERS.coordinator)

    await test.step('organiser creates and submits the request', async () => {
      const { page } = organiser
      await page.goto('/create-event')
      await page.getByLabel('Event Name').fill(name)
      await page.getByLabel('Description').fill('Created by the golden-path e2e test.')
      await page.getByLabel('Purpose of the Event').fill('End-to-end testing.')
      await page.getByLabel('Preferred Start Date & Time').fill(`${localDate(day)}T10:00`)
      await page.getByLabel('Preferred End Date & Time').fill(`${localDate(day)}T12:00`)
      await page.getByLabel('Expected Attendance').fill('20')
      await page.getByLabel('Room Layout').selectOption({ index: 1 })
      await page.getByLabel('Registration needed').check()
      // Open from today, so the attendee can register at the end of this run.
      await page.getByLabel('Registration Opens').fill(`${localDate(new Date())}T00:00`)
      await page.getByLabel('Registration Closes').fill(`${localDate(dayBefore)}T23:00`)
      await page.getByRole('button', { name: 'Submit Request' }).click()
      await expect(page.getByText('Event request submitted for review.')).toBeVisible()
    })

    await test.step('lead assigns Alice Tan as coordinator', async () => {
      const { page } = lead
      await page.goto('/')
      await page.getByLabel('Search event requests').fill(name)
      const row = page.locator('.row').filter({ hasText: name })
      await expect(row).toBeVisible()
      // The row's link is the request's event page: /events/<id>.
      const href = await row.getByRole('link').first().getAttribute('href')
      eventId = href.split('/').pop()
      await row.getByLabel(`Coordinator for ${name}`).selectOption({ label: USERS.coordinator.name })
      await row.getByRole('button', { name: 'Assign' }).click()
      await expect(page.getByText(`"${name}" assigned to ${USERS.coordinator.name}`)).toBeVisible()
    })

    await test.step('coordinator asks a clarification; status stays Under Review', async () => {
      const { page } = coordinator
      await page.goto(`/events/${eventId}`)
      await page.getByRole('button', { name: 'Request Clarification' }).click()
      // The button's job is to bring the chat box to the coordinator (that it
      // also puts the cursor in it is unit-tested in CoordinatorEventReview.test.js).
      await expect(page.locator('#clarification-message')).toBeInViewport()
      await page.locator('#clarification-message').fill('Is the date flexible?')
      await page.getByRole('button', { name: 'Send', exact: true }).click()
      await expect(page.locator('li.message').filter({ hasText: 'Is the date flexible?' })).toBeVisible()
      await expect(page.getByText('Under Review').first()).toBeVisible()
    })

    await test.step('organiser sees the question and replies', async () => {
      const { page } = organiser
      await page.goto(`/events/${eventId}`)
      await expect(page.locator('li.message').filter({ hasText: 'Is the date flexible?' })).toBeVisible()
      await page.locator('#clarification-message').fill('Yes, any weekday works.')
      await page.getByRole('button', { name: 'Send', exact: true }).click()
      await expect(page.getByText('Reply sent.')).toBeVisible()
    })

    await test.step('coordinator sees the reply, approves, and starts planning', async () => {
      const { page } = coordinator
      await page.reload()
      await expect(page.locator('li.message').filter({ hasText: 'Yes, any weekday works.' })).toBeVisible()
      await page.getByRole('button', { name: 'Approve Request' }).click()
      await expect(page.getByText('Request approved')).toBeVisible()
      await page.getByRole('button', { name: 'Start Planning' }).click()
      await expect(page.getByText('Request moved to In Planning')).toBeVisible()
    })

    let bookingPath
    await test.step('coordinator requests the Grand Ballroom', async () => {
      const { page } = coordinator
      await page.getByRole('link', { name: 'Request Venue Booking' }).click()
      await page.locator('button.venue-card').filter({ hasText: 'Grand Ballroom' }).click()
      await page.getByRole('button', { name: 'Submit Request' }).click()
      await expect(page).toHaveURL(new RegExp(`/events/${eventId}$`))
      bookingPath = await page.locator('a[href^="/venues/bookings/"]').first().getAttribute('href')
      expect(bookingPath).toBeTruthy()
    })

    await test.step('venue staff approve the booking', async () => {
      const venueStaff = await asRole(browser, USERS.venueStaff)
      await venueStaff.page.goto(bookingPath)
      await venueStaff.page.getByRole('button', { name: 'Approve Booking' }).click()
      await expect(venueStaff.page.getByRole('button', { name: 'Approve Booking' })).toHaveCount(0)
      await venueStaff.context.close()
    })

    await test.step('coordinator requests a projector', async () => {
      const { page } = coordinator
      await page.goto(`/events/${eventId}`)
      await page.getByRole('link', { name: 'Request Equipment' }).click()
      await page.getByLabel('Equipment type for item 1').selectOption({ label: 'Projector' })
      await page.getByLabel('Quantity for item 1').fill('1')
      await page.getByRole('button', { name: 'Submit Request' }).click()
      await expect(page).toHaveURL(new RegExp(`/events/${eventId}$`))
    })

    await test.step('technical support accept the equipment request', async () => {
      const tech = await asRole(browser, USERS.technicalSupport)
      await tech.page.goto('/equipment/requests')
      await tech.page.locator('a.row').filter({ hasText: name }).first().click()
      await tech.page.getByRole('button', { name: 'Accept request' }).click()
      await expect(tech.page.getByRole('button', { name: 'Accept request' })).toHaveCount(0)
      await tech.context.close()
    })

    await test.step('coordinator submits for the safety check', async () => {
      const { page } = coordinator
      await page.goto(`/events/${eventId}`)
      await page.getByRole('button', { name: 'Submit for Safety Check' }).click()
      await expect(page.getByText('Submitted for a safety check.')).toBeVisible()
    })

    await test.step('safety officer approves', async () => {
      const officer = await asRole(browser, USERS.safetyOfficer)
      await officer.page.goto('/')
      await officer.page.getByRole('link').filter({ hasText: name }).first().click()
      await officer.page.getByRole('button', { name: 'Approve', exact: true }).click()
      await officer.page.getByRole('button', { name: /^Confirm:/ }).click()
      await expect(officer.page.getByText('Approved. The coordinator can now confirm this session.')).toBeVisible()
      await officer.context.close()
    })

    await test.step('coordinator confirms the event', async () => {
      const { page } = coordinator
      await page.goto(`/events/${eventId}`)
      await page.getByRole('button', { name: 'Confirm Event' }).click()
      await expect(page.getByText('Confirmed', { exact: true }).first()).toBeVisible()
    })

    await test.step('organiser sees it confirmed', async () => {
      const { page } = organiser
      await page.goto(`/events/${eventId}`)
      await expect(page.getByText('Confirmed', { exact: true }).first()).toBeVisible()
    })

    await test.step('an attendee registers', async () => {
      const attendee = await asRole(browser, USERS.attendee)
      const { page } = attendee
      await page.goto(`/attend/${eventId}`)
      await page.getByRole('button', { name: 'Register', exact: true }).click()
      const phone = page.getByLabel('Phone Number')
      if (!(await phone.inputValue())) await phone.fill('9123 4567')
      await page.getByRole('button', { name: 'Confirm Registration' }).click()
      // The lasting "registered" badge, not the one-off success message
      // (both say "You're registered").
      await expect(page.locator('.state-confirmed')).toContainText("You're registered")
      await attendee.context.close()
    })

    // IS-38. The session is dated years ahead, so in real life it hasn't
    // "taken place" yet -- completion isn't date-gated (docs/open-questions.md),
    // which is what lets the journey end here.
    await test.step('coordinator marks the confirmed event completed; it is read-only', async () => {
      const { page } = coordinator
      await page.goto(`/events/${eventId}`)
      await page.getByRole('button', { name: 'Mark as Completed' }).click()
      await page.getByRole('button', { name: 'Confirm Completed' }).click()
      await expect(page.getByText('Session marked as completed.')).toBeVisible()
      // Survives a reload, i.e. it's the stored status, not local state.
      await page.reload()
      await expect(page.getByText('Completed', { exact: true }).first()).toBeVisible()
      await expect(page.getByRole('button', { name: 'Edit Details' })).toHaveCount(0)
      await expect(page.getByRole('button', { name: 'Cancel Event' })).toHaveCount(0)
      await expect(page.getByRole('button', { name: 'Mark as Completed' })).toHaveCount(0)
    })

    for (const role of [organiser, lead, coordinator]) await role.context.close()
  })
})
