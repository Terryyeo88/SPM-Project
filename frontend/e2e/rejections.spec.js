// The ways an event request gets turned back, one test per branch. Each test
// puts its request into the right starting state through the API
// (support/api.js -- fast, no clicking), then does ONLY the rejection and
// what follows it in the browser. The golden path (golden-path.spec.js)
// already proves every screen on the way there works.
//
// Like the golden path, these run against whatever Supabase .env points at;
// every request is named "E2E Reject <...> <timestamp>" on a random
// far-future day.
import { expect, test } from '@playwright/test'
import { USERS, loginAs } from './support/auth.js'
import {
  approveAndPlan,
  approveBooking,
  assignCoordinator,
  createRequest,
  getEvent,
  requestEquipment,
  requestVenue,
  submitForSafetyCheck,
} from './support/api.js'

test.describe.configure({ timeout: 90_000 })

async function asRole(browser, user) {
  const context = await browser.newContext()
  const page = await context.newPage()
  await loginAs(page, user)
  return { context, page }
}

test('coordinator rejects with a reason; the organiser edits and resubmits', async ({ browser }) => {
  const { eventId } = await createRequest(`E2E Reject review ${Date.now()}`)
  await assignCoordinator(eventId)
  const reason = 'Please give a clearer purpose for the event.'

  await test.step('coordinator rejects with a reason', async () => {
    const { context, page } = await asRole(browser, USERS.coordinator)
    await page.goto(`/events/${eventId}`)
    await page.getByRole('button', { name: 'Reject Request' }).click()
    await page.locator('#reject-reason').fill(reason)
    await page.getByRole('button', { name: 'Confirm Rejection' }).click()
    await expect(page.getByText('Request rejected')).toBeVisible()
    await context.close()
  })

  await test.step('organiser sees the reason, edits the request and resubmits', async () => {
    const { context, page } = await asRole(browser, USERS.organizer)
    await page.goto(`/events/${eventId}`)
    await expect(page.getByText(reason)).toBeVisible()
    await page.getByLabel('Purpose of the Event').fill('End-to-end testing of the rejection and resubmission flow.')
    await page.getByRole('button', { name: 'Resubmit Request' }).click()
    await expect(page.getByText("Request resubmitted. It's back with the coordinator for review.")).toBeVisible()
    await context.close()
  })

  // A resubmitted request goes straight back to the coordinator who
  // rejected it -- rejected -> submitted -> under_review in one step
  // (test_resubmission_keeps_same_coordinator_and_returns_to_review).
  const event = await getEvent(eventId)
  expect(event.status).toBe('under_review')
  expect(event.purpose).toBe('End-to-end testing of the rejection and resubmission flow.')
})

test('safety officer rejects; the session goes back to planning with the comment', async ({ browser }) => {
  const { eventId } = await createRequest(`E2E Reject safety ${Date.now()}`)
  await assignCoordinator(eventId)
  await approveAndPlan(eventId)
  const booking = await requestVenue(eventId)
  await approveBooking(booking.id)
  const reviewId = await submitForSafetyCheck(eventId)
  const comment = 'Fire exits are blocked by the planned stage.'

  await test.step('safety officer rejects with a comment', async () => {
    const { context, page } = await asRole(browser, USERS.safetyOfficer)
    await page.goto(`/safety-reviews/${reviewId}`)
    await page.getByRole('button', { name: 'Reject', exact: true }).click()
    await page.locator('#safety-comment').fill(comment)
    await page.getByRole('button', { name: 'Confirm: Reject' }).click()
    await expect(page.getByRole('button', { name: 'Confirm: Reject' })).toHaveCount(0)
    await context.close()
  })

  await test.step('coordinator sees Planning, the comment, and can resubmit', async () => {
    const { context, page } = await asRole(browser, USERS.coordinator)
    await page.goto(`/events/${eventId}`)
    await expect(page.getByText(comment)).toBeVisible()
    await expect(page.getByRole('button', { name: 'Resubmit for Safety Check' })).toBeVisible()
    await context.close()
  })

  expect((await getEvent(eventId)).status).toBe('planning')
})

test('venue staff reject the booking; the safety check is then refused', async ({ browser }) => {
  const { eventId } = await createRequest(`E2E Reject venue ${Date.now()}`)
  await assignCoordinator(eventId)
  await approveAndPlan(eventId)
  const booking = await requestVenue(eventId)
  const reason = 'The ballroom is being refurbished that month.'

  await test.step('venue staff reject with a reason', async () => {
    const { context, page } = await asRole(browser, USERS.venueStaff)
    await page.goto(`/venues/bookings/${booking.id}`)
    await page.getByRole('button', { name: 'Reject Booking' }).click()
    await page.locator('#reject-reason').fill(reason)
    await page.getByRole('button', { name: 'Confirm Rejection' }).click()
    await expect(page.getByText('Booking rejected.')).toBeVisible()
    await context.close()
  })

  await test.step('coordinator can see the reason on the booking', async () => {
    const { context, page } = await asRole(browser, USERS.coordinator)
    await page.goto(`/venues/bookings/${booking.id}`)
    await expect(page.getByText(reason)).toBeVisible()
    await context.close()
  })

  await test.step('coordinator can request another venue, but not the safety check', async () => {
    const { context, page } = await asRole(browser, USERS.coordinator)
    await page.goto(`/events/${eventId}`)
    await expect(page.getByRole('link', { name: 'Request a different venue' })).toBeVisible()
    await page.getByRole('button', { name: 'Submit for Safety Check' }).click()
    await expect(page.getByRole('alert').filter({ hasText: 'No venue booking has been confirmed' })).toBeVisible()
    await context.close()
  })

  expect((await getEvent(eventId)).status).toBe('planning')
})

test('technical support reject the equipment request; the coordinator sees the reason', async ({ browser }) => {
  const { eventId } = await createRequest(`E2E Reject equipment ${Date.now()}`)
  await assignCoordinator(eventId)
  await approveAndPlan(eventId)
  const equipmentRequest = await requestEquipment(eventId)
  const reason = 'All projectors are booked for a conference that week.'

  await test.step('technical support reject with a reason', async () => {
    const { context, page } = await asRole(browser, USERS.technicalSupport)
    await page.goto(`/equipment/requests/${equipmentRequest.id}`)
    await page.locator('#reject-reason').fill(reason)
    await page.getByRole('button', { name: 'Reject request' }).click()
    await expect(page.getByRole('button', { name: 'Reject request' })).toHaveCount(0)
    await context.close()
  })

  await test.step('coordinator sees the request rejected, with the reason', async () => {
    const { context, page } = await asRole(browser, USERS.coordinator)
    await page.goto(`/events/${eventId}`)
    await expect(page.getByText(`Reason: ${reason}`)).toBeVisible()
    await context.close()
  })

  // Still planning: a rejected equipment request doesn't move the session.
  expect((await getEvent(eventId)).status).toBe('planning')
})
