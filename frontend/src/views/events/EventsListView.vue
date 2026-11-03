<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { apiGet } from '../../lib/api'
import { useAuthStore } from '../../stores/auth'
import { ROUTE_ACCESS, hasAnyRole } from '../../lib/roles'
import { groupIntoRequests, timeValue } from '../../lib/eventSessions'
import AppNavBar from '../../components/AppNavBar.vue'

const events = ref([])
const loading = ref(true)
const error = ref('')
const statusFilter = ref('')

const STATUSES = [
  'draft',
  'submitted',
  'under_review',
  'approved',
  'planning',
  'safety_review',
  'confirmed',
  'completed',
  'cancelled',
  'rejected',
]

async function loadEvents() {
  loading.value = true
  error.value = ''
  try {
    const query = statusFilter.value ? `?status=${statusFilter.value}` : ''
    events.value = await apiGet(`/events${query}`)
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    loading.value = false
  }
}

function formatDate(value) {
  return value || 'Not set'
}

watch(statusFilter, loadEvents)
onMounted(loadEvents)

// --- Display-only additions below: none of these change what is fetched. ---

const auth = useAuthStore()

// Only show "New Event Request" to roles the router would actually let
// through to /create-event -- read from the same ROUTE_ACCESS table so
// the button can't drift from the route guard.
const createEventRoles = ROUTE_ACCESS.find((entry) => entry.routeName === 'create-event').roles
const canCreateEvent = computed(() => hasAnyRole(auth.roles, createEventRoles))

function statusLabel(status) {
  return status.replace(/_/g, ' ')
}

function dateRange(event) {
  const start = formatDate(event.preferred_start_date)
  const end = event.preferred_end_date
  return end && end !== event.preferred_start_date ? `${start} – ${end}` : start
}

// --- One box per event request (grouping: lib/eventSessions) ---------------

const requests = computed(() => groupIntoRequests(events.value))

// Client-side search over the already-loaded requests (by name).
const search = ref('')
const visibleRequests = computed(() => {
  const term = search.value.trim().toLowerCase()
  if (!term) return requests.value
  return requests.value.filter((request) => request.sessions.some(
    (session) => (session.name || '').toLowerCase().includes(term),
  ))
})

// The request's overall span: earliest session start to latest session end.
function requestDateRange(request) {
  const starts = request.sessions.map((s) => s.preferred_start_date).filter(Boolean).sort()
  const ends = request.sessions.map((s) => s.preferred_end_date || s.preferred_start_date).filter(Boolean).sort()
  if (!starts.length) return 'Not set'
  const first = starts[0]
  const last = ends[ends.length - 1]
  return last && last !== first ? `${first} – ${last}` : first
}

function sessionWhen(session) {
  const times = [timeValue(session.preferred_start_time), timeValue(session.preferred_end_time)]
    .filter(Boolean).join(' – ')
  return times ? `${dateRange(session)} · ${times}` : dateRange(session)
}

// One badge when every session is at the same stage, otherwise a count per
// status (e.g. "2 approved", "1 rejected") so nothing is hidden.
function statusSummary(request) {
  const counts = new Map()
  for (const session of request.sessions) counts.set(session.status, (counts.get(session.status) || 0) + 1)
  if (counts.size === 1) return [{ status: request.sessions[0].status, label: statusLabel(request.sessions[0].status) }]
  return [...counts.entries()].map(([status, count]) => ({ status, label: `${count} ${statusLabel(status)}` }))
}
</script>

<template>
  <div class="page">
    <AppNavBar />

    <main class="content">
      <div class="container">
        <div class="page-header">
          <h1 class="title">My Event Requests</h1>
          <router-link v-if="canCreateEvent" :to="{ name: 'create-event' }" class="new-request">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#ffffff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <line x1="12" y1="5" x2="12" y2="19"></line>
              <line x1="5" y1="12" x2="19" y2="12"></line>
            </svg>
            New Event Request
          </router-link>
        </div>

        <div class="search">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#9a9a9a" stroke-width="2" stroke-linecap="round" class="search-icon" aria-hidden="true">
            <circle cx="11" cy="11" r="7"></circle>
            <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
          </svg>
          <input
            v-model="search"
            type="text"
            class="search-input"
            placeholder="Search your event requests..."
            aria-label="Search event requests"
          />
        </div>

        <div class="tabs" role="group" aria-label="Filter by status">
          <button
            type="button"
            class="tab"
            :class="{ active: statusFilter === '' }"
            @click="statusFilter = ''"
          >
            All<template v-if="statusFilter === '' && !loading && !error"> ({{ requests.length }})</template>
          </button>
          <button
            v-for="status in STATUSES"
            :key="status"
            type="button"
            class="tab"
            :class="{ active: statusFilter === status }"
            @click="statusFilter = status"
          >
            {{ statusLabel(status) }}<template v-if="statusFilter === status && !loading && !error"> ({{ requests.length }})</template>
          </button>
        </div>

        <div v-if="loading || error || requests.length === 0 || visibleRequests.length === 0" class="list">
          <p v-if="loading" class="message">Loading event requests...</p>
          <p v-else-if="error" class="message error" role="alert">{{ error }}</p>
          <p v-else-if="requests.length === 0" class="message">
            No event requests to show{{ statusFilter ? ` with status "${statusFilter}"` : '' }}.
          </p>
          <p v-else class="message">
            No event requests match "{{ search }}".
          </p>
        </div>

        <ul v-else class="requests">
          <li v-for="request in visibleRequests" :key="request.key" class="request">
            <router-link :to="`/events/${request.sessions[0].id}`" class="row request-header">
              <div class="row-main">
                <span class="row-name">{{ request.name }}</span>
                <span class="row-meta">
                  {{ requestDateRange(request) }}
                  <template v-if="request.sessions.length > 1"> · {{ request.sessions.length }} sessions</template>
                  <template v-else-if="request.sessions[0].expected_attendance"> · {{ request.sessions[0].expected_attendance }} attendees</template>
                </span>
              </div>
              <span class="badges">
                <span v-for="badge in statusSummary(request)" :key="badge.status" class="status cs-pill" :class="`status-${badge.status} cs-status-${badge.status}`">
                  {{ badge.label }}
                </span>
              </span>
            </router-link>

            <ol v-if="request.sessions.length > 1" class="sessions" :aria-label="`Sessions of ${request.name}`">
              <li v-for="(session, index) in request.sessions" :key="session.id">
                <router-link :to="`/events/${session.id}`" class="row session-row">
                  <div class="row-main">
                    <span class="session-name">Session {{ index + 1 }}</span>
                    <span class="row-meta">
                      {{ sessionWhen(session) }}<template v-if="session.expected_attendance"> · {{ session.expected_attendance }} attendees</template>
                    </span>
                  </div>
                  <span class="status cs-pill" :class="`status-${session.status} cs-status-${session.status}`">{{ statusLabel(session.status) }}</span>
                </router-link>
              </li>
            </ol>
          </li>
        </ul>
      </div>
    </main>
  </div>
