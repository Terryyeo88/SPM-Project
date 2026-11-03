<script setup>
/**
 * One equipment unit's record -- Check Equipment Availability (Nawaz,
 * Sprint 2, IS-18), AC: "When viewing an equipment record, the Technical
 * Support Staff can view when the equipment is occupied along with the
 * event that it is reserved for and its reservation period."
 *
 * Occupancy comes from GET /equipment/<id> (equipment_reservations joined
 * to the owning request's event); only the event's id and name are
 * exposed, never the full event row. The event name is plain text rather
 * than a link: Technical Support Staff cannot open event details (see
 * lib/roles.js ROUTE_ACCESS). Each row links to the equipment REQUEST the
 * unit was reserved under instead, which they can open.
 */
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { apiGet } from '../../lib/api'
import AppNavBar from '../../components/AppNavBar.vue'
import { formatPeriod, unitStatusLabel } from '../../lib/equipment'

const route = useRoute()
const unit = ref(null)
const loading = ref(true)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    unit.value = await apiGet(`/equipment/${route.params.equipmentId}`)
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <AppNavBar />
    <main class="content">
      <div class="container">
        <router-link :to="{ name: 'equipment' }" class="back-link">&larr; Back to equipment</router-link>

        <p v-if="loading" class="message">Loading equipment record...</p>
        <p v-else-if="error" class="message error" role="alert">Couldn't load this equipment: {{ error }}</p>

        <template v-else>
          <div class="heading">
            <h1 class="title">{{ unit.asset_tag }}</h1>
            <span class="status cs-pill" :class="`status-${unit.status} cs-status-${unit.status}`">{{ unitStatusLabel(unit.status) }}</span>
          </div>

          <section class="card" aria-labelledby="details-heading">
            <h2 id="details-heading" class="card-title">Details</h2>
            <dl class="details">
              <dt>Type</dt>
              <dd class="capitalize">{{ unit.type }}</dd>
              <dt>Notes</dt>
              <dd>{{ unit.notes || 'None' }}</dd>
            </dl>
          </section>

          <section class="card" aria-labelledby="occupancy-heading">
            <h2 id="occupancy-heading" class="card-title">When this equipment is occupied</h2>
            <p v-if="unit.occupancy.length === 0" class="message">Not reserved for any event.</p>
            <ul v-else class="occupancy">
              <li v-for="entry in unit.occupancy" :key="entry.reservation_id" class="occupancy-row">
                <span class="occupancy-event">{{ entry.event_name ?? 'Unnamed event' }}</span>
                <span class="occupancy-period">{{ formatPeriod(entry.reserved_start, entry.reserved_end) }}</span>
                <router-link
                  v-if="entry.request_id"
                  :to="{ name: 'equipment-request-details', params: { requestId: entry.request_id } }"
                  class="occupancy-link"
                >
                  View request
                </router-link>
              </li>
            </ul>
            <p class="hint">Times shown in Singapore time.</p>
          </section>

          <router-link
            :to="{ name: 'equipment-calendar', params: { equipmentId: unit.id } }"
            class="calendar-link"
          >
            View reservation calendar &rarr;
          </router-link>
        </template>
      </div>
    </main>
  </div>
</template>

<style scoped>
.page { min-height: 100vh; display: flex; flex-direction: column; }
.content { flex: 1 1 auto; padding: var(--cs-space-6) var(--cs-space-4) var(--cs-space-8); display: flex; justify-content: center; }
.container { width: 100%; max-width: 760px; display: flex; flex-direction: column; gap: var(--cs-space-4); }
.back-link { font-size: var(--cs-text-sm); color: var(--cs-signal); text-decoration: none; }
.heading { display: flex; align-items: center; justify-content: space-between; gap: var(--cs-space-3); }
.title { margin: 0; font-size: var(--cs-text-xl); font-family: var(--cs-font-display); color: var(--cs-ink); }
.message { margin: 0; padding: var(--cs-space-2) 0; font-size: var(--cs-text-base); color: var(--cs-ink-soft); }
.error { color: var(--cs-occupied); }
.hint { margin: var(--cs-space-3) 0 0; font-size: var(--cs-text-xs); color: var(--cs-ink-soft); }
.capitalize { text-transform: capitalize; }

.card { background: var(--cs-surface); border: 1px solid var(--cs-line); border-radius: var(--cs-radius-md); padding: var(--cs-space-4) var(--cs-space-5); box-sizing: border-box; }
.card-title { margin: 0 0 var(--cs-space-3); font-size: var(--cs-text-sm); font-weight: 700; color: var(--cs-ink); }
.details { display: grid; grid-template-columns: 90px 1fr; gap: 6px var(--cs-space-3); margin: 0; font-size: var(--cs-text-sm); }
.details dt { color: var(--cs-ink-soft); }
.details dd { margin: 0; color: var(--cs-ink); }

.occupancy { list-style: none; margin: 0; padding: 0; }
.occupancy-row {
  display: grid; grid-template-columns: 1fr auto; gap: 2px var(--cs-space-3); padding: var(--cs-space-3) 0; border-bottom: 1px solid var(--cs-line);
}
.occupancy-row:last-child { border-bottom: none; }
.occupancy-event { font-size: var(--cs-text-base); font-weight: 600; color: var(--cs-ink); }
.occupancy-period { grid-column: 1; font-size: var(--cs-text-xs); color: var(--cs-ink-soft); }
.occupancy-link { grid-column: 2; grid-row: 1 / span 2; align-self: center; font-size: var(--cs-text-xs); color: var(--cs-signal); text-decoration: none; }

.calendar-link { align-self: flex-start; font-size: var(--cs-text-base); font-weight: 700; color: var(--cs-signal); text-decoration: none; }
.calendar-link:hover { text-decoration: underline; }
</style>
