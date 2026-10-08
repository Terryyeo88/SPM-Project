/**
 * Pure helpers behind the equipment screens (Check Equipment Availability,
 * Nawaz, Sprint 2, IS-18): views/equipment/EquipmentRequestsView.vue,
 * EquipmentRequestDetailView.vue, EquipmentInventoryView.vue and
 * EquipmentDetailView.vue. Kept out of the components so the grouping,
 * wording and date rules can be unit-tested without mounting anything --
 * same split as lib/venueBookings.js.
 *
 * Tab -> status mapping mirrors app.equipment.equipment_service.
 * REQUEST_STATUSES exactly (pending / confirmed / rejected).
 */

export const REQUEST_TABS = Object.freeze([
  Object.freeze({ key: 'pending', label: 'Pending', statuses: Object.freeze(['pending']) }),
  Object.freeze({ key: 'confirmed', label: 'Confirmed', statuses: Object.freeze(['confirmed']) }),
  Object.freeze({ key: 'rejected', label: 'Rejected', statuses: Object.freeze(['rejected']) }),
])

/** true if `key` names one of REQUEST_TABS (used to validate the ?tab= query param). */
export function isRequestTab(key) {
  return REQUEST_TABS.some((tab) => tab.key === key)
}

/** Splits requests into { pending: [], confirmed: [], rejected: [] }. */
export function groupRequestsByTab(requests) {
  const groups = Object.fromEntries(REQUEST_TABS.map((tab) => [tab.key, []]))
  for (const request of requests ?? []) {
    const tab = REQUEST_TABS.find((t) => t.statuses.includes(request.status))
    if (tab) groups[tab.key].push(request)
  }
  return groups
}

/** "2 × projector, 1 × screen" -- the one-line summary of a request's lines. */
export function summariseItems(items) {
  if (!items || items.length === 0) return 'No items'
  return items.map((item) => `${item.quantity} × ${item.type}`).join(', ')
}

const UNIT_STATUS_LABELS = Object.freeze({
  available: 'In service',
  maintenance: 'Under maintenance',
  retired: 'Retired',
})

export function unitStatusLabel(status) {
  return UNIT_STATUS_LABELS[status] ?? status
}

/**
 * How one line of the availability check reads on screen. `state` drives
 * the colour/flag ("insufficient" is the AC's "System flags equipment
 * items where available quantity is less than the requested quantity");
 * `detail` explains the number rather than leaving staff to guess why it
 * is low -- how many units are out of service, how many are held for
 * other events.
 */
export function describeAvailability(item) {
  const sufficient = item.available >= item.requested
  const reasons = []
  if (item.out_of_service > 0) reasons.push(`${item.out_of_service} out of service`)
  if (item.reserved_by_others > 0) reasons.push(`${item.reserved_by_others} reserved for other events`)

  let detail = `${item.available} of ${item.total_units} units free`
  if (reasons.length) detail += ` (${reasons.join(', ')})`

  return {
    state: sufficient ? 'sufficient' : 'insufficient',
    label: sufficient ? 'Available' : `Short by ${item.requested - item.available}`,
    detail,
  }
}

/** Headline for the whole check: how many lines are flagged. */
export function summariseCheck(result) {
  const items = result?.items ?? []
  const flagged = items.filter((item) => item.available < item.requested).length
  if (items.length === 0) {
    return { flagged: 0, sufficient: true, message: 'This request has no items to check.' }
  }
  if (flagged === 0) {
    return { flagged, sufficient: true, message: 'Sufficient equipment is available for every item.' }
  }
  const noun = flagged === 1 ? 'item' : 'items'
  return { flagged, sufficient: false, message: `${flagged} ${noun} flagged: not enough equipment available.` }
}

// Venues, and so events, are in Singapore (see app.events.event_service.
// SINGAPORE_TZ): a request's period is shown in Singapore time whatever
// the viewer's own browser timezone is, so "09:00" means the same thing
// to everyone looking at it.
const DISPLAY_TZ = 'Asia/Singapore'

function _parts(iso) {
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: DISPLAY_TZ,
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(new Date(iso))
  const get = (type) => parts.find((p) => p.type === type)?.value
  return { date: `${get('day')} ${get('month')} ${get('year')}`, time: `${get('hour')}:${get('minute')}` }
}

/** "01 Dec 2026, 09:00 – 13:00" (same day) or "01 Dec 2026 09:00 – 02 Dec 2026 13:00". */
export function formatPeriod(startIso, endIso) {
  if (!startIso || !endIso) return ''
  const start = _parts(startIso)
  const end = _parts(endIso)
  if (start.date === end.date) return `${start.date}, ${start.time} – ${end.time}`
  return `${start.date} ${start.time} – ${end.date} ${end.time}`
}
