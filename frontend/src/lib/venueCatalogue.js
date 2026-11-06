/**
 * IS-61 CRUD in Venue Catalogue: Venue Staff add, edit and delete venues
 * (backend: app/venues/venue_service.py, POST /venues, POST and DELETE
 * /venues/<id>). Pure form helpers behind VenueFormView.vue and the delete
 * panel on VenueDetailView.vue, plus the calls themselves -- same split as
 * lib/roomLayouts.js.
 *
 * Facilities and accessibility provisions are the same closed lists an event
 * session asks for (EQUIPMENT_OPTIONS / ACCESSIBILITY_OPTIONS): venue search
 * and the suitability checks compare the two value for value, and the
 * backend refuses anything else.
 *
 * Operating hours (IS-11 AC5, added to the form 6 Nov): one opening and
 * closing time per venue, the same every day. Optional -- both empty means
 * no set hours -- but set as a pair. A closing time earlier than the opening
 * time closes the next day (20:00-01:00, or 08:00-00:00 for "until
 * midnight"); the two can't be the same. The venue
 * calendar shows the time outside them as unavailable, and a new booking
 * request must fit inside them (app.venues.booking_service).
 *
 * tentative_hold_minutes (Sprint 3, Josiah, "Venue Availability Calendar
 * Tentative Hold") is edited here too, alongside setup/turnaround -- folded
 * into this same CRUD form rather than a separate settings screen once
 * both landed on main at the same time; see docs/design-decisions.md.
 */
import { apiDelete, apiPost } from './api'
import { ACCESSIBILITY_OPTIONS, EQUIPMENT_OPTIONS, timeValue } from './eventSessions'

// The form has no status field: a new venue is always available, and an edit
// leaves the venue's status as it is (it's never sent).
export const NEW_VENUE_STATUS = 'available'

// Setup and turnaround buffers are at least this long (same as
// venue_service.MIN_BUFFER_MINUTES).
export const MIN_BUFFER_MINUTES = 5

// The tentative hold duration (Sprint 3, "Venue Availability Calendar
// Tentative Hold") is at least this long, and defaults to 24h for a new
// venue -- same as venue_service.MIN_HOLD_MINUTES / DEFAULT_HOLD_MINUTES.
export const MIN_HOLD_MINUTES = 1
export const DEFAULT_HOLD_MINUTES = 1440

export const FACILITY_OPTIONS = Object.freeze(EQUIPMENT_OPTIONS.map(({ value, label }) => ({ value, label })))
export const ACCESSIBILITY_FEATURE_OPTIONS = Object.freeze(
  ACCESSIBILITY_OPTIONS.map(({ value, label }) => ({ value, label })),
)

/** The form for a new venue: what the backend defaults to. */
export function emptyVenueForm() {
  return {
    name: '',
    location: '',
    capacity: '',
    facilities: [],
    accessibility_features: [],
    supported_layouts: [],
    setup_minutes: 30,
    turnaround_minutes: 30,
    tentative_hold_minutes: DEFAULT_HOLD_MINUTES,
    operating_hours_start: '',
    operating_hours_end: '',
  }
}

/** An existing venue as form state. */
export function venueToForm(venue) {
  return {
    name: venue.name ?? '',
    location: venue.location ?? '',
    capacity: venue.capacity ?? '',
    facilities: [...(venue.facilities ?? [])],
    accessibility_features: [...(venue.accessibility_features ?? [])],
    supported_layouts: [...(venue.supported_layouts ?? [])],
    setup_minutes: venue.setup_minutes ?? 30,
    turnaround_minutes: venue.turnaround_minutes ?? 30,
    tentative_hold_minutes: venue.tentative_hold_minutes ?? DEFAULT_HOLD_MINUTES,
    // "HH:MM:SS" from the database, "HH:MM" for <input type="time">.
    operating_hours_start: timeValue(venue.operating_hours_start),
    operating_hours_end: timeValue(venue.operating_hours_end),
  }
}

function wholeNumber(value) {
  if (value === '' || value === null || value === undefined) return NaN
  const number = Number(value)
  return Number.isInteger(number) ? number : NaN
}

/**
 * The form as the backend's venue body; numbers are sent as numbers, and
 * empty operating hours as null (no set hours).
 */
export function venuePayload(form) {
  return {
    name: form.name.trim(),
    location: form.location.trim(),
    capacity: wholeNumber(form.capacity),
    facilities: [...form.facilities],
    accessibility_features: [...form.accessibility_features],
    supported_layouts: [...form.supported_layouts],
    setup_minutes: wholeNumber(form.setup_minutes),
    turnaround_minutes: wholeNumber(form.turnaround_minutes),
    tentative_hold_minutes: wholeNumber(form.tentative_hold_minutes),
    operating_hours_start: form.operating_hours_start || null,
    operating_hours_end: form.operating_hours_end || null,
  }
}

