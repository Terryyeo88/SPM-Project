/**
 * Pure helpers behind the attendee screens (Attendee Registration, Justin),
 * laid out after the attendee wireframes:
 *   - views/dashboard/AttendeeDashboard.vue  (Dashboard-Attendee: search,
 *     Registered Events / Waiting List, search results as cards)
 *   - views/registrations/AttendeeEventView.vue  (EventDetail: spots filled,
 *     Register / Withdraw / Leave Waiting List)
 *   - components/RegistrationForm.vue  (the form behind Register, with the
 *     Edit Profile wireframe's fields)
 *
 * The backend is the authority on every rule (confirmed + enabled,
 * registration window, capacity, waiting list): these only decide what the
 * page SAYS, and mirror the backend's field checks so mistakes show as the
 * attendee types.
 */

/** Same pattern as backend registration_service.PHONE_PATTERN. */
const PHONE_PATTERN = /^\+?[0-9][0-9 -]{5,18}[0-9]$/
/** Same pattern as backend registration_service.EMAIL_PATTERN. */
const EMAIL_PATTERN = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
export const NOTES_MAX_LENGTH = 500

/** A session counts as "Almost Full" once this share of places is taken. */
const ALMOST_FULL_SHARE = 0.8

/**
 * Where a session's registration window stands at `now`:
 *   'open'     -- inside the window (or no window set)
 *   'upcoming' -- the window hasn't opened yet
 *   'closed'   -- the window has closed
 */
export function registrationState(session, now = new Date()) {
  const opens = session.registration_start_datetime ? new Date(session.registration_start_datetime) : null
  const closes = session.registration_end_datetime ? new Date(session.registration_end_datetime) : null
  if (opens && now < opens) return 'upcoming'
  if (closes && now > closes) return 'closed'
  return 'open'
}

/**
 * The tag on a search-result card (wireframe: Open / Almost Full / Waitlist
 * Only), plus Opens Soon / Registration Closed for windows that aren't open.
 * tone: 'open' | 'warn' | 'full' | 'muted'.
 */
export function availabilityTag(session, now = new Date()) {
  const state = registrationState(session, now)
  if (state === 'upcoming') return { label: 'Opens Soon', tone: 'muted' }
  if (state === 'closed') return { label: 'Registration Closed', tone: 'muted' }
  if (session.places_left === 0) return { label: 'Waitlist Only', tone: 'full' }
  if (session.capacity && session.confirmed_count / session.capacity >= ALMOST_FULL_SHARE) {
    return { label: 'Almost Full', tone: 'warn' }
  }
  return { label: 'Open', tone: 'open' }
}

/** "Spots filled 42 / 60" and the bar's width; null without a capacity. */
export function spotsFilled(session) {
  if (!session.capacity) return null
  const filled = Math.min(session.confirmed_count ?? 0, session.capacity)
  return { filled, capacity: session.capacity, percent: Math.round((filled / session.capacity) * 100) }
}

/** "18 spots left", "1 spot left", "Full -- you'll join the waiting list". */
export function placesLabel(session) {
  if (session.places_left === null || session.places_left === undefined) return 'Spots available'
  if (session.places_left === 0) return "Full -- you'll join the waiting list"
  return `${session.places_left} ${session.places_left === 1 ? 'spot' : 'spots'} left`
}

/**
 * Search, as on the dashboard wireframe: by event name (case-insensitive)
 * and/or date (a session running on that day). Location isn't searchable
 * yet -- no event has a venue until venue booking exists.
 */
export function filterSessions(sessions, { query = '', date = '' } = {}) {
  const needle = query.trim().toLowerCase()
  return (sessions ?? []).filter((session) => {
    if (needle && !(session.name ?? '').toLowerCase().includes(needle)) return false
    if (date) {
      const start = session.preferred_start_date
      const end = session.preferred_end_date || start
      if (!start || date < start || date > end) return false
    }
    return true
  })
}

/**
 * Starting values for the register form, prefilled from the signed-in
 * user's profile (GET /me). Name and email exist on profiles today. Phone,
 * organisation and notification choices don't yet -- once a profile story
 * adds `phone`, `organisation`, `notify_email` / `notify_sms`, they prefill
 * here with no other change. Name and organisation are shown, not edited:
 * the attendee only chooses whether their organisation is included.
 */
export function prefillFromProfile(profile) {
  const hasChoice = typeof profile?.notify_email === 'boolean' || typeof profile?.notify_sms === 'boolean'
  return {
    name: profile?.name ?? '',
    email: profile?.email ?? '',
    phone: profile?.phone ?? '',
    organisation: profile?.organisation ?? '',
    include_organisation: Boolean(profile?.organisation),
    notify_email: hasChoice ? Boolean(profile.notify_email) : true,
    notify_sms: hasChoice ? Boolean(profile.notify_sms) : false,
    notes: '',
  }
}

/** The request body for POST /registrations/<id> from the form's values. */
export function registrationPayload(form) {
  return {
    email: form.email.trim(),
    phone: form.phone.trim(),
    notify_email: Boolean(form.notify_email),
    notify_sms: Boolean(form.notify_sms),
    include_organisation: Boolean(form.organisation && form.include_organisation),
    notes: form.notes.trim() || undefined,
  }
}

/** Error message for the email field, or '' if it's fine. */
export function emailError(email) {
  const value = (email ?? '').trim()
  if (!value) return 'An email address is required to register.'
  if (value.length > 254 || !EMAIL_PATTERN.test(value)) return 'Enter a valid email address.'
  return ''
}

/** Error message for the phone field, or '' if it's fine. */
export function phoneError(phone) {
  const value = (phone ?? '').trim()
  if (!value) return 'A phone number is required to register.'
  if (!PHONE_PATTERN.test(value)) return 'Enter a valid phone number, e.g. 9123 4567 or +65 9123 4567.'
  return ''
}

/** Error message for the notification checkboxes, or ''. */
export function notifyError(form) {
  return form.notify_email || form.notify_sms ? '' : 'Choose at least one way to be notified.'
}

/** Error message for the notes field, or ''. */
export function notesError(notes) {
  return (notes ?? '').trim().length > NOTES_MAX_LENGTH ? `Notes can be at most ${NOTES_MAX_LENGTH} characters.` : ''
}

const _SGT = new Intl.DateTimeFormat('en-SG', {
  timeZone: 'Asia/Singapore', day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit',
})

/** A timestamptz shown in Singapore time, e.g. "3 Nov 2026, 2:00 pm". */
export function formatSgt(value) {
  return value ? _SGT.format(new Date(value)) : ''
}

/** "Confirmed" / "Waitlisted (#2)" */
export function registrationStatusLabel(registration) {
  if (registration.status === 'waitlisted') {
    return registration.waitlist_position ? `Waitlisted (#${registration.waitlist_position})` : 'Waitlisted'
  }
  return 'Confirmed'
}

/** "3 Nov 2026 · 14:00–16:00" for a session's date and times. */
export function sessionWhen(session, formatDateRange) {
  if (!session) return ''
  const range = formatDateRange(session.preferred_start_date, session.preferred_end_date)
  const start = (session.preferred_start_time || '').slice(0, 5)
  const end = (session.preferred_end_time || '').slice(0, 5)
  return start ? `${range} · ${start}${end ? `–${end}` : ''}` : range
}
