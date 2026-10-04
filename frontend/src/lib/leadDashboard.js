/**
 * Pure helpers behind the Event Coordinator Lead dashboard
 * (views/dashboard/LeadDashboard.vue) -- Week 7 customer change #5:
 *
 *   "Newly submitted event requests should no longer be assigned directly
 *   to an Event Coordinator. Instead, they first enter an unassigned queue
 *   that can be viewed by the Event Coordinator Lead. The Lead can review
 *   basic event information, assign a suitable Event Coordinator, and
 *   reassign events where necessary. ... the Event Coordinator Lead should
 *   be able to view all coordinator assignments and active events under
 *   their supervision."
 *
 * The Lead works with REQUESTS, not session rows: GET /events returns one
 * row per session, and every session of a request shares a
 * shared_event_id and one coordinator (assigning or reassigning moves them
 * all). So rows are first folded into requests (groupRequests), then
 * sorted into tabs:
 *
 *   Unassigned -- a session still `submitted` with nobody assigned: the
 *                 queue the Lead assigns from.
 *   Assigned   -- active and assigned (under_review, approved, planning,
 *                 confirmed), shown per coordinator.
 *   Past       -- every session finished (completed, cancelled, rejected).
 */

export const ACTIVE_STATUSES = Object.freeze(['under_review', 'approved', 'planning', 'confirmed'])
export const PAST_STATUSES = Object.freeze(['completed', 'cancelled', 'rejected'])

export const LEAD_TABS = Object.freeze([
  Object.freeze({ key: 'unassigned', label: 'Unassigned' }),
  Object.freeze({ key: 'assigned', label: 'Assigned' }),
  Object.freeze({ key: 'past', label: 'Past' }),
])

/** true if `key` names one of LEAD_TABS (validates the ?tab= query param). */
export function isLeadTab(key) {
  return LEAD_TABS.some((tab) => tab.key === key)
}

function _sessionSortKey(row) {
  return `${row.preferred_start_date || '9999-12-31'} ${row.preferred_start_time || ''}`
}

/**
 * Folds session rows into one entry per request:
 *   { key, name, sessions (chronological), startDate, endDate,
 *     coordinatorId, statuses (distinct, in session order),
 *     expectedAttendance (largest session) }
 * A request created before sessions existed has no shared_event_id and is
 * a request of one. Drafts are skipped -- the Lead never sees them.
 */
export function groupRequests(events) {
  const byKey = new Map()
  for (const event of events ?? []) {
    if (event.status === 'draft') continue
    const key = event.shared_event_id || event.id
    if (!byKey.has(key)) byKey.set(key, [])
    byKey.get(key).push(event)
  }
  return [...byKey.entries()].map(([key, rows]) => {
    const sessions = [...rows].sort((a, b) => _sessionSortKey(a).localeCompare(_sessionSortKey(b)))
    const dates = sessions.flatMap((s) => [s.preferred_start_date, s.preferred_end_date]).filter(Boolean).sort()
    return {
      key,
      name: sessions[0].name,
      sessions,
      startDate: dates[0] ?? null,
      endDate: dates[dates.length - 1] ?? null,
      coordinatorId: sessions.find((s) => s.coordinator_id)?.coordinator_id ?? null,
      statuses: [...new Set(sessions.map((s) => s.status))],
      expectedAttendance: Math.max(0, ...sessions.map((s) => s.expected_attendance || 0)) || null,
    }
  })
}

/** Which tab a request (from groupRequests) belongs in. */
export function leadTabForRequest(request) {
  if (request.sessions.some((s) => s.status === 'submitted' && !s.coordinator_id)) return 'unassigned'
  if (request.sessions.every((s) => PAST_STATUSES.includes(s.status))) return 'past'
  return 'assigned'
}

/** { unassigned: [], assigned: [], past: [] }, each soonest-first. */
export function groupForLead(events) {
  const groups = Object.fromEntries(LEAD_TABS.map((tab) => [tab.key, []]))
  for (const request of groupRequests(events)) groups[leadTabForRequest(request)].push(request)
  for (const list of Object.values(groups)) {
    list.sort((a, b) => (a.startDate || '9999-12-31').localeCompare(b.startDate || '9999-12-31'))
  }
  return groups
}

/**
 * The Assigned tab's per-coordinator sections: one per coordinator in
 * `coordinators` (GET /events/coordinators, sorted by name) -- including
 * those with nothing assigned, so the Lead sees who is free -- each with
 * their requests. A request whose coordinator isn't in that list (e.g.
 * the role was since removed) still shows, under "Unknown coordinator".
 */
export function groupByCoordinator(requests, coordinators) {
  const sections = (coordinators ?? []).map((coordinator) => ({ coordinator, requests: [] }))
  const byId = new Map(sections.map((section) => [section.coordinator.id, section]))
  for (const request of requests ?? []) {
    let section = byId.get(request.coordinatorId)
    if (!section) {
      section = { coordinator: { id: request.coordinatorId, name: 'Unknown coordinator' }, requests: [] }
      byId.set(request.coordinatorId, section)
      sections.push(section)
    }
    section.requests.push(request)
  }
  return sections
}

/** The session id to POST assign-coordinator against: any session still in the queue. */
export function assignTargetId(request) {
  return request.sessions.find((s) => s.status === 'submitted' && !s.coordinator_id)?.id ?? null
}

/** The session id to POST reassign-coordinator against: an unfinished one held by the request's coordinator. */
export function reassignTargetId(request) {
  const held = request.sessions.filter((s) => s.coordinator_id && s.coordinator_id === request.coordinatorId)
  return (held.find((s) => s.status !== 'completed') ?? null)?.id ?? null
}

/** Case-insensitive match on the request name. */
export function filterRequests(requests, query) {
  const needle = (query ?? '').trim().toLowerCase()
  if (!needle) return requests
  return requests.filter((request) => (request.name ?? '').toLowerCase().includes(needle))
}
