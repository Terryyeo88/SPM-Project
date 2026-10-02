// Shared form logic for multi-session event requests, used by both
// CreateEventView and EventDetailsView. Each session becomes its own row in
// the events table; the backend links them with a shared_event_id.
//
// A session's form state uses <input type="datetime-local"> values
// ("YYYY-MM-DDTHH:mm"), which compare lexicographically the same as
// chronologically -- every ordering check below relies on that.

export const DRAFT_NAME = 'Untitled event request'

export const ROOM_LAYOUTS = ['theatre', 'classroom', 'boardroom', 'seminar', 'banquet', 'networking']
export const EQUIPMENT_OPTIONS = [
  { value: 'microphone', label: 'Microphones', hasQuantity: true },
  { value: 'projector', label: 'Projectors', hasQuantity: true },
  { value: 'screen', label: 'Screens', hasQuantity: true },
  { value: 'wifi', label: 'WiFi', hasQuantity: false },
]
export const ACCESSIBILITY_OPTIONS = [
  { value: 'wheelchair_access', label: 'Wheelchair access', hasQuantity: false },
  { value: 'lift_access', label: 'Lift access', hasQuantity: false },
  { value: 'removable_seats', label: 'Removable seats', hasQuantity: true },
  { value: 'extra_legroom_seats', label: 'Seats with extra legroom', hasQuantity: true },
]

export function localDateString(date) {
  const offset = date.getTimezoneOffset()
  return new Date(date.getTime() - offset * 60 * 1000).toISOString().slice(0, 10)
}

/** Earliest allowed session start date: tomorrow, in local time. */
export function minimumStartDate(now = new Date()) {
  return localDateString(new Date(now.getTime() + 24 * 60 * 60 * 1000))
}

export function timeValue(value) {
  return value ? value.slice(0, 5) : ''
}

// The session's date and time columns are combined into one datetime-local
// value for display, and split back apart before anything is sent -- the
// backend only knows about the separate date/time columns.
export function combineDateTime(datePart, timePart) {
  if (!datePart) return ''
  return `${datePart}T${timeValue(timePart) || '00:00'}`
}

export function splitDateTime(value) {
  if (!value) return { date: '', time: '' }
  const [date, time] = value.split('T')
  return { date: date || '', time: time || '' }
}

