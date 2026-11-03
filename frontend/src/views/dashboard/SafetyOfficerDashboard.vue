<script setup>
/**
 * Safety Officer dashboard (Week 7 change #6, Operational Feasibility Check):
 * the sessions coordinators have submitted for a safety check, in the same
 * layout as the coordinator's "My Assigned Events" -- attention callout,
 * search, tabs, one card per event request with its sessions inside.
 *
 *   Check Safety -- reviews still pending, oldest first.
 *   Checked      -- reviews decided (approved, rejected, changes requested),
 *                   most recent first, each with its outcome.
 *
 * Every Safety Officer sees every review (no assignment step). Each session
 * row opens that review (route `safety-review`), where the officer decides.
 * Which status lands in which tab lives in lib/safetyReviews.js (and its tests).
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiGet } from '../../lib/api'
import { formatDateRange, requestDateRange } from '../../lib/coordinatorDashboard'
import { groupIntoRequests, timeValue } from '../../lib/eventSessions'
import {
  SAFETY_TABS,
  filterReviews,
  groupReviewsByTab,
  isSafetyTab,
  reviewRows,
  reviewStatusLabel,
} from '../../lib/safetyReviews'

const route = useRoute()
const router = useRouter()

const reviews = ref([])
const loading = ref(true)
const error = ref('')
const search = ref('')
// In the URL (?tab=checked), so the review page's Back link and the
// browser's Back button return to the same tab.
const activeTab = ref(isSafetyTab(route.query.tab) ? route.query.tab : 'checkSafety')

function selectTab(key) {
  activeTab.value = key
  router.replace({ query: { ...route.query, tab: key } })
}

const groups = computed(() => groupReviewsByTab(reviews.value))
const requestsByTab = computed(() => Object.fromEntries(
  SAFETY_TABS.map((tab) => [tab.key, groupIntoRequests(reviewRows(groups.value[tab.key]))]),
))
const visibleRequests = computed(() => groupIntoRequests(reviewRows(filterReviews(groups.value[activeTab.value], search.value))))
const attentionRequests = computed(() => requestsByTab.value.checkSafety)

async function loadReviews() {
  loading.value = true
  error.value = ''
  try {
    reviews.value = await apiGet('/safety-reviews')
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    loading.value = false
  }
}

function reviewLink(row) {
  return { name: 'safety-review', params: { reviewId: row.reviewId } }
}

// The card opens its first session still awaiting a check, else its first.
function requestLink(request) {
  return reviewLink(request.sessions.find((s) => s.review.status === 'pending') || request.sessions[0])
}

function pendingCount(request) {
  return request.sessions.filter((s) => s.review.status === 'pending').length
}

function awaitingText(request) {
  const waiting = pendingCount(request)
  if (!waiting) return ''
  if (request.sessions.length === 1) return 'Awaiting your check'
  return `${waiting} ${waiting === 1 ? 'session' : 'sessions'} awaiting your check`
}

function requestSubtitle(request) {
  const parts = [requestDateRange(request)]
  if (request.sessions.length > 1) parts.push(`${request.sessions.length} sessions`)
  else if (request.sessions[0].expected_attendance) parts.push(`${request.sessions[0].expected_attendance} expected`)
  return parts.join(' · ')
}

function sessionSubtitle(row) {
  const parts = [formatDateRange(row.preferred_start_date, row.preferred_end_date)]
  const times = [timeValue(row.preferred_start_time), timeValue(row.preferred_end_time)].filter(Boolean).join(' – ')
  if (times) parts.push(times)
  if (row.expected_attendance) parts.push(`${row.expected_attendance} expected`)
  return parts.join(' · ')
}

/** One badge per outcome in the card, like the coordinator's status summary. */
function outcomeSummary(request) {
  const counts = new Map()
  for (const row of request.sessions) counts.set(row.review.status, (counts.get(row.review.status) || 0) + 1)
  if (counts.size === 1) {
    const [status] = counts.keys()
    return [{ status, label: reviewStatusLabel(status) }]
  }
  return [...counts.entries()].map(([status, count]) => ({ status, label: `${count} ${reviewStatusLabel(status)}` }))
}

const EMPTY_MESSAGES = {
  checkSafety: 'Nothing waiting for a safety check.',
  checked: "You haven't checked any sessions yet.",
}

onMounted(loadReviews)
</script>

