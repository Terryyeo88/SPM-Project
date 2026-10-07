<script setup>
// View Venue Availability Calendar (Nawaz, Sprint 2, IS-11).
//
// "Available" is never an entry fetched from the backend -- it's just
// the absence of one over a period (see calendar_service.py's own
// docstring) -- so a day with no entries below simply renders empty.
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { apiGet } from '../../lib/api'
import AppNavBar from '../../components/AppNavBar.vue'

const route = useRoute()
const venueId = route.params.venueId

const view = ref('month') // 'month' | 'week' | 'day'
const anchor = ref(startOfDay(new Date()))

const venue = ref(null)
const entries = ref([])
const loading = ref(true)
const error = ref('')

function startOfDay(d) {
  const copy = new Date(d)
  copy.setHours(0, 0, 0, 0)
  return copy
}
function toISODate(d) {
  return d.toISOString().slice(0, 10)
}
function addDays(d, n) {
  const copy = new Date(d)
  copy.setDate(copy.getDate() + n)
  return copy
}

// [start, end) for the currently selected view, anchored on `anchor`.
const range = computed(() => {
  if (view.value === 'day') {
    return { start: anchor.value, end: addDays(anchor.value, 1) }
  }
  if (view.value === 'week') {
    const dow = anchor.value.getDay() // 0 = Sunday
    const start = addDays(anchor.value, -dow)
    return { start, end: addDays(start, 7) }
  }
  // month: first of month to first of next month
  const start = new Date(anchor.value.getFullYear(), anchor.value.getMonth(), 1)
  const end = new Date(anchor.value.getFullYear(), anchor.value.getMonth() + 1, 1)
  return { start, end }
})

const rangeLabel = computed(() => {
  const { start, end } = range.value
  if (view.value === 'month') {
    return start.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
  }
  const lastDay = addDays(end, -1)
  return `${start.toLocaleDateString()} – ${lastDay.toLocaleDateString()}`
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { start, end } = range.value
    // Backend range is inclusive of `end`'s whole day (see
    // calendar_service.get_venue_calendar) -- pass the last included
    // day, not the exclusive day-after boundary used internally above.
    const data = await apiGet(`/venues/${venueId}/calendar?start=${toISODate(start)}&end=${toISODate(addDays(end, -1))}`)
    venue.value = data.venue
    entries.value = data.entries
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    loading.value = false
  }
}

watch([view, anchor], load)
onMounted(load)

function step(delta) {
  if (view.value === 'day') anchor.value = addDays(anchor.value, delta)
  else if (view.value === 'week') anchor.value = addDays(anchor.value, delta * 7)
  else anchor.value = new Date(anchor.value.getFullYear(), anchor.value.getMonth() + delta, 1)
}
function goToday() {
  anchor.value = startOfDay(new Date())
}

const STATE_LABELS = {
  tentatively_held: 'Tentatively held',
  confirmed: 'Confirmed',
  blocked: 'Blocked',
}
const REASON_LABELS = {
  maintenance: 'Maintenance',
  renovation: 'Renovation',
  safety_issue: 'Safety issue',
  internal_activity: 'Internal activity',
  other: 'Other',
}

