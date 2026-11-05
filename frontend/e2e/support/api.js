// Fast setup for e2e tests: drive the backend API directly, as each seeded
// role, to put an event request into the state a test starts from -- so a
// test of (say) the Safety Officer rejecting doesn't click through ten
// screens first. The browser is then used only for the step under test.
//
// Same endpoints and bodies the screens themselves send (see the comment on
// each helper), signed in the same way the app signs in: Supabase password
// login with the anon key, then a Bearer token on every API call. Reads
// frontend/.env for the Supabase URL, anon key and API base URL (or the same
// names from the environment, e.g. in CI).
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { SEED_PASSWORD, USERS } from './auth.js'

function loadEnv() {
  const env = { ...process.env }
  try {
    const text = readFileSync(fileURLToPath(new URL('../../.env', import.meta.url)), 'utf8')
    for (const line of text.split(/\r?\n/)) {
      const match = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/)
      if (match && env[match[1]] === undefined) env[match[1]] = match[2].replace(/^['"]|['"]$/g, '')
    }
  } catch {
    // No .env file (CI): everything comes from process.env.
  }
  return env
}

const env = loadEnv()
const SUPABASE_URL = env.VITE_SUPABASE_URL
const ANON_KEY = env.VITE_SUPABASE_ANON_KEY
const API_BASE_URL = env.VITE_API_BASE_URL || 'http://127.0.0.1:5000'

const tokens = new Map()

async function tokenFor(user) {
  if (tokens.has(user.email)) return tokens.get(user.email)
  if (!SUPABASE_URL || !ANON_KEY) throw new Error('VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY missing (frontend/.env).')
  const response = await fetch(`${SUPABASE_URL}/auth/v1/token?grant_type=password`, {
    method: 'POST',
    headers: { apikey: ANON_KEY, 'Content-Type': 'application/json' },
    body: JSON.stringify({ email: user.email, password: SEED_PASSWORD }),
  })
  const body = await response.json()
  if (!response.ok) throw new Error(`Couldn't sign in ${user.email}: ${body.error_description || body.msg || response.status}`)
  tokens.set(user.email, body.access_token)
  return body.access_token
}

/** One API call as `user`. Throws with the API's own message on failure. */
export async function call(user, method, path, body) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: { Authorization: `Bearer ${await tokenFor(user)}`, 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const text = await response.text()
  const data = text ? JSON.parse(text) : null
  if (!response.ok) throw new Error(`${method} ${path} as ${user.email} -> ${response.status}: ${data?.message || data?.error || text}`)
  return data
}

// -- dates --------------------------------------------------------------------

const pad = (n) => String(n).padStart(2, '0')
export const localDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`

/** A random far-future day (1-9 years out), so runs never clash over a
 * venue, equipment, or the coordinator's own calendar. */
export function farFutureDay() {
  const day = new Date()
  day.setDate(day.getDate() + 365 + Math.floor(Math.random() * 2900))
  return day
}

// -- setup steps, in lifecycle order ---------------------------------------------

/** Organiser creates and submits a one-session request (CreateEventView's
 * POST /events). Returns { eventId, name, day }. */
export async function createRequest(name, day = farFutureDay()) {
  const layouts = await call(USERS.organizer, 'GET', '/room-layouts')
  const layout = layouts.map((row) => (typeof row === 'string' ? row : row.name))[0]
  const group = await call(USERS.organizer, 'POST', '/events', {
    name,
    description: 'Created by an e2e test.',
    purpose: 'End-to-end testing.',
    sessions: [
      {
        preferred_start_date: localDate(day),
        preferred_start_time: '10:00',
        preferred_end_date: localDate(day),
        preferred_end_time: '12:00',
        expected_attendance: 20,
        accessibility_needs: [],
        room_layout: layout,
        equipment: [],
        registration_needs: false,
        registration_start_datetime: null,
        registration_end_datetime: null,
        special_requests: '',
      },
    ],
  })
  return { eventId: group.sessions[0].id, name, day }
}

/** Lead assigns the seeded coordinator (LeadDashboard's assign). */
export async function assignCoordinator(eventId, coordinator = USERS.coordinator) {
  const coordinators = await call(USERS.lead, 'GET', '/events/coordinators')
  const match = coordinators.find((c) => c.name === coordinator.name)
  if (!match) throw new Error(`Coordinator ${coordinator.name} not in /events/coordinators.`)
  await call(USERS.lead, 'POST', `/events/${eventId}/assign-coordinator`, { coordinator_id: match.id })
}

/** Coordinator approves, then starts planning (CoordinatorEventReview). */
export async function approveAndPlan(eventId) {
  await call(USERS.coordinator, 'POST', `/events/${eventId}/approve`, {})
  await call(USERS.coordinator, 'POST', `/events/${eventId}/start-planning`, {})
}

/** Coordinator requests a venue by name (RequestVenueBookingView). Returns the booking. */
export async function requestVenue(eventId, venueName = 'Grand Ballroom') {
  const venues = await call(USERS.coordinator, 'GET', '/venues')
  const venue = venues.find((v) => v.name === venueName)
  if (!venue) throw new Error(`Venue "${venueName}" not found -- run backend/seed.py.`)
  return call(USERS.coordinator, 'POST', `/events/${eventId}/venue-bookings`, { venue_id: venue.id })
}

/** Venue staff approve a booking (VenueBookingReviewView). */
export async function approveBooking(bookingId) {
  await call(USERS.venueStaff, 'POST', `/venues/bookings/${bookingId}/approve`, {})
}

/** Coordinator requests equipment by type name (RequestEquipmentView). Returns the request. */
export async function requestEquipment(eventId, typeName = 'projector', quantity = 1) {
  const types = await call(USERS.coordinator, 'GET', '/equipment/types')
  const type = types.find((t) => t.name === typeName)
  if (!type) throw new Error(`Equipment type "${typeName}" not found -- run backend/seed.py.`)
  return call(USERS.coordinator, 'POST', `/events/${eventId}/equipment-requests`, {
    items: [{ equipment_type_id: type.id, quantity, technical_requirements: null }],
  })
}

/** Coordinator submits for the safety check (SafetyCheckStatus). Returns the pending review's id. */
export async function submitForSafetyCheck(eventId) {
  await call(USERS.coordinator, 'POST', `/events/${eventId}/safety-review`, {})
  const reviews = await call(USERS.coordinator, 'GET', `/events/${eventId}/safety-reviews`)
  const pending = reviews.find((review) => review.status === 'pending')
  if (!pending) throw new Error('No pending safety review after submitting.')
  return pending.id
}

/** The session as `user` sees it (status etc.). */
export const getEvent = (eventId, user = USERS.organizer) => call(user, 'GET', `/events/${eventId}`)
