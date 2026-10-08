/**
 * Pure helpers behind the Event Coordinator dashboard
 * (views/dashboard/CoordinatorDashboard.vue), kept out of the component
 * so the grouping rules can be unit-tested without mounting anything.
 *
 * Tab -> status mapping (team decision, following the Event Status
 * Management story's lifecycle):
 *   Needs Review -- under_review: assigned to this coordinator (by the Lead) and
 *                   waiting on an approve / reject / clarify decision.
 *                   (Assignment is what moves `submitted` -> `under_review`,
 *                   see backend coordinator_service.assign_initial_coordinator.)
 *   In Planning  -- approved, planning: approved, arrangements in progress.
 *   Confirmed    -- confirmed.
 *   Past         -- completed, cancelled, rejected: nothing left to act on.
 * `draft` and `submitted` never reach a coordinator (no coordinator is
 * assigned until after submission), so they belong to no tab.
 */

export const DASHBOARD_TABS = Object.freeze([
  Object.freeze({ key: 'needsReview', label: 'Needs Review', statuses: Object.freeze(['under_review']) }),
  Object.freeze({ key: 'inPlanning', label: 'In Planning', statuses: Object.freeze(['approved', 'planning']) }),
  Object.freeze({ key: 'confirmed', label: 'Confirmed', statuses: Object.freeze(['confirmed']) }),
  Object.freeze({
    key: 'past',
    label: 'Past',
    statuses: Object.freeze(['completed', 'cancelled', 'rejected']),
  }),
])

/** The dashboard tab key an event with this status belongs in, or null (draft/submitted). */
export function tabForStatus(status) {
  return DASHBOARD_TABS.find((tab) => tab.statuses.includes(status))?.key ?? null
}

/** true if `key` names one of DASHBOARD_TABS (used to validate the ?tab= query param). */
export function isDashboardTab(key) {
  return DASHBOARD_TABS.some((tab) => tab.key === key)
}

/**
 * Splits events into { needsReview: [], inPlanning: [], confirmed: [], past: [] }.
 *
 * Only events whose coordinator_id is `coordinatorId` are kept: GET /events
 * returns the UNION of a multi-role user's lists (e.g. someone who is both
 * an organiser and a coordinator also gets the events they organised), and
 * this dashboard is specifically "My Assigned Events".
 */
export function groupEventsByTab(events, coordinatorId) {
  const groups = Object.fromEntries(DASHBOARD_TABS.map((tab) => [tab.key, []]))
  for (const event of events ?? []) {
    if (!coordinatorId || event.coordinator_id !== coordinatorId) continue
    const tab = DASHBOARD_TABS.find((t) => t.statuses.includes(event.status))
    if (tab) groups[tab.key].push(event)
  }
  return groups
}

/** Case-insensitive match on the event name (the only searchable text the list endpoint returns today). */
export function filterBySearch(events, query) {
  const needle = (query ?? '').trim().toLowerCase()
  if (!needle) return events
  return events.filter((event) => (event.name ?? '').toLowerCase().includes(needle))
}

const _DATE_FORMAT = new Intl.DateTimeFormat('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })

function _formatDate(isoDate) {
  // Parse the YYYY-MM-DD parts directly -- `new Date('2027-02-22')` is UTC
  // midnight and can render as the previous day in negative-offset zones.
  const [year, month, day] = isoDate.split('-').map(Number)
  return _DATE_FORMAT.format(new Date(year, month - 1, day))
}

/** "22 Feb 2027", or "22 Feb 2027 – 24 Feb 2027" for multi-day events. */
export function formatDateRange(startDate, endDate) {
  if (!startDate) return 'Date not set'
  const start = _formatDate(startDate)
  if (!endDate || endDate === startDate) return start
  return `${start} – ${_formatDate(endDate)}`
}

/** "under_review" -> "Under Review" */
export function statusLabel(status) {
  return (status ?? '')
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

// -- One card per event request (same layout as the organiser's list) -------
// Sessions of one request share a shared_event_id; groupIntoRequests
// (lib/eventSessions) builds { key, name, sessions } in date order. The
// dashboard groups each TAB's sessions, so a request whose sessions are at
// different stages appears under each of those tabs with just its sessions
// for that tab.

/** The request's overall span: earliest session start to latest session end. */
export function requestDateRange(request) {
  const starts = request.sessions.map((s) => s.preferred_start_date).filter(Boolean).sort()
  const ends = request.sessions.map((s) => s.preferred_end_date || s.preferred_start_date).filter(Boolean).sort()
  if (!starts.length) return formatDateRange(null)
  return formatDateRange(starts[0], ends[ends.length - 1])
}

/**
 * One badge when every session is at the same stage, otherwise a count per
 * status (e.g. "2 Approved", "1 Planning") so nothing is hidden -- the same
 * rule as the organiser's list.
 */
export function requestStatusSummary(request) {
  const counts = new Map()
  for (const session of request.sessions) counts.set(session.status, (counts.get(session.status) || 0) + 1)
  if (counts.size === 1) {
    const [status] = counts.keys()
    return [{ status, label: statusLabel(status) }]
  }
  return [...counts.entries()].map(([status, count]) => ({ status, label: `${count} ${statusLabel(status)}` }))
}

/** How many of the request's sessions are waiting on the coordinator's review. */
export function sessionsAwaitingReview(request) {
  return request.sessions.filter((session) => session.status === 'under_review').length
}