/** The body for adding a venue: the form, as available. */
export function newVenuePayload(form) {
  return { ...venuePayload(form), status: NEW_VENUE_STATUS }
}

/**
 * Field -> message for everything wrong with the form ({} when it's fine).
 * Mirrors app.venues.venue_service._validated so most mistakes are caught
 * before a round trip; the backend still has the last word.
 */
export function validateVenueForm(form) {
  const errors = {}
  const payload = venuePayload(form)
  if (!payload.name) errors.name = 'Name is required.'
  if (!payload.location) errors.location = 'Location is required.'
  if (!(payload.capacity >= 1)) errors.capacity = 'Maximum capacity must be a whole number of at least 1.'
  if (!payload.supported_layouts.length) errors.supported_layouts = 'Choose at least one supported room layout.'
  if (!(payload.setup_minutes >= MIN_BUFFER_MINUTES)) {
    errors.setup_minutes = `Setup time must be a whole number of at least ${MIN_BUFFER_MINUTES} minutes.`
  }
  if (!(payload.turnaround_minutes >= MIN_BUFFER_MINUTES)) {
    errors.turnaround_minutes = `Turnaround time must be a whole number of at least ${MIN_BUFFER_MINUTES} minutes.`
  }
  if (!(payload.tentative_hold_minutes >= MIN_HOLD_MINUTES)) {
    errors.tentative_hold_minutes = `Tentative hold duration must be a whole number of at least ${MIN_HOLD_MINUTES} minute.`
  }
  const opens = payload.operating_hours_start
  const closes = payload.operating_hours_end
  if (Boolean(opens) !== Boolean(closes)) {
    errors.operating_hours = 'Set both an opening and a closing time, or leave both empty.'
  } else if (opens && closes === opens) {
    // An earlier closing time is fine: it closes the next day.
    errors.operating_hours =
      "Opening and closing times can't be the same. Leave both empty if the venue has no set hours."
  }
  return errors
}

/**
 * A venue's hours for display: "07:00 - 23:59 daily", "20:00 - 01:00 (next
 * day) daily", "08:00 - 00:00 (midnight) daily" or "No set hours".
 */
export function formatOperatingHours(start, end) {
  if (!start || !end) return 'No set hours'
  const opens = timeValue(start)
  const closes = timeValue(end)
  // "HH:MM" strings compare in time order.
  let note = ''
  if (closes === '00:00') note = ' (midnight)'
  else if (closes < opens) note = ' (next day)'
  return `${opens} - ${closes}${note} daily`
}


/**
 * Only the fields that differ from `venue`, for an edit -- the backend
 * writes just what it's sent. Lists compare by content, order included.
 */
export function changedFields(venue, form) {
  const before = venuePayload(venueToForm(venue))
  const after = venuePayload(form)
  return Object.fromEntries(
    Object.entries(after).filter(([field, value]) => JSON.stringify(value) !== JSON.stringify(before[field])),
  )
}

/**
 * Layout picker options: the active layouts, plus any the venue already
 * lists that have since been soft-deleted (the backend lets a venue keep
 * those, but not newly add one).
 */
export function layoutOptions(active, current = []) {
  const options = active.map((name) => ({ value: name, label: name }))
  for (const name of current) {
    if (!active.includes(name)) options.push({ value: name, label: `${name} (no longer offered)` })
  }
  return options
}

/** What the delete did, for the message shown after it. */
export function deleteOutcomeMessage(result) {
  const name = result?.venue?.name ?? 'The venue'
  const released = result?.released_bookings?.length ?? 0
  const returned = result?.returned_to_planning?.length ?? 0
  if (!released) return `${name} was deleted. No ongoing events had booked it.`
  const bookings = released === 1 ? '1 booking' : `${released} bookings`
  let message = `${name} was deleted. ${bookings} for ongoing events ${released === 1 ? 'was' : 'were'} released, and their coordinators will be asked to book another venue.`
  if (returned) {
    const sessions = returned === 1 ? '1 session' : `${returned} sessions`
    message += ` ${sessions} went back to planning.`
  }
  return message
}

export const createVenue = (body) => apiPost('/venues', body)
export const updateVenue = (venueId, changes) => apiPost(`/venues/${venueId}`, changes)
// Removes the venue's record; its bookings keep the venue's name.
export const deleteVenue = (venueId) => apiDelete(`/venues/${venueId}`)
