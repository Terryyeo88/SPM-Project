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
import { rangeQuery, useCalendarRange, widenRange } from '../../lib/calendar'
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
    // A day wider than the month on each side: the query's dates are UTC
    // and the backend compares UTC times, so an exact month misses the last
    // local day after 08:00 in Singapore (see widenRange). The grid only
    // draws this month's days, placed by local time.
    const data = await apiGet(`/equipment/${equipmentId}/calendar?${rangeQuery(widenRange(range.value))}`)
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
  reserved: { label: 'Reserved', color: '#2f6b3f', background: '#eaf5ec' },
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
            <span class="status" :class="`status-${unit.status}`">{{ unitStatusLabel(unit.status) }}</span>
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
.page { min-height: 100vh; display: flex; flex-direction: column; background: #eeeeee; }
.content { flex: 1 1 auto; padding: 32px 16px; display: flex; justify-content: center; }
.container { width: 100%; max-width: 880px; display: flex; flex-direction: column; gap: 16px; }
.back-link { align-self: flex-start; font-size: 13px; color: #1f5fae; text-decoration: none; }
.heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.title { margin: 0; font-size: 20px; font-weight: 700; color: #1f1f1f; }
.subtitle { margin: 2px 0 0; font-size: 13px; color: #6a6a6a; text-transform: capitalize; }
.message { margin: 0; padding: 8px 0; font-size: 14px; color: #8a8a8a; }
.error { color: #b42318; }
.capitalize { text-transform: capitalize; }

.card {
  background: #ffffff; border: 1px dashed #9a9a9a; border-radius: 6px; padding: 16px 18px; box-sizing: border-box;
  display: flex; flex-direction: column; gap: 12px;
}
.card-title { margin: 0; font-size: 14px; font-weight: 700; color: #1f1f1f; }
.details { display: grid; grid-template-columns: 90px 1fr; gap: 6px 12px; margin: 0; font-size: 13px; }
.details dt { color: #8a8a8a; }
.details dd { margin: 0; color: #2a2a2a; }

.nav-row { display: flex; align-items: center; gap: 12px; }
.nav-btn, .today-btn {
  height: 30px; border: 1px solid #d8d8d8; border-radius: 4px; background: #ffffff; color: #555555; cursor: pointer;
  font-size: 13px;
}
.nav-btn { width: 30px; }
.today-btn { padding: 0 12px; margin-left: auto; font-weight: 600; }
.range-label { font-size: 14px; font-weight: 700; color: #222222; }

/* Same pill as EquipmentDetailView.vue. */
.status { font-size: 11px; font-weight: 600; border-radius: 10px; padding: 3px 10px; white-space: nowrap; }
.status-available { color: #0f6e6a; background: #ddf3f1; }
.status-maintenance { color: #8a6d00; background: #fff4c2; }
.status-retired { color: #6a6a6a; background: #f0f0f0; }
</style>
