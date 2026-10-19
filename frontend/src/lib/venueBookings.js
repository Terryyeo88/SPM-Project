/**
 * Pure helpers behind the venue booking queue
 * (views/venues/VenueBookingQueueView.vue) and the request form
 * (views/venues/RequestVenueBookingView.vue), kept out of the components
 * so the grouping/validation rules can be unit-tested without mounting
 * anything -- same split as lib/coordinatorDashboard.js.
 *
 * Tab -> status mapping mirrors app.venues.booking_service.BOOKING_STATUSES
 * (pending / confirmed / rejected / cancelled) -- there is no "needs more
 * info" or in-between state for a venue booking, unlike an event request.
 */

export const BOOKING_TABS = Object.freeze([
  Object.freeze({ key: 'pending', label: 'Pending', statuses: Object.freeze(['pending']) }),
  Object.freeze({ key: 'confirmed', label: 'Confirmed', statuses: Object.freeze(['confirmed']) }),
  Object.freeze({ key: 'rejected', label: 'Rejected', statuses: Object.freeze(['rejected']) }),
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
