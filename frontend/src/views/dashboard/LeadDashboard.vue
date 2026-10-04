<script setup>
/**
 * Event Coordinator Lead dashboard -- Week 7 customer change #5. Same
 * shape as the coordinator's dashboard (search, then tabs):
 *
 *   Unassigned -- requests submitted and waiting for a coordinator. The
 *                 Lead picks one per request and assigns it
 *                 (POST /events/<id>/assign-coordinator), which moves every
 *                 session to under_review.
 *   Assigned   -- one collapsible section per coordinator with their active
 *                 requests, so the Lead sees every assignment (and who is
 *                 free). Each request can be reassigned
 *                 (POST /events/<id>/reassign-coordinator).
 *   Past       -- completed, cancelled and rejected requests.
 *
 * Rows are REQUESTS (all sessions together), not session rows -- see
 * lib/leadDashboard.js. Which request lands in which tab lives there too,
 * with its tests.
 *
 * Not built: notifying the coordinator when they're assigned or
 * reassigned (change #5 asks for it; no notification system exists yet
 * -- see docs/open-questions.md).
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiGet, apiPost } from '../../lib/api'
import { formatDateRange, statusLabel } from '../../lib/coordinatorDashboard'
import {
  LEAD_TABS,
  assignTargetId,
  filterRequests,
  groupByCoordinator,
  groupForLead,
  isLeadTab,
  reassignTargetId,
} from '../../lib/leadDashboard'

const route = useRoute()
const router = useRouter()

const events = ref([])
const coordinators = ref([])
const loading = ref(true)
const error = ref('')
const success = ref('')
const search = ref('')
// The active tab lives in the URL (?tab=assigned), like the coordinator
// dashboard, so Back from an event's details page returns to it.
const activeTab = ref(isLeadTab(route.query.tab) ? route.query.tab : 'unassigned')

// Per-request UI state, keyed by request key.
const picks = reactive({}) // chosen coordinator id in that row's dropdown
const rowErrors = reactive({})
const busyKey = ref(null)

const groups = computed(() => groupForLead(events.value))
const visible = computed(() => filterRequests(groups.value[activeTab.value], search.value))
// While searching, only coordinators with a matching request are shown.
const coordinatorSections = computed(() => {
  const sections = groupByCoordinator(visible.value, coordinators.value)
  return search.value.trim() ? sections.filter((section) => section.requests.length) : sections
})
const coordinatorNames = computed(() => Object.fromEntries(coordinators.value.map((c) => [c.id, c.name])))

function selectTab(key) {
  activeTab.value = key
  success.value = ''
  router.replace({ query: { ...route.query, tab: key } })
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [eventRows, coordinatorRows] = await Promise.all([apiGet('/events'), apiGet('/events/coordinators')])
    events.value = eventRows
    coordinators.value = coordinatorRows
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    loading.value = false
  }
}

function eventLink(request) {
  return { name: 'event-details', params: { eventId: request.sessions[0].id } }
}

function subtitle(request) {
  const parts = [formatDateRange(request.startDate, request.endDate)]
  if (request.sessions.length > 1) parts.push(`${request.sessions.length} sessions`)
  if (request.expectedAttendance) parts.push(`${request.expectedAttendance} expected`)
  return parts.join(' · ')
}

function requestStatus(request) {
  return request.statuses.length === 1 ? request.statuses[0] : null
}

// Reassign choices: everyone except the request's current coordinator.
function reassignChoices(request) {
  return coordinators.value.filter((c) => c.id !== request.coordinatorId)
}

async function act(request, path, body, message) {
  rowErrors[request.key] = ''
  success.value = ''
  busyKey.value = request.key
  try {
    await apiPost(path, body)
    delete picks[request.key]
    success.value = message
    await load()
  } catch (requestError) {
    rowErrors[request.key] = requestError.message
  } finally {
    busyKey.value = null
  }
}

function assign(request) {
  const coordinatorId = picks[request.key]
  if (!coordinatorId) {
    rowErrors[request.key] = 'Choose a coordinator first.'
    return
  }
  const name = coordinatorNames.value[coordinatorId]
  return act(
    request,
    `/events/${assignTargetId(request)}/assign-coordinator`,
    { coordinator_id: coordinatorId },
    `"${request.name}" assigned to ${name}. It's now under review in the Assigned tab.`,
  )
}

function reassign(request) {
  const coordinatorId = picks[request.key]
  if (!coordinatorId) {
    rowErrors[request.key] = 'Choose a coordinator first.'
    return
  }
  const name = coordinatorNames.value[coordinatorId]
  return act(
    request,
    `/events/${reassignTargetId(request)}/reassign-coordinator`,
    { new_coordinator_id: coordinatorId, reason: 'reassigned by lead' },
    `"${request.name}" reassigned to ${name}.`,
  )
}

const EMPTY_MESSAGES = {
  unassigned: 'No requests waiting for a coordinator.',
  assigned: 'No active assignments.',
  past: 'No past events.',
}

onMounted(load)
</script>

<template>
  <section class="lead-dashboard" aria-labelledby="lead-dashboard-title">
    <h2 id="lead-dashboard-title">Coordinator Assignments</h2>

    <p v-if="loading" class="muted">Loading event requests...</p>
    <p v-else-if="error" class="error" role="alert">Couldn't load event requests: {{ error }}</p>

    <template v-else>
      <div v-if="groups.unassigned.length" class="attention" role="status">
        <p class="attention-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
            stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <path d="M12 9v4" />
            <path d="M12 17h.01" />
          </svg>
          {{ groups.unassigned.length }} {{ groups.unassigned.length === 1 ? 'request is' : 'requests are' }}
          waiting for a coordinator
        </p>
      </div>

      <p v-if="success" class="success" role="status">{{ success }}</p>

      <div class="search">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
          stroke-linecap="round" aria-hidden="true">
          <circle cx="11" cy="11" r="7" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <label for="lead-search" class="visually-hidden">Search event requests</label>
        <input id="lead-search" v-model="search" type="search" placeholder="Search by event name..." />
      </div>

      <div class="tabs" role="group" aria-label="Filter by assignment">
        <button
          v-for="tab in LEAD_TABS"
          :key="tab.key"
          type="button"
          class="tab"
          :class="{ active: activeTab === tab.key }"
          :aria-pressed="activeTab === tab.key"
          @click="selectTab(tab.key)"
        >
          {{ tab.label }} ({{ groups[tab.key].length }})
        </button>
      </div>

      <!-- Unassigned: pick a coordinator per request and assign. -->
      <div v-if="activeTab === 'unassigned'" class="list">
        <p v-if="visible.length === 0" class="muted empty">
          {{ search.trim() ? `No requests match "${search.trim()}".` : EMPTY_MESSAGES.unassigned }}
        </p>
        <div v-for="request in visible" :key="request.key" class="row">
          <router-link :to="eventLink(request)" class="row-main">
            <span class="row-name">{{ request.name }}</span>
            <span class="muted small">{{ subtitle(request) }}</span>
          </router-link>
          <form class="row-action" @submit.prevent="assign(request)">
            <label :for="`assign-${request.key}`" class="visually-hidden">Coordinator for {{ request.name }}</label>
            <select
              :id="`assign-${request.key}`"
              :value="picks[request.key] ?? ''"
              :disabled="busyKey === request.key"
              @change="picks[request.key] = $event.target.value"
            >
              <option value="" disabled>Choose coordinator</option>
              <option v-for="c in coordinators" :key="c.id" :value="c.id">{{ c.name }}</option>
            </select>
            <button type="submit" class="btn primary" :disabled="busyKey === request.key">
              {{ busyKey === request.key ? 'Assigning...' : 'Assign' }}
            </button>
          </form>
          <p v-if="rowErrors[request.key]" class="row-error" role="alert">{{ rowErrors[request.key] }}</p>
        </div>
      </div>

      <!-- Assigned: one dropdown section per coordinator. -->
      <div v-else-if="activeTab === 'assigned'" class="coordinator-sections">
        <p v-if="search.trim() && visible.length === 0" class="muted">No requests match "{{ search.trim() }}".</p>
        <details
          v-for="section in coordinatorSections"
          :key="section.coordinator.id"
          class="coordinator"
          :open="section.requests.length > 0 && Boolean(search.trim())"
        >
          <summary>
            <span class="coordinator-name">{{ section.coordinator.name }}</span>
            <span class="count" :class="{ free: section.requests.length === 0 }">
              {{ section.requests.length }} active {{ section.requests.length === 1 ? 'request' : 'requests' }}
            </span>
          </summary>
          <p v-if="section.requests.length === 0" class="muted empty">Nothing assigned.</p>
          <div v-for="request in section.requests" :key="request.key" class="row">
            <router-link :to="eventLink(request)" class="row-main">
              <span class="row-name">{{ request.name }}</span>
              <span class="muted small">{{ subtitle(request) }}</span>
            </router-link>
            <span class="row-side">
              <span v-if="requestStatus(request)" class="status" :class="`status-${requestStatus(request)}`">
                {{ statusLabel(requestStatus(request)) }}
              </span>
              <span v-else class="status">Mixed</span>
            </span>
            <form class="row-action" @submit.prevent="reassign(request)">
              <label :for="`reassign-${request.key}`" class="visually-hidden">Reassign {{ request.name }} to</label>
              <select
                :id="`reassign-${request.key}`"
                :value="picks[request.key] ?? ''"
                :disabled="busyKey === request.key"
                @change="picks[request.key] = $event.target.value"
              >
                <option value="" disabled>Reassign to...</option>
                <option v-for="c in reassignChoices(request)" :key="c.id" :value="c.id">{{ c.name }}</option>
              </select>
              <button type="submit" class="btn neutral" :disabled="busyKey === request.key">
                {{ busyKey === request.key ? 'Reassigning...' : 'Reassign' }}
              </button>
            </form>
            <p v-if="rowErrors[request.key]" class="row-error" role="alert">{{ rowErrors[request.key] }}</p>
          </div>
        </details>
        <p v-if="!search.trim() && coordinatorSections.length === 0" class="muted">{{ EMPTY_MESSAGES.assigned }}</p>
      </div>

      <!-- Past: read-only. -->
      <div v-else class="list">
        <p v-if="visible.length === 0" class="muted empty">
          {{ search.trim() ? `No requests match "${search.trim()}".` : EMPTY_MESSAGES.past }}
        </p>
        <router-link v-for="request in visible" :key="request.key" :to="eventLink(request)" class="row link-row">
          <span class="row-main">
            <span class="row-name">{{ request.name }}</span>
            <span class="muted small">
              {{ subtitle(request) }} · {{ coordinatorNames[request.coordinatorId] || 'No coordinator' }}
            </span>
          </span>
          <span class="row-side">
            <span v-if="requestStatus(request)" class="status" :class="`status-${requestStatus(request)}`">
              {{ statusLabel(requestStatus(request)) }}
            </span>
            <span v-else class="status">Mixed</span>
          </span>
        </router-link>
      </div>
    </template>
  </section>
</template>

<style scoped>
.lead-dashboard { display: flex; flex-direction: column; gap: 20px; margin-top: 1.5rem; }
h2 { margin: 0; font-size: 20px; color: #1f1f1f; }
.muted { color: #6b6b6b; }
.small { font-size: 12px; }
.error, .row-error { color: #a33f3f; }
.row-error { flex-basis: 100%; margin: 0; font-size: 12px; }
.success { margin: 0; color: #2f6b3f; font-size: 13px; }

.attention {
  background: #fdf6ec; border: 1px solid #e3b877; border-radius: 6px; padding: 14px 18px;
}
.attention-title { display: flex; align-items: center; gap: 8px; margin: 0; font-size: 13px; font-weight: 700; color: #8a5a12; }

.search { position: relative; color: #8a8a8a; }
.search svg { position: absolute; left: 16px; top: 50%; transform: translateY(-50%); }
.search input {
  width: 100%; height: 46px; box-sizing: border-box; padding: 0 16px 0 44px;
  border: 1px solid #b0b0b0; border-radius: 8px; background: #fff; font: inherit; font-size: 14px;
}

.tabs { display: flex; flex-wrap: wrap; gap: 8px; }
.tab {
  min-height: 36px; padding: 7px 16px; border: 1px solid #d0d0d0; border-radius: 20px;
  background: #fff; color: #555; font: inherit; font-size: 13px; font-weight: 600; cursor: pointer;
}
.tab.active { background: #2568e8; border-color: #2568e8; color: #fff; }
.tab:focus-visible, .row-main:focus-visible, .link-row:focus-visible, summary:focus-visible {
  outline: 2px solid #2568e8; outline-offset: 2px;
}

.list { background: #fff; border: 1px solid #d0d0d0; border-radius: 6px; padding: 4px 18px; }
.empty { padding: 16px 0; margin: 0; }
.row {
  display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 12px;
  padding: 16px 0; border-bottom: 1px solid #e6e6e6;
}
.row:last-child { border-bottom: none; }
.link-row { color: inherit; text-decoration: none; }
.row-main { display: flex; flex-direction: column; gap: 3px; min-width: 0; flex: 1 1 220px; color: inherit; text-decoration: none; }
.row-main:hover .row-name, .link-row:hover .row-name { text-decoration: underline; }
.row-name { font-size: 14px; font-weight: 600; color: #2a2a2a; }
.row-side { display: flex; align-items: center; gap: 10px; flex: 0 0 auto; }
.row-action { display: flex; gap: 8px; flex: 0 0 auto; }
.row-action select {
  height: 34px; min-width: 170px; padding: 0 8px; border: 1px solid #b0b0b0; border-radius: 6px;
  background: #fff; font: inherit; font-size: 13px;
}

.btn {
  height: 34px; padding: 0 14px; border-radius: 6px; font: inherit; font-size: 13px; font-weight: 600; cursor: pointer;
}
.btn:disabled { opacity: 0.6; cursor: default; }
.btn.primary { background: #2568e8; border: 1px solid #2568e8; color: #fff; }
.btn.neutral { background: #fff; border: 1px solid #b0b0b0; color: #333; }

.coordinator-sections { display: flex; flex-direction: column; gap: 10px; }
.coordinator { background: #fff; border: 1px solid #d0d0d0; border-radius: 6px; padding: 0 18px; }
.coordinator[open] { padding-bottom: 4px; }
summary {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 14px 0; cursor: pointer; list-style: none;
}
summary::-webkit-details-marker { display: none; }
summary::before { content: '▸'; color: #8a8a8a; margin-right: 8px; }
.coordinator[open] summary::before { content: '▾'; }
.coordinator[open] summary { border-bottom: 1px solid #e6e6e6; }
.coordinator-name { flex: 1 1 auto; font-size: 14px; font-weight: 700; color: #1f1f1f; }
.count { font-size: 12px; font-weight: 600; color: #1f5fae; background: #e7f0fb; border-radius: 10px; padding: 3px 10px; }
.count.free { color: #2f6b3f; background: #eaf5ec; }

.status { font-size: 11px; font-weight: 600; border-radius: 10px; padding: 3px 10px; white-space: nowrap; background: #eee; color: #5a5a5a; }
.status-under_review { background: #f7efe1; color: #8a5a12; }
.status-approved, .status-planning { background: #e7f0fb; color: #1f5fae; }
.status-confirmed, .status-completed { background: #eaf5ec; color: #2f6b3f; }
.status-cancelled, .status-rejected { background: #f5e6e6; color: #a33f3f; }

.visually-hidden {
  position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap;
}

@media (max-width: 600px) {
  .row-action { flex: 1 1 100%; }
  .row-action select { flex: 1 1 auto; min-width: 0; }
}
</style>
