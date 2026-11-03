/**
 * Pure helpers behind the venue booking queue
 * (views/venues/VenueBookingQueueView.vue) and the request form
 * (views/venues/RequestVenueBookingView.vue), kept out of the components
 * so the grouping/validation rules can be unit-tested without mounting
 * anything -- same split as lib/coordinatorDashboard.js.
 *
 * Tab -> status mapping mirrors app.venues.booking_service.BOOKING_STATUSES
 * exactly (pending / confirmed / rejected / released / cancelled) --
 * there is no "needs more info" or in-between state for a venue booking,
 * unlike an event request.
 *
 * "released" (Sprint 3): a booking that left "confirmed" for a reason
 * OTHER than Venue Staff rejecting it or the coordinator cancelling it --
 * its event was cancelled entirely, its tentative hold expired, or its
 * venue was blocked. See app.venues.booking_release's own module
 * docstring.
 *
 * "cancelled" (IS-9): the coordinator cancels ONE booking directly,
 * without touching the event or the session's other bookings. Distinct
 * from "released", which is always system-initiated.
 */

export const BOOKING_TABS = Object.freeze([
  Object.freeze({ key: 'pending', label: 'Pending', statuses: Object.freeze(['pending']) }),
  Object.freeze({ key: 'confirmed', label: 'Confirmed', statuses: Object.freeze(['confirmed']) }),
  Object.freeze({ key: 'rejected', label: 'Rejected', statuses: Object.freeze(['rejected']) }),
  Object.freeze({ key: 'released', label: 'Released', statuses: Object.freeze(['released']) }),
  Object.freeze({ key: 'cancelled', label: 'Cancelled', statuses: Object.freeze(['cancelled']) }),
])

/** true if `key` names one of BOOKING_TABS (used to validate the ?tab= query param). */
export function isBookingTab(key) {
  return BOOKING_TABS.some((tab) => tab.key === key)
}

/** Splits bookings into { pending: [], confirmed: [], rejected: [] }. */
export function groupBookingsByTab(bookings) {
  const groups = Object.fromEntries(BOOKING_TABS.map((tab) => [tab.key, []]))
  for (const booking of bookings ?? []) {
    const tab = BOOKING_TABS.find((t) => t.statuses.includes(booking.status))
    if (tab) groups[tab.key].push(booking)
  }
  return groups
}

/**
 * Client-side validation for the request form. `venue_id` is the only
 * field this form collects -- every other requirement (capacity, dates,
 * layout, accessibility) already lives on the event session itself and
 * was validated when that session was created (see
 * app.venues.booking_service.create_booking_request, which reads them
 * from the event, not from this form).
 */
export function validateBookingForm(form) {
  return Boolean(form?.venue_id)
}

/**
 * IS-9: true if the coordinator may cancel this one booking -- same
 * conditions as rule_venue_booking_cancel: it is still pending or confirmed,
 * and the event isn't completed or cancelled. Cancelling it never touches the
 * session's other bookings.
 */
export function canCancelBooking(booking, event) {
  return ['pending', 'confirmed'].includes(booking?.status)
    && !['completed', 'cancelled'].includes(event?.status)
}

/**
 * Venue Availability Calendar Tentative Hold (Sprint 3): the date/time a
 * CONFIRMED booking's tentative hold expires, computed client-side from
 * confirmed_at + hold_minutes (both snapshotted onto the booking at
 * confirm time -- see app.venues.booking_service.confirm_booking). null
 * for a booking that was never confirmed, or is missing either field
 * (an older row from before this sprint, or a non-confirmed status where
 * the fields are meaningless). This is purely informational: the actual
 * expiry decision is the backend's (app.venues.booking_release), which
 * re-derives the same deadline server-side every time it's touched -- a
 * clock difference between browser and server only affects how early/
 * late this display looks, never whether the booking is actually live.
 */
export function holdExpiry(booking) {
  if (booking?.status !== 'confirmed') return null
  if (!booking.confirmed_at || typeof booking.hold_minutes !== 'number') return null
  const confirmedAt = new Date(booking.confirmed_at)
  if (Number.isNaN(confirmedAt.getTime())) return null
  return new Date(confirmedAt.getTime() + booking.hold_minutes * 60_000)
}

/** holdExpiry(booking), formatted for display: "3 Nov 2026, 14:30". null stays null. */
export function formatHoldExpiry(booking) {
  const expiry = holdExpiry(booking)
  if (!expiry) return null
  return expiry.toLocaleString('en-SG', {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

/**
 * IS-61: the bookings this session lost because Venue Staff deleted their
 * venue (released_by_venue_deletion) and hasn't replaced yet -- what the
 * "book another venue" alert on the event details page lists. A release
 * counts as replaced once the session has a pending or confirmed booking
 * made after it (released_at; updated_at only for a row released before that
 * column existed -- deleting the venue rewrites updated_at, so it can't be
 * trusted after one). So the alert stays while the coordinator still only
 * has bookings they made before the delete, and goes once they rebook.
 * Nothing is listed for a completed or cancelled event.
 */
export function unreplacedVenueReleases(bookings, event) {
  if (['completed', 'cancelled'].includes(event?.status)) return []
  // Anything but a list (an unexpected response) means no bookings, not a crash.
  const rows = Array.isArray(bookings) ? bookings : []
  const active = rows.filter((booking) => ['pending', 'confirmed'].includes(booking.status))
  return rows.filter(
    (booking) =>
      booking.released_by_venue_deletion
      && !active.some((other) => (other.created_at ?? '') > (booking.released_at ?? booking.updated_at ?? '')),
  )
}