function entryLabel(entry) {
  if (entry.type === 'block') return REASON_LABELS[entry.reason] || 'Blocked'
  return entry.event_name || 'Booked'
}
function timeLabel(iso) {
  return new Date(iso).toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

// -- month grid: one cell per day, with blanks padding to a full week --
const monthCells = computed(() => {
  if (view.value !== 'month') return []
  const { start, end } = range.value
  const blanksBefore = start.getDay()
  const daysInMonth = Math.round((end - start) / 86400000)
  const cellsByDay = new Map()
  for (let i = 0; i < daysInMonth; i++) cellsByDay.set(i + 1, [])

  for (const entry of entries.value) {
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
})

// -- day/week view: a flat, time-ordered list --
const listEntries = computed(() => {
  if (view.value === 'month') return []
  return [...entries.value].sort((a, b) => a.start.localeCompare(b.start))
})
</script>

<template>
  <div class="page">
    <AppNavBar />
    <main class="content">
      <div class="container">
        <router-link :to="`/venues/${venueId}`" class="back-link">&larr; Back to venue</router-link>

        <div class="header-row">
          <h1 class="title">{{ venue ? `${venue.name} — Availability` : 'Venue Availability' }}</h1>
          <div class="view-tabs" role="group" aria-label="Calendar view">
            <button
              v-for="v in ['day', 'week', 'month']"
              :key="v"
              type="button"
              class="tab"
              :class="{ active: view === v }"
              @click="view = v"
            >
              {{ v }}
            </button>
          </div>
        </div>

        <div class="nav-row">
          <button type="button" class="nav-btn" @click="step(-1)" aria-label="Previous">‹</button>
          <span class="range-label">{{ rangeLabel }}</span>
          <button type="button" class="nav-btn" @click="step(1)" aria-label="Next">›</button>
          <button type="button" class="today-btn" @click="goToday">Today</button>
        </div>

        <p v-if="loading" class="message">Loading availability...</p>
        <p v-else-if="error" class="message error" role="alert">{{ error }}</p>

        <template v-else>
          <p v-if="venue?.operating_hours_start" class="hours-note">
            Operating hours: {{ venue.operating_hours_start }}–{{ venue.operating_hours_end }} daily. Periods outside
            these hours are unavailable.
          </p>

          <div v-if="view === 'month'" class="month-grid">
            <div v-for="d in ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']" :key="d" class="day-header">{{ d }}</div>
            <div v-for="(cell, i) in monthCells" :key="i" class="day-cell" :class="{ blank: cell.blank }">
              <template v-if="!cell.blank">
                <span class="day-number">{{ cell.day }}</span>
                <span v-for="(entry, j) in cell.entries" :key="j" class="entry-pill" :class="`state-${entry.state}`">
                  {{ entryLabel(entry) }}
                </span>
              </template>
            </div>
          </div>

          <div v-else class="list">
            <p v-if="listEntries.length === 0" class="message">No bookings or blocked periods in this range.</p>
            <div v-for="(entry, i) in listEntries" :key="i" class="list-row">
              <span class="entry-pill" :class="`state-${entry.state}`">{{ STATE_LABELS[entry.state] }}</span>
              <span class="list-main">{{ entryLabel(entry) }}</span>
              <span class="list-time">{{ timeLabel(entry.start) }} – {{ timeLabel(entry.end) }}</span>
            </div>
          </div>

          <div class="legend">
            <span class="legend-item"><span class="dot state-tentatively_held"></span>Tentatively held</span>
            <span class="legend-item"><span class="dot state-confirmed"></span>Confirmed</span>
            <span class="legend-item"><span class="dot state-blocked"></span>Blocked</span>
          </div>
        </template>
      </div>
    </main>
  </div>
</template>

<style scoped>
.page { min-height: 100vh; display: flex; flex-direction: column; background: #eeeeee; }
.content { flex: 1 1 auto; padding: 32px 16px; display: flex; justify-content: center; }
.container { width: 100%; max-width: 880px; display: flex; flex-direction: column; gap: 16px; }
.back-link { align-self: flex-start; font-size: 13px; color: #666666; text-decoration: underline; }
.header-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.title { margin: 0; font-size: 20px; font-weight: 700; color: #1f1f1f; }
.view-tabs { display: flex; gap: 6px; }
.tab {
  border: 1px solid #b0b0b0; background: #ffffff; color: #555555; font-size: 12px; font-weight: 600;
  padding: 6px 14px; border-radius: 16px; cursor: pointer; text-transform: capitalize;
}
.tab.active { border-color: #444444; background: #444444; color: #ffffff; }
.nav-row { display: flex; align-items: center; gap: 12px; }
.nav-btn, .today-btn {
  height: 30px; border: 1px solid #d8d8d8; border-radius: 4px; background: #ffffff; color: #555555; cursor: pointer;
  font-size: 13px;
}
.nav-btn { width: 30px; }
.today-btn { padding: 0 12px; margin-left: auto; font-weight: 600; }
.range-label { font-size: 14px; font-weight: 700; color: #222222; }
.hours-note { margin: 0; font-size: 12px; color: #8a8a8a; }
.message { margin: 0; padding: 16px 0; font-size: 14px; color: #8a8a8a; }
.error { color: #b42318; }

.month-grid {
  display: grid; grid-template-columns: repeat(7, 1fr); gap: 1px; background: #e6e6e6; border: 1px solid #e6e6e6;
  border-radius: 4px; overflow: hidden;
}
.day-header { background: #f7f7f7; padding: 6px 8px; font-size: 10px; font-weight: 700; color: #9a9a9a; text-align: center; }
.day-cell { background: #ffffff; min-height: 62px; padding: 6px 8px; box-sizing: border-box; display: flex; flex-direction: column; gap: 3px; }
.day-cell.blank { background: #f9f9f9; }
.day-number { font-size: 11px; color: #555555; }

.entry-pill {
  font-size: 9px; font-weight: 600; border-radius: 6px; padding: 1px 4px; display: inline-block; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis;
}
.state-tentatively_held { color: #1f5fae; background: #e4eefb; }
.state-confirmed { color: #2f6b3f; background: #eaf5ec; }
.state-blocked { color: #a33f3f; background: #f5e6e6; }

.list { background: #ffffff; border: 1px dashed #9a9a9a; border-radius: 6px; padding: 4px 18px; box-sizing: border-box; }
.list-row { display: flex; align-items: center; gap: 12px; padding: 12px 0; border-bottom: 1px dashed #e2e2e2; font-size: 13px; }
.list-row:last-child { border-bottom: none; }
.list-main { flex: 1 1 auto; color: #2a2a2a; font-weight: 600; }
.list-time { color: #8a8a8a; }

.legend { display: flex; align-items: center; gap: 16px; font-size: 11px; color: #8a8a8a; }
.legend-item { display: flex; align-items: center; gap: 4px; }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.dot.state-tentatively_held { background: #1f5fae; }
.dot.state-confirmed { background: #2f6b3f; }
.dot.state-blocked { background: #a33f3f; }
</style>