<template>
  <section class="safety-dashboard" aria-labelledby="safety-dashboard-title">
    <h2 id="safety-dashboard-title">Safety Checks</h2>

    <p v-if="loading" class="muted">Loading safety checks...</p>
    <p v-else-if="error" class="error" role="alert">Couldn't load safety checks: {{ error }}</p>

    <template v-else>
      <div v-if="attentionRequests.length" class="attention" role="status">
        <p class="attention-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
            stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
            <path d="M12 9v4" />
            <path d="M12 17h.01" />
          </svg>
          {{ attentionRequests.length }} {{ attentionRequests.length === 1 ? 'event needs' : 'events need' }} a safety check
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
        <label for="safety-search" class="visually-hidden">Search safety checks</label>
        <input id="safety-search" v-model="search" type="search" placeholder="Search by event name..." />
      </div>

      <div class="tabs" role="group" aria-label="Filter safety checks">
        <button
          v-for="tab in SAFETY_TABS"
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
                <span v-for="badge in outcomeSummary(request)" :key="badge.status" class="status cs-pill" :class="`review-${badge.status} ${badge.status === 'changes_requested' ? 'cs-pill--pending' : `cs-status-${badge.status}`}`">
                  {{ badge.label }}
                </span>
              </span>
            </span>
          </router-link>

          <ol v-if="request.sessions.length > 1" class="sessions" :aria-label="`Sessions of ${request.name}`">
            <li v-for="row in request.sessions" :key="row.reviewId">
              <router-link :to="reviewLink(row)" class="row session-row">
                <span class="row-main">
                  <span class="session-name">{{ sessionSubtitle(row) }}</span>
                  <span v-if="row.review.comment" class="muted small comment">“{{ row.review.comment }}”</span>
                </span>
                <span class="row-side">
                  <span class="status cs-pill" :class="`review-${row.review.status} ${row.review.status === 'changes_requested' ? 'cs-pill--pending' : `cs-status-${row.review.status}`}`">{{ reviewStatusLabel(row.review.status) }}</span>
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
.safety-dashboard { display: flex; flex-direction: column; gap: var(--cs-space-5); margin-top: 1.5rem; }
h2 { margin: 0; font-size: var(--cs-text-lg); font-family: var(--cs-font-display); color: var(--cs-ink); }
.muted { color: var(--cs-ink-soft); }
.small { font-size: var(--cs-text-xs); }
.error { color: var(--cs-occupied); }
.comment { font-style: italic; }

.attention {
  display: flex; flex-direction: column; gap: var(--cs-space-3);
  background: var(--cs-signal-tint); border: 1px solid var(--cs-signal-light); border-radius: var(--cs-radius-md); padding: var(--cs-space-4) var(--cs-space-5);
}
.attention-title { display: flex; align-items: center; gap: var(--cs-space-2); margin: 0; font-size: var(--cs-text-sm); font-weight: 700; color: var(--cs-signal-strong); }
.attention-row {
  display: flex; justify-content: space-between; gap: var(--cs-space-3);
  padding-left: var(--cs-space-6); font-size: var(--cs-text-sm); color: var(--cs-signal-strong); text-decoration: none;
}
.attention-row:hover .attention-name { text-decoration: underline; }
.attention-name { font-weight: 600; color: var(--cs-ink); }

.search { position: relative; color: var(--cs-ink-soft); }
.search svg { position: absolute; left: 16px; top: 50%; transform: translateY(-50%); }
.search input {
  width: 100%; height: 46px; box-sizing: border-box; padding: 0 16px 0 44px;
  border: 1px solid var(--cs-line-strong); border-radius: var(--cs-radius-sm); background: var(--cs-surface); font: inherit; font-size: var(--cs-text-base);
}

.tabs { display: flex; flex-wrap: wrap; gap: var(--cs-space-2); }
.tab {
  min-height: 36px; padding: 7px var(--cs-space-4); border: 1px solid var(--cs-line); border-radius: var(--cs-radius-full);
  background: var(--cs-surface); color: var(--cs-ink-soft); font: inherit; font-size: var(--cs-text-sm); font-weight: 600; cursor: pointer;
}
.tab.active { background: var(--cs-ink); border-color: var(--cs-ink); color: #fff; }
.tab:focus-visible, .row:focus-visible, .attention-row:focus-visible { outline: 2px solid var(--cs-signal); outline-offset: 2px; }

.list { background: var(--cs-surface); border: 1px solid var(--cs-line); border-radius: var(--cs-radius-md); padding: 4px var(--cs-space-5); }
.empty { padding: var(--cs-space-4) 0; margin: 0; }
.row {
  display: flex; align-items: center; justify-content: space-between; gap: var(--cs-space-3);
  padding: var(--cs-space-4) 0; border-bottom: 1px solid var(--cs-line); color: inherit; text-decoration: none;
}
.row:last-child { border-bottom: none; }

.requests { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--cs-space-3); }
.request { background: var(--cs-surface); border: 1px solid var(--cs-line); border-radius: var(--cs-radius-md); padding: 4px var(--cs-space-5); }
.request-header:only-child { border-bottom: none; }
.badges { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: var(--cs-space-2); }
.sessions { list-style: none; margin: 0 0 10px; padding: 0 0 0 14px; border-left: 2px solid var(--cs-line); }
.session-row { padding: 10px 0; }
.sessions li:last-child .session-row { border-bottom: none; }
.session-name { font-size: var(--cs-text-sm); font-weight: 600; color: var(--cs-ink); }
.session-row:hover .session-name { text-decoration: underline; }
.row:hover .row-name { text-decoration: underline; }
.row-main { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.row-name { font-size: var(--cs-text-sm); font-weight: 600; color: var(--cs-ink); }
.row-side { display: flex; align-items: center; gap: var(--cs-space-3); flex: 0 0 auto; }
.attention-text { font-size: var(--cs-text-xs); font-weight: 600; color: var(--cs-signal-strong); }

.visually-hidden {
  position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap;
}

@media (max-width: 600px) {
  .row { flex-direction: column; align-items: flex-start; }
  .attention-row { flex-direction: column; gap: 2px; }
}
</style>
