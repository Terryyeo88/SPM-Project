<script setup>
/**
 * Event Coordinator dashboard ("My Assigned Events"), laid out after the
 * Dashboard-Coordinator wireframe: attention callout, search, then the
 * Needs Review / In Planning / Confirmed / Past tabs. Which statuses land
 * in which tab lives in lib/coordinatorDashboard.js (and its tests).
 *
 * Not in this pass (tracked separately):
 *   - Approve / reject / clarify actions -- Event Review and Approval.
 *     Rows link to the existing event details page for now.
 *   - The wireframe's inline per-row Reassign picker -- reassignment is
 *     still on its own page (/events/reassign).
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
  statusLabel,
} from '../../lib/coordinatorDashboard'

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
const visibleEvents = computed(() => filterBySearch(groups.value[activeTab.value], search.value))
const attentionEvents = computed(() => groups.value.needsReview)

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

function subtitle(event) {
  const parts = [formatDateRange(event.preferred_start_date, event.preferred_end_date)]
  if (event.expected_attendance) parts.push(`${event.expected_attendance} expected`)
  return parts.join(' · ')
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
      <div v-if="attentionEvents.length" class="attention" role="status">
        <p class="attention-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
            stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <path d="M12 9v4" />
            <path d="M12 17h.01" />
          </svg>
          {{ attentionEvents.length }} {{ attentionEvents.length === 1 ? 'event needs' : 'events need' }} your attention
        </p>
        <router-link v-for="event in attentionEvents" :key="event.id" :to="eventLink(event)" class="attention-row">
          <span class="attention-name">{{ event.name }}</span>
          <span>Awaiting your review</span>
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
          {{ tab.label }} ({{ groups[tab.key].length }})
        </button>
      </div>

      <div class="list">
        <p v-if="visibleEvents.length === 0" class="muted empty">
          {{ search.trim() ? `No events match "${search.trim()}".` : EMPTY_MESSAGES[activeTab] }}
        </p>
        <router-link v-for="event in visibleEvents" :key="event.id" :to="eventLink(event)" class="row">
          <span class="row-main">
            <span class="row-name">{{ event.name }}</span>
            <span class="muted small">{{ subtitle(event) }}</span>
          </span>
          <span class="row-side">
            <span v-if="event.status === 'under_review'" class="attention-text">Awaiting your review</span>
            <span class="status" :class="`status-${event.status}`">{{ statusLabel(event.status) }}</span>
          </span>
        </router-link>
      </div>
    </template>
  </section>
</template>

<style scoped>
.coordinator-dashboard { display: flex; flex-direction: column; gap: 20px; margin-top: 1.5rem; }
h2 { margin: 0; font-size: 20px; color: #1f1f1f; }
.muted { color: #6b6b6b; }
.small { font-size: 12px; }
.error { color: #a33f3f; }

.attention {
  display: flex; flex-direction: column; gap: 10px;
  background: #fdf6ec; border: 1px solid #e3b877; border-radius: 6px; padding: 14px 18px;
}
.attention-title { display: flex; align-items: center; gap: 8px; margin: 0; font-size: 13px; font-weight: 700; color: #8a5a12; }
.attention-row {
  display: flex; justify-content: space-between; gap: 12px;
  padding-left: 24px; font-size: 13px; color: #8a5a12; text-decoration: none;
}
.attention-row:hover .attention-name { text-decoration: underline; }
.attention-name { font-weight: 600; color: #3a2c14; }

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
.tab:focus-visible, .row:focus-visible, .attention-row:focus-visible { outline: 2px solid #2568e8; outline-offset: 2px; }

.list { background: #fff; border: 1px solid #d0d0d0; border-radius: 6px; padding: 4px 18px; }
.empty { padding: 16px 0; margin: 0; }
.row {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 16px 0; border-bottom: 1px solid #e6e6e6; color: inherit; text-decoration: none;
}
.row:last-child { border-bottom: none; }
.row:hover .row-name { text-decoration: underline; }
.row-main { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.row-name { font-size: 14px; font-weight: 600; color: #2a2a2a; }
.row-side { display: flex; align-items: center; gap: 10px; flex: 0 0 auto; }
.attention-text { font-size: 11px; font-weight: 600; color: #8a5a12; }

.status { font-size: 11px; font-weight: 600; border-radius: 10px; padding: 3px 10px; white-space: nowrap; background: #eee; color: #5a5a5a; }
.status-under_review { background: #f7efe1; color: #8a5a12; }
.status-approved, .status-planning { background: #e7f0fb; color: #1f5fae; }
.status-confirmed { background: #eaf5ec; color: #2f6b3f; }
.status-cancelled, .status-rejected { background: #f5e6e6; color: #a33f3f; }

.visually-hidden {
  position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap;
}

@media (max-width: 600px) {
  .row { flex-direction: column; align-items: flex-start; }
  .attention-row { flex-direction: column; gap: 2px; }
}
</style>
