<script setup>
/**
 * Event Coordinator dashboard ("My Assigned Events"), laid out after the
 * Dashboard-Coordinator wireframe: attention callout, search, then the
 * Needs Review / In Planning / Confirmed / Past tabs. Which statuses land
 * in which tab lives in lib/coordinatorDashboard.js (and its tests).
 *
 * Same layout as the organiser's list (EventsListView): one card per event
 * request (sessions sharing a shared_event_id), with its sessions listed
 * inside it. Each tab groups its own sessions, so a request whose sessions
 * are at different stages appears under each of those tabs.
 *
 * Not in this pass (tracked separately):
 *   - Approve / reject / clarify actions inline in a row -- they live on
 *     the event details page (CoordinatorEventReview and its Conversation
 *     chat), which every row links to.
 *   - The wireframe's inline per-row Reassign picker -- coordinators no
 *     longer reassign at all (Week 9 clarification: only the Event
 *     Coordinator Lead does, from the Lead dashboard).
 *   - Client organisation / category in each row -- the events table has
 *     neither column yet, so rows show date and attendance instead.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiGet } from '../../lib/api'
import { useAuthStore } from '../../stores/auth'
import {
  DASHBOARD_TABS,
  filterBySearch,
  formatDateRange,
  groupEventsByTab,
  isDashboardTab,
  requestDateRange,
  requestStatusSummary,
  sessionsAwaitingReview,
  statusLabel,
} from '../../lib/coordinatorDashboard'
import { groupIntoRequests, timeValue } from '../../lib/eventSessions'

const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const events = ref([])
const loading = ref(true)
const error = ref('')
// The active tab lives in the URL (?tab=inPlanning) so that the event
// details page's Back link can return to the tab matching the event's
// status, and the browser's own Back button keeps the tab too.
const activeTab = ref(isDashboardTab(route.query.tab) ? route.query.tab : 'needsReview')

function selectTab(key) {
  activeTab.value = key
  router.replace({ query: { ...route.query, tab: key } })
}
const search = ref('')

const groups = computed(() => groupEventsByTab(events.value, auth.profile?.id))
// Each tab's sessions, as one card per request.
const requestsByTab = computed(() => Object.fromEntries(
  DASHBOARD_TABS.map((tab) => [tab.key, groupIntoRequests(groups.value[tab.key])]),
))
const visibleRequests = computed(() => groupIntoRequests(filterBySearch(groups.value[activeTab.value], search.value)))
const attentionRequests = computed(() => requestsByTab.value.needsReview)

async function loadEvents() {
  loading.value = true
  error.value = ''
  try {
    events.value = await apiGet('/events')
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    loading.value = false
  }
}

function eventLink(event) {
  return { name: 'event-details', params: { eventId: event.id } }
}

function requestSubtitle(request) {
  const parts = [requestDateRange(request)]
  if (request.sessions.length > 1) parts.push(`${request.sessions.length} sessions`)
  else if (request.sessions[0].expected_attendance) parts.push(`${request.sessions[0].expected_attendance} expected`)
  return parts.join(' · ')
}

function sessionSubtitle(session) {
  const parts = [formatDateRange(session.preferred_start_date, session.preferred_end_date)]
  const times = [timeValue(session.preferred_start_time), timeValue(session.preferred_end_time)].filter(Boolean).join(' – ')
  if (times) parts.push(times)
  if (session.expected_attendance) parts.push(`${session.expected_attendance} expected`)
  return parts.join(' · ')
}

// The card links to its first session waiting on review (if any), so the
// coordinator lands on what needs them; otherwise to its first session.
function requestLink(request) {
  return eventLink(request.sessions.find((s) => s.status === 'under_review') || request.sessions[0])
}

function awaitingText(request) {
  const waiting = sessionsAwaitingReview(request)
  if (!waiting) return ''
  if (request.sessions.length === 1) return 'Awaiting your review'
  return `${waiting} ${waiting === 1 ? 'session' : 'sessions'} awaiting your review`
}

const EMPTY_MESSAGES = {
  needsReview: 'Nothing waiting for your review.',
  inPlanning: 'No approved events in planning.',
  confirmed: 'No confirmed events yet.',
  past: 'No past events.',
}

onMounted(loadEvents)
</script>

<template>
  <section class="coordinator-dashboard" aria-labelledby="coordinator-dashboard-title">
    <h2 id="coordinator-dashboard-title">My Assigned Events</h2>

    <p v-if="loading" class="muted">Loading your events...</p>
    <p v-else-if="error" class="error" role="alert">Couldn't load your events: {{ error }}</p>

    <template v-else>
      <div v-if="attentionRequests.length" class="attention" role="status">
        <p class="attention-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
            stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <path d="M12 9v4" />
            <path d="M12 17h.01" />
          </svg>
          {{ attentionRequests.length }} {{ attentionRequests.length === 1 ? 'event needs' : 'events need' }} your attention
        </p>
        <router-link v-for="request in attentionRequests" :key="request.key" :to="requestLink(request)" class="attention-row">
          <span class="attention-name">{{ request.name }}</span>
          <span>{{ awaitingText(request) }}</span>
        </router-link>
      </div>

      <div class="search">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
          stroke-linecap="round" aria-hidden="true">
          <circle cx="11" cy="11" r="7" />
          <line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <label for="coordinator-search" class="visually-hidden">Search assigned events</label>
        <input id="coordinator-search" v-model="search" type="search" placeholder="Search by event name..." />
      </div>

      <div class="tabs" role="group" aria-label="Filter by stage">
        <button
          v-for="tab in DASHBOARD_TABS"
          :key="tab.key"
          type="button"
          class="tab"
          :class="{ active: activeTab === tab.key }"
          :aria-pressed="activeTab === tab.key"
          @click="selectTab(tab.key)"
        >
          {{ tab.label }} ({{ requestsByTab[tab.key].length }})
        </button>
      </div>

      <div v-if="visibleRequests.length === 0" class="list">
        <p class="muted empty">
          {{ search.trim() ? `No events match "${search.trim()}".` : EMPTY_MESSAGES[activeTab] }}
        </p>
      </div>

      <ul v-else class="requests">
        <li v-for="request in visibleRequests" :key="request.key" class="request">
          <router-link :to="requestLink(request)" class="row request-header">
            <span class="row-main">
              <span class="row-name">{{ request.name }}</span>
              <span class="muted small">{{ requestSubtitle(request) }}</span>
            </span>
            <span class="row-side">
              <span v-if="awaitingText(request)" class="attention-text">{{ awaitingText(request) }}</span>
              <span class="badges">
                <span v-for="badge in requestStatusSummary(request)" :key="badge.status" class="status cs-pill" :class="`status-${badge.status} cs-status-${badge.status}`">
                  {{ badge.label }}
                </span>
              </span>
            </span>
          </router-link>

          <ol v-if="request.sessions.length > 1" class="sessions" :aria-label="`Sessions of ${request.name}`">
            <li v-for="(session, index) in request.sessions" :key="session.id">
              <router-link :to="eventLink(session)" class="row session-row">
                <span class="row-main">
                  <span class="session-name">Session {{ index + 1 }}</span>
                  <span class="muted small">{{ sessionSubtitle(session) }}</span>
                </span>
                <span class="row-side">
                  <span v-if="session.status === 'under_review'" class="attention-text">Awaiting your review</span>
                  <span class="status cs-pill" :class="`status-${session.status} cs-status-${session.status}`">{{ statusLabel(session.status) }}</span>
                </span>
              </router-link>
            </li>
          </ol>
        </li>
      </ul>
    </template>
  </section>
</template>

<style scoped>
.coordinator-dashboard { display: flex; flex-direction: column; gap: var(--cs-space-5); margin-top: var(--cs-space-5); }
h2 { margin: 0; font-family: var(--cs-font-display); font-size: var(--cs-text-lg); color: var(--cs-ink); }
.muted { color: var(--cs-ink-soft); }
.small { font-size: var(--cs-text-xs); }
.error { color: var(--cs-occupied); }

.attention {
  display: flex; flex-direction: column; gap: var(--cs-space-2);
  background: var(--cs-pending-tint); border: 1px solid var(--cs-pending); border-radius: var(--cs-radius-md);
  padding: var(--cs-space-4) var(--cs-space-5);
}
.attention-title { display: flex; align-items: center; gap: var(--cs-space-2); margin: 0; font-size: var(--cs-text-sm); font-weight: 700; color: var(--cs-pending); }
.attention-row {
  display: flex; justify-content: space-between; gap: var(--cs-space-3);
  padding-left: var(--cs-space-6); font-size: var(--cs-text-sm); color: var(--cs-pending); text-decoration: none;
}
.attention-row:hover .attention-name { text-decoration: underline; }
.attention-name { font-weight: 600; color: var(--cs-ink); }

.search { position: relative; color: var(--cs-ink-soft); }
.search svg { position: absolute; left: var(--cs-space-4); top: 50%; transform: translateY(-50%); }
.search input {
  width: 100%; height: 46px; box-sizing: border-box; padding: 0 var(--cs-space-4) 0 44px;
  border: 1px solid var(--cs-line-strong); border-radius: var(--cs-radius-sm); background: var(--cs-surface);
  font: inherit; font-size: var(--cs-text-base); color: var(--cs-ink);
}
.search input:focus-visible { outline: 2px solid var(--cs-signal); outline-offset: 1px; border-color: var(--cs-signal); }

.tabs { display: flex; flex-wrap: wrap; gap: var(--cs-space-2); }
.tab {
  min-height: 36px; padding: 7px 16px; border: 1px solid var(--cs-line-strong); border-radius: var(--cs-radius-full);
  background: var(--cs-surface); color: var(--cs-ink-soft); font: inherit; font-size: var(--cs-text-sm); font-weight: 600; cursor: pointer;
}
.tab.active { background: var(--cs-ink); border-color: var(--cs-ink); color: var(--cs-paper); }

.list { background: var(--cs-surface); border: 1px solid var(--cs-line); border-radius: var(--cs-radius-md); padding: var(--cs-space-1) var(--cs-space-5); }
.empty { padding: var(--cs-space-4) 0; margin: 0; }
.row {
  display: flex; align-items: center; justify-content: space-between; gap: var(--cs-space-3);
  padding: var(--cs-space-4) 0; border-bottom: 1px solid var(--cs-line); color: inherit; text-decoration: none;
}
.row:last-child { border-bottom: none; }

/* One card per request, its sessions inside -- as on the organiser's list. */
.requests { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--cs-space-3); }
.request { background: var(--cs-surface); border: 1px solid var(--cs-line); border-radius: var(--cs-radius-md); padding: var(--cs-space-1) var(--cs-space-5); }
.request-header:only-child { border-bottom: none; }
.badges { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: var(--cs-space-2); }
.sessions { list-style: none; margin: 0 0 var(--cs-space-3); padding: 0 0 0 var(--cs-space-4); border-left: 2px solid var(--cs-line); }
.session-row { padding: var(--cs-space-3) 0; }
.sessions li:last-child .session-row { border-bottom: none; }
.session-name { font-size: var(--cs-text-sm); font-weight: 600; color: var(--cs-ink-soft); }
.session-row:hover .session-name { text-decoration: underline; }
.row:hover .row-name { text-decoration: underline; }
.row-main { display: flex; flex-direction: column; gap: var(--cs-space-1); min-width: 0; }
.row-name { font-size: var(--cs-text-base); font-weight: 600; color: var(--cs-ink); }
.row-side { display: flex; align-items: center; gap: var(--cs-space-3); flex: 0 0 auto; }
.attention-text { font-size: var(--cs-text-xs); font-weight: 600; color: var(--cs-pending); }

.visually-hidden {
  position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap;
}

@media (max-width: 600px) {
  .row { flex-direction: column; align-items: flex-start; }
  .attention-row { flex-direction: column; gap: var(--cs-space-1); }
}
</style>
