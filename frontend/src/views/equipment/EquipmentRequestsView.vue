<script setup>
/**
 * Technical Support Staff's equipment request queue -- Check Equipment
 * Availability (Nawaz, Sprint 2, IS-18), AC1: "Can select an equipment
 * request ...". Structurally mirrors VenueBookingQueueView.vue (tabs,
 * search, list) using lib/equipment.js.
 *
 * GET /equipment/requests already scopes rows per caller (unfiltered for
 * technical_support_staff -- see app.equipment.equipment_service.
 * list_requests). Creating a request is the separate "Record Equipment
 * Request for Event" story and isn't on this screen.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiGet } from '../../lib/api'
import AppNavBar from '../../components/AppNavBar.vue'
import {
  REQUEST_TABS,
  describeChange,
  formatPeriod,
  groupRequestsByTab,
  isRequestTab,
  summariseItems,
} from '../../lib/equipment'
import { statusLabel } from '../../lib/coordinatorDashboard'

const route = useRoute()
const router = useRouter()

const requests = ref([])
const loading = ref(true)
const error = ref('')
const activeTab = ref(isRequestTab(route.query.tab) ? route.query.tab : 'pending')
const search = ref('')
// Quantity changes waiting for a decision (IS-43). Loaded separately: the
// queue still works if this fails.
const pendingChanges = ref([])

function selectTab(key) {
  activeTab.value = key
  router.replace({ query: { ...route.query, tab: key } })
}

const groups = computed(() => groupRequestsByTab(requests.value))
const visibleRequests = computed(() => {
  const needle = search.value.trim().toLowerCase()
  const rows = groups.value[activeTab.value]
  if (!needle) return rows
  return rows.filter((request) => (request.event_name ?? '').toLowerCase().includes(needle))
})

async function loadRequests() {
  loading.value = true
  error.value = ''
  try {
    requests.value = await apiGet('/equipment/requests')
    try {
      const changes = await apiGet('/equipment/change-requests')
      pendingChanges.value = Array.isArray(changes) ? changes : []
    } catch {
      pendingChanges.value = []
    }
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    loading.value = false
  }
}

const EMPTY_MESSAGES = {
  pending: 'No equipment requests waiting to be checked.',
  confirmed: 'No confirmed equipment requests yet.',
  rejected: 'No rejected equipment requests.',
  cancelled: 'No cancelled equipment requests.',
}

onMounted(loadRequests)
</script>

<template>
  <div class="page">
    <AppNavBar />
    <main class="content">
      <div class="container">
        <h1 class="title">Equipment Requests</h1>

        <p v-if="loading" class="message">Loading equipment requests...</p>
        <p v-else-if="error" class="message error" role="alert">Couldn't load equipment requests: {{ error }}</p>

        <template v-else>
          <div class="search">
            <label for="request-search" class="visually-hidden">Search by event name</label>
            <input id="request-search" v-model="search" type="search" placeholder="Search by event name..." />
          </div>

          <section v-if="pendingChanges.length" class="changes" aria-labelledby="pending-changes-heading">
            <h2 id="pending-changes-heading" class="changes-title">
              Quantity changes waiting ({{ pendingChanges.length }})
            </h2>
            <router-link
              v-for="change in pendingChanges"
              :key="change.id"
              :to="{ name: 'equipment-request-details', params: { requestId: change.request_id } }"
              class="change-link"
            >
              <span class="row-name">{{ change.event_name ?? 'Untitled event' }}</span>
              <span class="row-meta">{{ describeChange(change) }}</span>
            </router-link>
          </section>

          <div class="tabs" role="group" aria-label="Filter by status">
            <button
              v-for="tab in REQUEST_TABS"
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
            <p v-if="visibleRequests.length === 0" class="message">
              {{ search.trim() ? `No requests match "${search.trim()}".` : EMPTY_MESSAGES[activeTab] }}
            </p>
            <router-link
              v-for="request in visibleRequests"
              :key="request.id"
              :to="{ name: 'equipment-request-details', params: { requestId: request.id } }"
              class="row"
            >
              <div class="row-main">
                <span class="row-name">{{ request.event_name ?? 'Untitled event' }}</span>
                <span class="row-meta">{{ formatPeriod(request.needed_start, request.needed_end) }}</span>
                <span class="row-meta">{{ summariseItems(request.items) }}</span>
              </div>
              <span class="status cs-pill" :class="`status-${request.status} cs-status-${request.status}`">{{ statusLabel(request.status) }}</span>
            </router-link>
          </div>
        </template>
      </div>
    </main>
  </div>
</template>

<style scoped>
.page { min-height: 100vh; display: flex; flex-direction: column; }
.content { flex: 1 1 auto; padding: var(--cs-space-6) var(--cs-space-4) var(--cs-space-8); display: flex; justify-content: center; }
.container { width: 100%; max-width: 880px; display: flex; flex-direction: column; gap: var(--cs-space-5); }
.title { margin: 0; font-size: var(--cs-text-xl); font-family: var(--cs-font-display); color: var(--cs-ink); }
.message { margin: 0; padding: var(--cs-space-4) 0; font-size: var(--cs-text-base); color: var(--cs-ink-soft); }
.error { color: var(--cs-occupied); }

.search input {
  width: 100%; height: 46px; box-sizing: border-box; padding: 0 var(--cs-space-4);
  border: 1px solid var(--cs-line-strong); border-radius: var(--cs-radius-sm); background: var(--cs-surface); font: inherit; font-size: var(--cs-text-base);
}
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }

.changes { background: var(--cs-signal-tint); border: 1px solid var(--cs-signal-light); border-radius: var(--cs-radius-md); padding: var(--cs-space-3) var(--cs-space-5); display: flex; flex-direction: column; gap: var(--cs-space-2); }
.changes-title { margin: 0; font-size: var(--cs-text-sm); font-weight: 700; color: var(--cs-signal-strong); }
.change-link { display: flex; justify-content: space-between; gap: var(--cs-space-3); text-decoration: none; color: var(--cs-ink); font-size: var(--cs-text-base); }
.tabs { display: flex; align-items: center; gap: var(--cs-space-2); flex-wrap: wrap; }
.tab {
  border: 1px solid var(--cs-line); background: var(--cs-surface); color: var(--cs-ink-soft); font-size: var(--cs-text-sm); font-weight: 600;
  padding: 7px var(--cs-space-4); border-radius: var(--cs-radius-full); cursor: pointer;
}
.tab.active { border-color: var(--cs-ink); background: var(--cs-ink); color: #ffffff; }

.list { background: var(--cs-surface); border: 1px solid var(--cs-line); border-radius: var(--cs-radius-md); padding: 4px 18px; box-sizing: border-box; }
.row {
  display: flex; align-items: center; justify-content: space-between; gap: var(--cs-space-3);
  padding: var(--cs-space-4) 0; border-bottom: 1px solid var(--cs-line); text-decoration: none; color: inherit;
}
.row:last-child { border-bottom: none; }
.row:hover .row-name { text-decoration: underline; }
.row-main { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.row-name { font-size: var(--cs-text-sm); font-weight: 600; color: var(--cs-ink); }
.row-meta { font-size: var(--cs-text-xs); color: var(--cs-ink-soft); }

@media (max-width: 600px) {
  .row { flex-direction: column; align-items: flex-start; }
}
</style>
