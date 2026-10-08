<script setup>
/**
 * One equipment request plus its availability check -- Check Equipment
 * Availability (Nawaz, Sprint 2, IS-18), the story's main screen.
 *
 *   AC1  the request and its required date/time are shown at the top
 *   AC2  per item: requested quantity vs how many units are available
 *   AC3  items where available < requested are flagged
 *   AC4  "available" already has other events' reservations for the same
 *        period subtracted (done by the backend; the "held by" list shows
 *        which units and which events, so the number can be checked)
 *   AC5  the request is a stored row, so it is viewable again later
 *
 * Read-only: accepting or rejecting a request (and so reserving stock) is
 * the separate "Accept an equipment request" story, so there are no
 * decision buttons here. The check is fetched fresh on every load rather
 * than stored, so reopening the request later reflects reservations made
 * in the meantime.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { apiGet } from '../../lib/api'
import AppNavBar from '../../components/AppNavBar.vue'
import { describeAvailability, formatPeriod, summariseCheck } from '../../lib/equipment'
import { statusLabel } from '../../lib/coordinatorDashboard'

const route = useRoute()
const request = ref(null)
const check = ref(null)
const loading = ref(true)
const error = ref('')

const summary = computed(() => summariseCheck(check.value))
const techRequirements = computed(() => {
  const byType = new Map((request.value?.items ?? []).map((item) => [item.equipment_type_id, item]))
  return byType
})
const lines = computed(() =>
  (check.value?.items ?? []).map((item) => ({
    ...item,
    ...describeAvailability(item),
    technical_requirements: techRequirements.value.get(item.equipment_type_id)?.technical_requirements ?? null,
  })),
)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const id = route.params.requestId
    const [loadedRequest, loadedCheck] = await Promise.all([
      apiGet(`/equipment/requests/${id}`),
      apiGet(`/equipment/requests/${id}/availability`),
    ])
    request.value = loadedRequest
    check.value = loadedCheck
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
        <router-link :to="{ name: 'equipment-requests' }" class="back-link">&larr; Back to equipment requests</router-link>

        <p v-if="loading" class="message">Loading availability...</p>
        <p v-else-if="error" class="message error" role="alert">Couldn't load this request: {{ error }}</p>

        <template v-else>
          <div class="heading">
            <h1 class="title">{{ request.event_name ?? 'Untitled event' }}</h1>
            <span class="status" :class="`status-${request.status}`">{{ statusLabel(request.status) }}</span>
          </div>

          <section class="card" aria-labelledby="needed-heading">
            <h2 id="needed-heading" class="card-title">Required date and time</h2>
            <p class="period">{{ formatPeriod(request.needed_start, request.needed_end) }}</p>
            <p class="hint">Times shown in Singapore time.</p>
          </section>

          <div class="banner" :class="summary.sufficient ? 'banner-ok' : 'banner-warn'" role="status">
            {{ summary.message }}
          </div>

          <section class="card" aria-labelledby="items-heading">
            <h2 id="items-heading" class="card-title">Equipment availability</h2>
            <p v-if="lines.length === 0" class="message">This request has no items.</p>

            <div v-for="line in lines" :key="line.equipment_type_id" class="line" :class="`line-${line.state}`">
              <div class="line-head">
                <span class="line-type">{{ line.type }}</span>
                <span class="flag" :class="`flag-${line.state}`">
                  {{ line.state === 'insufficient' ? '⚠ ' : '✓ ' }}{{ line.label }}
                </span>
              </div>
              <p class="line-numbers">
                Requested <strong>{{ line.requested }}</strong> &middot; available <strong>{{ line.available }}</strong>
              </p>
              <p class="line-detail">{{ line.detail }}</p>
              <p v-if="line.technical_requirements" class="line-notes">
                Technical requirements: {{ line.technical_requirements }}
              </p>
              <p v-if="line.available_units.length" class="line-units">
                Free units: {{ line.available_units.join(', ') }}
              </p>
              <ul v-if="line.conflicts.length" class="conflicts" :aria-label="`${line.type} units held for other events`">
                <li v-for="conflict in line.conflicts" :key="`${conflict.asset_tag}-${conflict.reserved_start}`">
                  <strong>{{ conflict.asset_tag }}</strong> held for
                  {{ conflict.event_name ?? 'another event' }},
                  {{ formatPeriod(conflict.reserved_start, conflict.reserved_end) }}
                </li>
              </ul>
            </div>
          </section>

          <p class="hint">
            This screen only checks availability. Accepting or rejecting the request is not part of it yet.
          </p>
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
.hint { margin: 0; font-size: 12px; color: #8a8a8a; }

.card { background: #ffffff; border: 1px dashed #9a9a9a; border-radius: 6px; padding: 16px 18px; box-sizing: border-box; }
.card-title { margin: 0 0 8px; font-size: 14px; font-weight: 700; color: #1f1f1f; }
.period { margin: 0 0 4px; font-size: 15px; font-weight: 600; color: #2a2a2a; }

.banner { border-radius: 6px; padding: 12px 16px; font-size: 14px; font-weight: 600; }
.banner-ok { background: #eaf5ec; color: #2f6b3f; }
.banner-warn { background: #fdf6ec; color: #8a5a12; }

.line { padding: 14px 0; border-bottom: 1px dashed #e2e2e2; }
.line:last-child { border-bottom: none; padding-bottom: 0; }
.line-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.line-type { font-size: 14px; font-weight: 700; color: #1f1f1f; text-transform: capitalize; }
.flag { font-size: 11px; font-weight: 700; border-radius: 10px; padding: 3px 10px; white-space: nowrap; }
.flag-sufficient { background: #eaf5ec; color: #2f6b3f; }
.flag-insufficient { background: #fdf6ec; color: #8a5a12; }
.line-numbers { margin: 6px 0 0; font-size: 13px; color: #2a2a2a; }
.line-detail, .line-units, .line-notes { margin: 4px 0 0; font-size: 12px; color: #6a6a6a; }
.conflicts { margin: 8px 0 0; padding-left: 18px; font-size: 12px; color: #6a6a6a; }
.conflicts li { margin: 2px 0; }

.status { font-size: 11px; font-weight: 600; color: #6a6a6a; background: #f0f0f0; border-radius: 10px; padding: 3px 10px; white-space: nowrap; }
.status-pending { color: #8a6d00; background: #fff4c2; }
.status-confirmed { color: #0f6e6a; background: #ddf3f1; }
.status-rejected { color: #b42318; background: #fde8e6; }
</style>
