// Date math for the availability calendars (venue today, equipment next),
// extracted unchanged from VenueCalendarView.vue (IS-11, Nawaz). Pure
// functions plus one composable, useCalendarRange, that holds the
// selected view and the day it is anchored on.
//
// Ranges are [start, end): `end` is the first day NOT shown. The backend
// takes an INCLUSIVE end day instead (app.shared.calendar), so
// rangeQuery() converts.
import { computed, ref } from 'vue'

export const CALENDAR_VIEWS = Object.freeze(['day', 'week', 'month'])
export const WEEKDAY_HEADERS = Object.freeze(['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'])

export function startOfDay(d) {
  const copy = new Date(d)
  copy.setHours(0, 0, 0, 0)
  return copy
}

export function toISODate(d) {
  return d.toISOString().slice(0, 10)
}

export function addDays(d, n) {
  const copy = new Date(d)
  copy.setDate(copy.getDate() + n)
  return copy
}

// [start, end) for `view`, anchored on `anchor`.
export function rangeFor(view, anchor) {
  if (view === 'day') {
    return { start: anchor, end: addDays(anchor, 1) }
  }
  if (view === 'week') {
    const dow = anchor.getDay() // 0 = Sunday
    const start = addDays(anchor, -dow)
    return { start, end: addDays(start, 7) }
  }
  // month: first of month to first of next month
  const start = new Date(anchor.getFullYear(), anchor.getMonth(), 1)
  const end = new Date(anchor.getFullYear(), anchor.getMonth() + 1, 1)
  return { start, end }
}

export function rangeLabel(view, range) {
  const { start, end } = range
  if (view === 'month') {
    return start.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
  }
  const lastDay = addDays(end, -1)
  return `${start.toLocaleDateString()} – ${lastDay.toLocaleDateString()}`
}

// The backend's start/end query values: the last INCLUDED day, not the
// exclusive day-after boundary used here.
export function rangeQuery(range) {
  return `start=${toISODate(range.start)}&end=${toISODate(addDays(range.end, -1))}`
}

export function stepAnchor(view, anchor, delta) {
  if (view === 'day') return addDays(anchor, delta)
  if (view === 'week') return addDays(anchor, delta * 7)
  return new Date(anchor.getFullYear(), anchor.getMonth() + delta, 1)
}

export function timeLabel(iso) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

// Month grid: one cell per day, with blanks padding the first week. An
// entry goes in the cell of the day it STARTS on.
export function monthCells(range, entries) {
  const { start, end } = range
  const blanksBefore = start.getDay()
  const daysInMonth = Math.round((end - start) / 86400000)
  const cellsByDay = new Map()
  for (let i = 0; i < daysInMonth; i++) cellsByDay.set(i + 1, [])

  for (const entry of entries) {
    const entryStart = new Date(entry.start)
    if (entryStart.getFullYear() === start.getFullYear() && entryStart.getMonth() === start.getMonth()) {
      const bucket = cellsByDay.get(entryStart.getDate())
      if (bucket) bucket.push(entry)
    }
  }

  const cells = []
  for (let i = 0; i < blanksBefore; i++) cells.push({ blank: true })
  for (let day = 1; day <= daysInMonth; day++) {
    cells.push({ blank: false, day, entries: cellsByDay.get(day) })
  }
  return cells
}

// Day/week view: a flat, time-ordered list.
export function sortedByStart(entries) {
  return [...entries].sort((a, b) => a.start.localeCompare(b.start))
}

// The selected view ('month' | 'week' | 'day'), the day it is anchored
// on, and the visible range derived from both.
export function useCalendarRange(initialView = 'month') {
  const view = ref(initialView)
  const anchor = ref(startOfDay(new Date()))
  const range = computed(() => rangeFor(view.value, anchor.value))
  const label = computed(() => rangeLabel(view.value, range.value))

  function step(delta) {
    anchor.value = stepAnchor(view.value, anchor.value, delta)
  }
  function goToday() {
    anchor.value = startOfDay(new Date())
  }

  return { view, anchor, range, label, step, goToday }
}