// The registration window columns are timestamptz, so they travel as full
// ISO strings with an offset, and are shown in the browser's local time.
export function isoToLocalInput(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return `${localDateString(date)}T${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}

export function localInputToIso(value) {
  if (!value) return null
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? null : date.toISOString()
}

let nextKey = 0

export function emptySession() {
  nextKey += 1
  return {
    key: nextKey,
    id: null,
    status: 'draft',
    preferred_start_datetime: '',
    preferred_end_datetime: '',
    expected_attendance: '',
    accessibility_needs: [],
    room_layout: '',
    equipment: [],
    registration_needs: false,
    registration_start_datetime: '',
    registration_end_datetime: '',
    special_requests: '',
    errors: {},
  }
}

export function sessionFromEvent(row) {
  return {
    ...emptySession(),
    id: row.id,
    status: row.status,
    preferred_start_datetime: combineDateTime(row.preferred_start_date, row.preferred_start_time),
    preferred_end_datetime: combineDateTime(row.preferred_end_date, row.preferred_end_time),
    expected_attendance: row.expected_attendance || '',
    accessibility_needs: (row.accessibility_needs || []).map((entry) => ({ ...entry })),
    room_layout: row.room_layout || '',
    equipment: (row.equipment_needed?.equipment || []).map((entry) => ({ ...entry })),
    registration_needs: row.registration_needs || false,
    registration_start_datetime: isoToLocalInput(row.registration_start_datetime),
    registration_end_datetime: isoToLocalInput(row.registration_end_datetime),
    special_requests: row.special_requests || '',
  }
}

export function sessionPayload(session) {
  const start = splitDateTime(session.preferred_start_datetime)
  const end = splitDateTime(session.preferred_end_datetime)
  const payload = {
    preferred_start_date: start.date,
    preferred_start_time: start.time,
    preferred_end_date: end.date,
    preferred_end_time: end.time,
    expected_attendance: session.expected_attendance === '' ? null : Number(session.expected_attendance),
    accessibility_needs: session.accessibility_needs,
    room_layout: session.room_layout,
    equipment: session.equipment,
    registration_needs: session.registration_needs,
    registration_start_datetime: session.registration_needs ? localInputToIso(session.registration_start_datetime) : null,
    registration_end_datetime: session.registration_needs ? localInputToIso(session.registration_end_datetime) : null,
    special_requests: session.special_requests,
  }
  if (session.id) payload.id = session.id
  return payload
}

export function sessionHasData(session) {
  return [
    session.preferred_start_datetime,
    session.preferred_end_datetime,
    session.expected_attendance,
    session.room_layout,
    session.special_requests,
    session.registration_start_datetime,
    session.registration_end_datetime,
  ].some((value) => String(value ?? '').trim() !== '')
    || session.registration_needs
    || session.accessibility_needs.length > 0
    || session.equipment.length > 0
}

/** Every rule that can fail on a value the user has actually entered. */
function invalidInputs(session, minimumDate) {
  const startDate = splitDateTime(session.preferred_start_datetime).date
  const start = session.preferred_start_datetime
  const regStart = session.registration_start_datetime
  const regEnd = session.registration_end_datetime
  return {
    attendance: session.expected_attendance !== '' && Number(session.expected_attendance) <= 0,
    start: Boolean(startDate) && startDate < minimumDate,
    // The combined start-before-end check (not two separate date/time
    // rules), so an end time earlier than the start time is correctly
    // allowed as long as the end DATE is later (22:00 to 06:00 next day).
    range: Boolean(start && session.preferred_end_datetime && session.preferred_end_datetime <= start),
    registrationRange: Boolean(session.registration_needs && regStart && regEnd && regEnd <= regStart),
    registrationClose: Boolean(session.registration_needs && regEnd && start && regEnd > start),
    equipment: session.equipment.some((entry) => entry.quantity < 1),
    accessibility: session.accessibility_needs.some((entry) => entry.quantity !== undefined && entry.quantity < 1),
  }
}

export function sessionHasInvalidInput(session, minimumDate) {
  return Object.values(invalidInputs(session, minimumDate)).some(Boolean)
}

export function sessionIsComplete(session, minimumDate) {
  const hasRequired = [session.preferred_start_datetime, session.preferred_end_datetime, session.room_layout]
    .every((value) => String(value ?? '').trim() !== '')
  const hasRegistrationWindow = !session.registration_needs
    || Boolean(session.registration_start_datetime && session.registration_end_datetime)
  return hasRequired
    && hasRegistrationWindow
    && Number(session.expected_attendance) > 0
    && !sessionHasInvalidInput(session, minimumDate)
}

// -- Reactive (as-you-type) validation ---------------------------------------
// Each of these only flags values that ARE filled in but wrong -- a field
// that's still empty is naturally empty while the user fills in the others.
// The "required" checks belong only to validateSession(), run at submit time.

export function validateDateRange(session, minimumDate) {
  const { errors } = session
  delete errors.preferred_start_datetime
  delete errors.preferred_end_datetime
  const invalid = invalidInputs(session, minimumDate)
  // The start field is the one being edited when this runs, so clearing it
  // is flagged straight away (as before); the END field's "required" check
  // waits for validateSession(), since it's still empty while the start is
  // being filled in first.
  if (!session.preferred_start_datetime) errors.preferred_start_datetime = 'Preferred start date and time is required.'
  else if (invalid.start) errors.preferred_start_datetime = 'Preferred start date must be after today.'
  if (invalid.range) errors.preferred_end_datetime = 'End date and time must be after the start date and time.'
  // The registration close is checked against the session start, so it
  // has to be re-checked whenever the start moves too.
  validateRegistrationWindow(session, minimumDate)
}

export function validateAttendance(session) {
  delete session.errors.expected_attendance
  if (session.expected_attendance !== '' && Number(session.expected_attendance) <= 0) {
    session.errors.expected_attendance = 'Expected attendance must be greater than zero.'
  }
}

export function validateRegistrationWindow(session, minimumDate) {
  const { errors } = session
  delete errors.registration_start_datetime
  delete errors.registration_end_datetime
  const invalid = invalidInputs(session, minimumDate)
  if (invalid.registrationRange) {
    errors.registration_end_datetime = 'Registration must close after it opens.'
  } else if (invalid.registrationClose) {
    errors.registration_end_datetime = 'Registration must close on or before the session starts.'
  }
}

export function validateQuantities(session) {
  const { errors } = session
  delete errors.equipment
  delete errors.accessibility_needs
  if (session.equipment.some((entry) => entry.quantity < 1)) {
    errors.equipment = 'Equipment quantities must be at least 1.'
  }
  if (session.accessibility_needs.some((entry) => entry.quantity !== undefined && entry.quantity < 1)) {
    errors.accessibility_needs = 'Accessibility quantities must be at least 1.'
  }
}

/** Full check at submit time, including required fields. Returns true when valid. */
export function validateSession(session, minimumDate) {
  Object.keys(session.errors).forEach((field) => delete session.errors[field])
  validateDateRange(session, minimumDate)
  if (!session.preferred_end_datetime) {
    session.errors.preferred_end_datetime = 'Preferred end date and time is required.'
  }
  validateAttendance(session)
  if (session.expected_attendance === '') {
    session.errors.expected_attendance = 'Expected attendance is required.'
  }
  if (!session.room_layout) session.errors.room_layout = 'Please select a room layout.'
  if (session.registration_needs) {
    if (!session.registration_start_datetime) {
      session.errors.registration_start_datetime = 'Registration opening date and time is required.'
    }
    if (!session.registration_end_datetime) {
      session.errors.registration_end_datetime = 'Registration closing date and time is required.'
    }
  }
  validateQuantities(session)
  return Object.keys(session.errors).length === 0
}
