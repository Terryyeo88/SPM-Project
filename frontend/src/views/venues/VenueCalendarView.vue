<script setup>
// View Venue Availability Calendar (Nawaz, Sprint 2, IS-11).
//
// "Available" is never an entry fetched from the backend -- it's just
// the absence of one over a period (see calendar_service.py's own
// docstring) -- so a day with no entries below simply renders empty.
//
// The grid itself is components/AvailabilityCalendar.vue and the date
// math is lib/calendar.js, shared with the equipment calendar; this view
// owns the venue-specific parts: the fetch, the state colours and the
// entry labels.
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { apiGet } from '../../lib/api'
import { CALENDAR_VIEWS, rangeQuery, useCalendarRange } from '../../lib/calendar'
import AppNavBar from '../../components/AppNavBar.vue'
import AvailabilityCalendar from '../../components/AvailabilityCalendar.vue'

const route = useRoute()
const venueId = route.params.venueId

const { view, anchor, range, label: rangeLabel, step, goToday } = useCalendarRange('month')

const venue = ref(null)
const entries = ref([])
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    // Backend range is inclusive of `end`'s whole day (see
    // calendar_service.get_venue_calendar) -- rangeQuery passes the last
    // included day, not the exclusive day-after boundary of `range`.
    const data = await apiGet(`/venues/${venueId}/calendar?${rangeQuery(range.value)}`)
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

// In legend order. These are the calendar's own colours, unchanged from
// before the extraction -- see docs/open-questions.md on why they are not
// (yet) the event-status palette.
const STATES = {
  tentatively_held: { label: 'Tentatively held', color: '#1f5fae', background: '#e4eefb' },
  confirmed: { label: 'Confirmed', color: '#2f6b3f', background: '#eaf5ec' },
  blocked: { label: 'Blocked', color: '#a33f3f', background: '#f5e6e6' },
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
              v-for="v in CALENDAR_VIEWS"
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

          <AvailabilityCalendar
            :view="view"
            :range="range"
            :entries="entries"
            :states="STATES"
            :entry-label="entryLabel"
            empty-message="No bookings or blocked periods in this range."
          />
        </template>
      </div>
    </main>
  </div>
</template>

<style scoped>
.page { min-height: 100vh; display: flex; flex-direction: column; }
.content { flex: 1 1 auto; padding: var(--cs-space-6) var(--cs-space-4) var(--cs-space-8); display: flex; justify-content: center; }
.container { width: 100%; max-width: 880px; display: flex; flex-direction: column; gap: var(--cs-space-4); }
.back-link { align-self: flex-start; font-size: var(--cs-text-sm); color: var(--cs-ink-soft); text-decoration: underline; }
.header-row { display: flex; align-items: center; justify-content: space-between; gap: var(--cs-space-3); flex-wrap: wrap; }
.title { margin: 0; font-size: var(--cs-text-xl); font-family: var(--cs-font-display); color: var(--cs-ink); }
.view-tabs { display: flex; gap: var(--cs-space-2); }
.tab {
  border: 1px solid var(--cs-line); background: var(--cs-surface); color: var(--cs-ink-soft); font-size: var(--cs-text-xs); font-weight: 600;
  padding: 6px var(--cs-space-4); border-radius: var(--cs-radius-full); cursor: pointer; text-transform: capitalize;
}
.tab.active { border-color: var(--cs-ink); background: var(--cs-ink); color: #ffffff; }
.nav-row { display: flex; align-items: center; gap: var(--cs-space-3); }
.nav-btn, .today-btn {
  height: 30px; border: 1px solid var(--cs-line); border-radius: var(--cs-radius-sm); background: var(--cs-surface); color: var(--cs-ink-soft); cursor: pointer;
  font-size: var(--cs-text-sm);
}
.nav-btn { width: 30px; }
.today-btn { padding: 0 var(--cs-space-3); margin-left: auto; font-weight: 600; }
.range-label { font-size: var(--cs-text-base); font-weight: 700; color: var(--cs-ink); }
.hours-note { margin: 0; font-size: var(--cs-text-xs); color: var(--cs-ink-soft); }
.message { margin: 0; padding: var(--cs-space-4) 0; font-size: var(--cs-text-base); color: var(--cs-ink-soft); }
.error { color: var(--cs-occupied); }

</style>