</template>

<style scoped>
.page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}
.content {
  flex: 1 1 auto;
  padding: var(--cs-space-6) var(--cs-space-4) var(--cs-space-8);
  display: flex;
  justify-content: center;
}
.container {
  width: 100%;
  max-width: 880px;
  display: flex;
  flex-direction: column;
  gap: var(--cs-space-5);
}
.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--cs-space-3);
  flex-wrap: wrap;
}
.title {
  margin: 0;
  font-size: var(--cs-text-xl);
  font-family: var(--cs-font-display);
  color: var(--cs-ink);
}
.new-request {
  height: 42px;
  border-radius: var(--cs-radius-sm);
  background: var(--cs-signal);
  color: #ffffff;
  font-size: var(--cs-text-sm);
  font-weight: 700;
  display: flex;
  align-items: center;
  gap: var(--cs-space-2);
  padding: 0 var(--cs-space-4);
  text-decoration: none;
  box-sizing: border-box;
}
.new-request:hover {
  background: var(--cs-signal-strong);
}
.search {
  position: relative;
}
.search-icon {
  position: absolute;
  left: 16px;
  top: 50%;
  transform: translateY(-50%);
}
.search-input {
  width: 100%;
  height: 46px;
  border: 1px solid var(--cs-line-strong);
  border-radius: var(--cs-radius-sm);
  background: var(--cs-surface);
  padding: 0 16px 0 44px;
  font-size: var(--cs-text-base);
  color: var(--cs-ink);
  box-sizing: border-box;
}
.search-input:focus-visible {
  outline: 2px solid var(--cs-signal);
  outline-offset: 1px;
  border-color: var(--cs-signal);
}
.tabs {
  display: flex;
  align-items: center;
  gap: var(--cs-space-2);
  flex-wrap: wrap;
}
.tab {
  border: 1px solid var(--cs-line);
  background: var(--cs-surface);
  color: var(--cs-ink-soft);
  font-size: var(--cs-text-sm);
  font-weight: 600;
  padding: 7px var(--cs-space-4);
  border-radius: var(--cs-radius-full);
  cursor: pointer;
  text-transform: capitalize;
}
.tab.active {
  border-color: var(--cs-ink);
  background: var(--cs-ink);
  color: #ffffff;
}
.list {
  background: var(--cs-surface);
  border: 1px solid var(--cs-line);
  border-radius: var(--cs-radius-md);
  padding: 4px 18px;
  box-sizing: border-box;
}
.requests {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--cs-space-3);
}
.request {
  background: var(--cs-surface);
  border: 1px solid var(--cs-line);
  border-radius: var(--cs-radius-md);
  padding: 4px 18px;
  box-sizing: border-box;
}
.badges {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: var(--cs-space-2);
}
.sessions {
  list-style: none;
  margin: 0 0 10px;
  padding: 0 0 0 14px;
  border-left: 2px solid var(--cs-line);
}
.session-row {
  padding: 10px 0;
}
.sessions li:last-child .session-row {
  border-bottom: none;
}
.session-name {
  font-size: var(--cs-text-sm);
  font-weight: 600;
  color: var(--cs-ink);
}
.session-row:hover .session-name {
  text-decoration: underline;
}
.message {
  margin: 0;
  padding: var(--cs-space-4) 0;
  font-size: var(--cs-text-base);
  color: var(--cs-ink-soft);
}
.error {
  color: var(--cs-occupied);
}
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--cs-space-3);
  padding: var(--cs-space-4) 0;
  border-bottom: 1px solid var(--cs-line);
  text-decoration: none;
  color: inherit;
  cursor: pointer;
}
.row:last-child {
  border-bottom: none;
}
.row:hover .row-name {
  text-decoration: underline;
}
.row-main {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.row-name {
  font-size: var(--cs-text-sm);
  font-weight: 600;
  color: var(--cs-ink);
}
.row-meta {
  font-size: var(--cs-text-xs);
  color: var(--cs-ink-soft);
}
</style>
