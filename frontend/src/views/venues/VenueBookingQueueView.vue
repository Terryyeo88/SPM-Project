<script setup>
/**
 * Venue Staff's booking queue ("Booking Review" wireframe's list half) --
 * Venue Booking Approval (Josiah, Sprint 2). Structurally mirrors
 * CoordinatorDashboard.vue (tabs, search, list), using venueBookings.js
 * instead of coordinatorDashboard.js.
 *
 * GET /venues/bookings already scopes rows per caller (unfiltered for
 * venue_staff -- see app.venues.booking_service.list_bookings; no
 * per-venue-staff-assignment table exists yet), so every row here is
 * one this caller may act on or at least see.
 *
 * Not in this pass: a "My Venues" filter tab -- that's the separate,
 * unassigned Block Venue story bundled into the same wireframe.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiGet } from '../../lib/api'
import AppNavBar from '../../components/AppNavBar.vue'
import { BOOKING_TABS, groupBookingsByTab, isBookingTab } from '../../lib/venueBookings'
import { statusLabel } from '../../lib/coordinatorDashboard'

const route = useRoute()
const router = useRouter()

const bookings = ref([])
const loading = ref(true)
const error = ref('')
const activeTab = ref(isBookingTab(route.query.tab) ? route.query.tab : 'pending')
const search = ref('')

function selectTab(key) {
  activeTab.value = key
  router.replace({ query: { ...route.query, tab: key } })
}

const groups = computed(() => groupBookingsByTab(bookings.value))
const visibleBookings = computed(() => {
  const needle = search.value.trim().toLowerCase()
  const rows = groups.value[activeTab.value]
  if (!needle) return rows
  return rows.filter((booking) => (booking.events?.name ?? '').toLowerCase().includes(needle))
})

async function loadBookings() {
  loading.value = true
  error.value = ''
  try {
    bookings.value = await apiGet('/venues/bookings')
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    loading.value = false
  }
}

function bookingLink(booking) {
  return { name: 'venue-booking-review', params: { bookingId: booking.id } }
}

const EMPTY_MESSAGES = {
  pending: 'Nothing waiting for a decision.',
  confirmed: 'No confirmed bookings yet.',
  rejected: 'No rejected bookings.',
  released: 'No released bookings.',
  cancelled: 'No cancelled bookings.',
}

onMounted(loadBookings)
</script>

<template>
  <div class="page">
    <AppNavBar />
    <main class="content">
      <div class="container">
        <h1 class="title">Venue Bookings</h1>

        <p v-if="loading" class="message">Loading bookings...</p>
        <p v-else-if="error" class="message error" role="alert">Couldn't load bookings: {{ error }}</p>

        <template v-else>
          <div class="search">
            <label for="booking-search" class="visually-hidden">Search by event name</label>
            <input id="booking-search" v-model="search" type="search" placeholder="Search by event name..." />
          </div>

          <div class="tabs" role="group" aria-label="Filter by stage">
            <button
              v-for="tab in BOOKING_TABS"
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
            <p v-if="visibleBookings.length === 0" class="message">
              {{ search.trim() ? `No bookings match "${search.trim()}".` : EMPTY_MESSAGES[activeTab] }}
            </p>
            <router-link v-for="booking in visibleBookings" :key="booking.id" :to="bookingLink(booking)" class="row">
              <div class="row-main">
                <span class="row-name">{{ booking.events?.name ?? 'Untitled event' }}</span>
                <span class="row-meta">{{ booking.venues?.name ?? 'Unknown venue' }}</span>
              </div>
              <span class="status cs-pill" :class="`status-${booking.status} cs-status-${booking.status}`">{{ statusLabel(booking.status) }}</span>
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
