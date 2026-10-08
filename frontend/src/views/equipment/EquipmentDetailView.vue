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
            <span class="status" :class="`status-${unit.status}`">{{ unitStatusLabel(unit.status) }}</span>
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
        </template>
      </div>
    </main>
  </div>
</template>

<style scoped>
.page { min-height: 100vh; display: flex; flex-direction: column; background: #eeeeee; }
.content { flex: 1 1 auto; padding: 32px 16px; display: flex; justify-content: center; }
.container { width: 100%; max-width: 760px; display: flex; flex-direction: column; gap: 16px; }
.back-link { font-size: 13px; color: #1f5fae; text-decoration: none; }
.heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.title { margin: 0; font-size: 20px; font-weight: 700; color: #1f1f1f; }
.message { margin: 0; padding: 8px 0; font-size: 14px; color: #8a8a8a; }
.error { color: #b42318; }
.hint { margin: 10px 0 0; font-size: 12px; color: #8a8a8a; }
.capitalize { text-transform: capitalize; }

.card { background: #ffffff; border: 1px dashed #9a9a9a; border-radius: 6px; padding: 16px 18px; box-sizing: border-box; }
.card-title { margin: 0 0 10px; font-size: 14px; font-weight: 700; color: #1f1f1f; }
.details { display: grid; grid-template-columns: 90px 1fr; gap: 6px 12px; margin: 0; font-size: 13px; }
.details dt { color: #8a8a8a; }
.details dd { margin: 0; color: #2a2a2a; }

.occupancy { list-style: none; margin: 0; padding: 0; }
.occupancy-row {
  display: grid; grid-template-columns: 1fr auto; gap: 2px 12px; padding: 10px 0; border-bottom: 1px dashed #e2e2e2;
}
.occupancy-row:last-child { border-bottom: none; }
.occupancy-event { font-size: 14px; font-weight: 600; color: #2a2a2a; }
.occupancy-period { grid-column: 1; font-size: 12px; color: #6a6a6a; }
.occupancy-link { grid-column: 2; grid-row: 1 / span 2; align-self: center; font-size: 12px; color: #1f5fae; text-decoration: none; }

.status { font-size: 11px; font-weight: 600; border-radius: 10px; padding: 3px 10px; white-space: nowrap; }
.status-available { color: #0f6e6a; background: #ddf3f1; }
.status-maintenance { color: #8a6d00; background: #fff4c2; }
.status-retired { color: #6a6a6a; background: #f0f0f0; }
</style>
