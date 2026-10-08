/**
 * Pure helpers behind IS-21 Request for Event Change
 * (components/EventChangeRequests.vue), kept out of the component so the
 * diffing and display rules can be unit-tested without mounting anything
 * -- same split as lib/venueBookings.js.
 *
 * Once a request is submitted the organiser can't edit it; they ask for a
 * change (POST /events/<id>/change-requests) and the assigned coordinator
 * approves or rejects it. The backend
 * (app.events.change_request_service) is the authority on what actually
 * changes -- buildChanges here only keeps the request small and lets the
 * form say "nothing changed" before a round trip.
 */
import { ACCESSIBILITY_OPTIONS, EQUIPMENT_OPTIONS, sessionFromEvent, sessionPayload } from './eventSessions'

// Same window as CHANGE_REQUEST_STATUSES in app/authz/rules.py: submitted
// up to confirmed. Draft and rejected are edited directly instead.
export const CHANGE_REQUEST_STATUSES = Object.freeze(['submitted', 'under_review', 'approved', 'planning', 'confirmed'])

export const SHARED_FIELDS = Object.freeze(['name', 'description', 'purpose'])

export const FIELD_LABELS = Object.freeze({
  name: 'Event name',
  description: 'Description',
  purpose: 'Purpose',
  preferred_start_date: 'Start date',
  preferred_start_time: 'Start time',
  preferred_end_date: 'End date',
  preferred_end_time: 'End time',
  expected_attendance: 'Expected attendance',
  room_layout: 'Room layout',
  accessibility_needs: 'Accessibility needs',
  equipment: 'Equipment',
  registration_needs: 'Registration needed',
  registration_start_datetime: 'Registration opens',
  registration_end_datetime: 'Registration closes',
  special_requests: 'Special requests',
})

const ITEM_LABELS = Object.fromEntries(
  [...EQUIPMENT_OPTIONS, ...ACCESSIBILITY_OPTIONS].map((option) => [option.value, option.label]),
)

/** true if a change may be requested for a session in this status. */
export function isChangeable(status) {
  return CHANGE_REQUEST_STATUSES.includes(status)
}

/** An event row in the change request's field names (the event API's). */
export function eventFields(row) {
  const { id, ...session } = sessionPayload(sessionFromEvent(row))
  return { name: row.name || '', description: row.description || '', purpose: row.purpose || '', ...session }
}

function same(a, b) {
  const blank = (value) => value === '' || value === null || value === undefined
  if (blank(a) && blank(b)) return true
  return JSON.stringify(a) === JSON.stringify(b)
}

/**
 * The fields the organiser actually changed: `row` is the session as it is
 * now, `form` is { name, description, purpose, session } where `session` is
 * EventSessionFields' state (lib/eventSessions). Both go through the same
 * transform, so e.g. "09:00:00" from the database and "09:00" from the form
 * compare equal.
 */
export function buildChanges(row, form) {
  const before = eventFields(row)
  const { id, ...session } = sessionPayload(form.session)
  const after = { name: form.name, description: form.description, purpose: form.purpose, ...session }
  return Object.fromEntries(Object.entries(after).filter(([field, value]) => !same(value, before[field])))
}

/** The pending change request for one session, if there is one. */
export function pendingChangeFor(changes, eventId) {
  return (changes ?? []).find((change) => change.event_id === eventId && change.status === 'pending') ?? null
}

function describeItems(items) {
  if (!items?.length) return 'None'
  return items
    .map((entry) => {
      const quantity = entry.quantity && entry.item !== 'wifi' ? ` × ${entry.quantity}` : ''
      const notes = entry.notes ? ` (${entry.notes})` : ''
      return `${ITEM_LABELS[entry.item] ?? entry.item}${quantity}${notes}`
    })
    .join(', ')
}

/** One requested value as the reviewer reads it. */
export function describeValue(field, value) {
  if (field === 'equipment' || field === 'accessibility_needs') return describeItems(value)
  if (field === 'registration_needs') return value ? 'Yes' : 'No'
  if (value === null || value === undefined || value === '') return 'Not set'
  if (field === 'preferred_start_time' || field === 'preferred_end_time') return String(value).slice(0, 5)
  if (field === 'registration_start_datetime' || field === 'registration_end_datetime') {
    const date = new Date(value)
    return Number.isNaN(date.getTime())
      ? String(value)
      : date.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
  }
  if (field === 'room_layout') return String(value).charAt(0).toUpperCase() + String(value).slice(1)
  return String(value)
}

/** [{ field, label, from, to }] for a change request, in FIELD_LABELS order. */
export function describeChange(change) {
  const requested = change?.requested_changes ?? {}
  const previous = change?.previous_values ?? {}
  return Object.keys(FIELD_LABELS)
    .filter((field) => field in requested)
    .map((field) => ({
      field,
      label: FIELD_LABELS[field],
      from: describeValue(field, previous[field]),
      to: describeValue(field, requested[field]),
    }))
}

/**
 * One event_logs entry (GET /events/<id>/logs) as [{ field, label, from, to }]:
 * what actually changed, as opposed to a change request's what-was-asked.
 */
export function describeLogEntry(entry) {
  const changes = entry?.changes ?? {}
  return Object.keys(FIELD_LABELS)
    .filter((field) => field in changes)
    .map((field) => ({
      field,
      label: FIELD_LABELS[field],
      from: describeValue(field, changes[field]?.from),
      to: describeValue(field, changes[field]?.to),
    }))
}

/** true if approving this change renames/redescribes every session of the request. */
export function touchesSharedDetails(change) {
  return SHARED_FIELDS.some((field) => field in (change?.requested_changes ?? {}))
}

/**
 * What approving a pending change would disturb, as the backend assessed it
 * (app.events.change_impact): [{ area, severity, title, issues }]. Empty for
 * a decided change or one that touches nothing already arranged.
 */
export function impactsOf(change) {
  return change?.status === 'pending' && Array.isArray(change.impact) ? change.impact : []
}

/** The distinct areas to acknowledge when approving -- what the backend checks. */
export function impactAreas(change) {
  return [...new Set(impactsOf(change).map((impact) => impact.area))]
}

export const CHANGE_STATUS_LABELS = Object.freeze({
  pending: 'Awaiting review',
  approved: 'Approved',
  rejected: 'Rejected',
})
