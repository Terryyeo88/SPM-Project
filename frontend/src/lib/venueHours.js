/**
 * IS-11 AC5 (Nawaz, 6 Nov): "periods outside the venue's operating hours
 * are shown as unavailable" on the venue availability calendar.
 *
 * The hours are one window per venue, the same every day
 * (venues.operating_hours_start/end, set on the venue form). They aren't
 * entries the backend stores, so the calendar works them out here, for each
 * day of the visible range, and shows them next to the bookings and blocks.
 *
 * Times are the venue's local time (Singapore), read in the browser's own
 * time zone like the rest of the calendar (lib/calendar.js).
 */
import { addDays } from './calendar'
import { timeValue } from './eventSessions'

export const OUTSIDE_HOURS_STATE = 'outside_hours'

// A closing time of 23:59 is how "open until midnight" is entered; the
// minute after it isn't worth an entry of its own.
const OPEN_UNTIL_MIDNIGHT = '23:59'

// A local time on `day`, as a UTC ISO string: the backend's timestamps come
// back in UTC too, so the two sort together as text (sortedByStart in
// lib/calendar.js).
function at(day, hhmm) {
  const [hours, minutes] = hhmm.split(':').map(Number)
  const local = new Date(day)
  local.setHours(hours, minutes, 0, 0)
  return local.toISOString()
}

/**
 * Calendar entries for the time outside the venue's hours on every day of
 * [range.start, range.end): none when the venue has no set hours.
 *
 * Day and week views list the closed periods themselves (before opening,
 * after closing). The month grid has no hour axis, so it gets one entry a
 * day giving the hours instead.
 */
export function outsideHoursEntries(range, start, end, view) {
  const opens = timeValue(start)
  const closes = timeValue(end)
  if (!opens || !closes) return []

  const entries = []
  for (let day = range.start; day < range.end; day = addDays(day, 1)) {
    const base = { type: 'outside_hours', state: OUTSIDE_HOURS_STATE, opens, closes }
    if (view === 'month') {
      entries.push({ ...base, period: 'day', start: at(day, '00:00'), end: at(addDays(day, 1), '00:00') })
      continue
    }
    if (opens > '00:00') {
      entries.push({ ...base, period: 'before_opening', start: at(day, '00:00'), end: at(day, opens) })
    }
    if (closes < OPEN_UNTIL_MIDNIGHT) {
      entries.push({ ...base, period: 'after_closing', start: at(day, closes), end: at(addDays(day, 1), '00:00') })
    }
  }
  return entries
}

/** What an outside-hours entry says on the calendar. */
export function outsideHoursLabel(entry) {
  if (entry.period === 'before_opening') return `Closed until ${entry.opens}`
  if (entry.period === 'after_closing') return `Closed from ${entry.closes}`
  // Short enough for a month-grid cell; the legend says it's unavailable time.
  return `Open ${entry.opens}–${entry.closes} only`
}
