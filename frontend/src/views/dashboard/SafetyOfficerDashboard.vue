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
                <span v-for="badge in outcomeSummary(request)" :key="badge.status" class="status" :class="`review-${badge.status}`">
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
                  <span class="status" :class="`review-${row.review.status}`">{{ reviewStatusLabel(row.review.status) }}</span>
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
.safety-dashboard { display: flex; flex-direction: column; gap: 20px; margin-top: 1.5rem; }
h2 { margin: 0; font-size: 20px; color: #1f1f1f; }
.muted { color: #6b6b6b; }
.small { font-size: 12px; }
.error { color: #a33f3f; }
.comment { font-style: italic; }

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

.requests { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 12px; }
.request { background: #fff; border: 1px solid #d0d0d0; border-radius: 6px; padding: 4px 18px; }
.request-header:only-child { border-bottom: none; }
.badges { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 6px; }
.sessions { list-style: none; margin: 0 0 10px; padding: 0 0 0 14px; border-left: 2px solid #e2e2e2; }
.session-row { padding: 10px 0; }
.sessions li:last-child .session-row { border-bottom: none; }
.session-name { font-size: 13px; font-weight: 600; color: #444; }
.session-row:hover .session-name { text-decoration: underline; }
.row:hover .row-name { text-decoration: underline; }
.row-main { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.row-name { font-size: 14px; font-weight: 600; color: #2a2a2a; }
.row-side { display: flex; align-items: center; gap: 10px; flex: 0 0 auto; }
.attention-text { font-size: 11px; font-weight: 600; color: #8a5a12; }

.status { font-size: 11px; font-weight: 600; border-radius: 10px; padding: 3px 10px; white-space: nowrap; background: #eee; color: #5a5a5a; }
.review-pending { color: #3d4fa8; background: #e8ebfa; }
.review-approved { color: #2f6b3f; background: #eaf5ec; }
.review-changes_requested { color: #8a5a12; background: #f7efe1; }
.review-rejected { color: #a33f3f; background: #f5e6e6; }

.visually-hidden {
  position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap;
}

@media (max-width: 600px) {
  .row { flex-direction: column; align-items: flex-start; }
  .attention-row { flex-direction: column; gap: 2px; }
}
</style>
