<script setup>
// View Equipment Availability Calendar (IS-47) -- one unit's profile and
// its reservation calendar, the equipment twin of VenueCalendarView.vue.
//
// The grid is components/AvailabilityCalendar.vue and the date math is
// lib/calendar.js, shared with the venue calendar; this view owns the
// equipment-specific parts: the fetch, the state colours, the entry labels
// and the profile block. Month view only (AC3), and a reservation is marked
// on every day it covers (AC5, `span-days`).
//
// Only "reserved" is ever an entry: pending requests have no unit
// allocated yet, and maintenance has no dated periods -- the unit's current
// status is the pill in the heading instead (see docs/open-questions.md).
import { onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { apiGet } from '../../lib/api'
import { rangeQuery, useCalendarRange } from '../../lib/calendar'
import { unitStatusLabel } from '../../lib/equipment'
import AppNavBar from '../../components/AppNavBar.vue'
import AvailabilityCalendar from '../../components/AvailabilityCalendar.vue'

const route = useRoute()
const equipmentId = route.params.equipmentId

const { range, label: rangeLabel, step, goToday } = useCalendarRange('month')

const unit = ref(null)
const entries = ref([])
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    const data = await apiGet(`/equipment/${equipmentId}/calendar?${rangeQuery(range.value)}`)
    unit.value = data.equipment
    entries.value = data.entries
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    loading.value = false
  }
}

watch(range, load)
onMounted(load)

// The venue calendar's "confirmed" colours: a reservation is a confirmed
// allocation of this unit.
const STATES = {
  reserved: { label: 'Reserved', color: 'var(--cs-available)', background: 'var(--cs-available-tint)' },
}

function entryLabel(entry) {
  return entry.event_name || 'Reserved'
}
</script>

<template>
  <div class="page">
    <AppNavBar />
    <main class="content">
      <div class="container">
        <router-link :to="{ name: 'equipment' }" class="back-link">&larr; Back to equipment</router-link>

        <p v-if="loading && !unit" class="message">Loading equipment calendar...</p>
        <p v-else-if="error" class="message error" role="alert">Couldn't load this equipment: {{ error }}</p>

        <template v-else>
          <div class="heading">
            <div>
              <h1 class="title">{{ unit.asset_tag }}</h1>
              <p class="subtitle">{{ unit.type }}</p>
            </div>
            <span class="status cs-pill" :class="`status-${unit.status} cs-status-${unit.status}`">{{ unitStatusLabel(unit.status) }}</span>
          </div>

          <section class="card" aria-labelledby="profile-heading">
            <h2 id="profile-heading" class="card-title">Equipment Profile</h2>
            <dl class="details">
              <dt>Asset tag</dt>
              <dd>{{ unit.asset_tag }}</dd>
              <dt>Type</dt>
              <dd class="capitalize">{{ unit.type }}</dd>
              <dt>Notes</dt>
              <dd>{{ unit.notes || 'None' }}</dd>
            </dl>
          </section>

          <section class="card" aria-labelledby="calendar-heading">
            <h2 id="calendar-heading" class="card-title">Reservation Calendar</h2>
            <div class="nav-row">
              <button type="button" class="nav-btn" @click="step(-1)" aria-label="Previous month">‹</button>
              <span class="range-label">{{ rangeLabel }}</span>
              <button type="button" class="nav-btn" @click="step(1)" aria-label="Next month">›</button>
              <button type="button" class="today-btn" @click="goToday">Today</button>
            </div>
            <AvailabilityCalendar
              view="month"
              :range="range"
              :entries="entries"
              :states="STATES"
              :entry-label="entryLabel"
              span-days
            />
          </section>
        </template>
      </div>
    </main>
  </div>
</template>

<style scoped>
.page { min-height: 100vh; display: flex; flex-direction: column; }
.content { flex: 1 1 auto; padding: var(--cs-space-6) var(--cs-space-4) var(--cs-space-8); display: flex; justify-content: center; }
.container { width: 100%; max-width: 880px; display: flex; flex-direction: column; gap: var(--cs-space-4); }
.back-link { align-self: flex-start; font-size: var(--cs-text-sm); color: var(--cs-signal); text-decoration: none; }
.heading { display: flex; align-items: center; justify-content: space-between; gap: var(--cs-space-3); }
.title { margin: 0; font-size: var(--cs-text-xl); font-family: var(--cs-font-display); color: var(--cs-ink); }
.subtitle { margin: 2px 0 0; font-size: var(--cs-text-sm); color: var(--cs-ink-soft); text-transform: capitalize; }
.message { margin: 0; padding: var(--cs-space-2) 0; font-size: var(--cs-text-base); color: var(--cs-ink-soft); }
.error { color: var(--cs-occupied); }
.capitalize { text-transform: capitalize; }

.card {
  background: var(--cs-surface); border: 1px solid var(--cs-line); border-radius: var(--cs-radius-md); padding: var(--cs-space-4) var(--cs-space-5); box-sizing: border-box;
  display: flex; flex-direction: column; gap: var(--cs-space-3);
}
.card-title { margin: 0; font-size: var(--cs-text-sm); font-weight: 700; color: var(--cs-ink); }
.details { display: grid; grid-template-columns: 90px 1fr; gap: 6px var(--cs-space-3); margin: 0; font-size: var(--cs-text-sm); }
.details dt { color: var(--cs-ink-soft); }
.details dd { margin: 0; color: var(--cs-ink); }

.nav-row { display: flex; align-items: center; gap: var(--cs-space-3); }
.nav-btn, .today-btn {
  height: 30px; border: 1px solid var(--cs-line-strong); border-radius: var(--cs-radius-sm); background: var(--cs-surface); color: var(--cs-ink-soft); cursor: pointer;
  font-size: var(--cs-text-sm);
}
.nav-btn { width: 30px; }
.today-btn { padding: 0 var(--cs-space-3); margin-left: auto; font-weight: 600; }
.range-label { font-size: var(--cs-text-base); font-weight: 700; color: var(--cs-ink); }
</style>
