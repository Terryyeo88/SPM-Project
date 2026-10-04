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
              <span class="status" :class="`status-${booking.status}`">{{ statusLabel(booking.status) }}</span>
            </router-link>
          </div>
        </template>
      </div>
    </main>
  </div>
</template>

<style scoped>
.page { min-height: 100vh; display: flex; flex-direction: column; background: #eeeeee; }
.content { flex: 1 1 auto; padding: 32px 16px; display: flex; justify-content: center; }
.container { width: 100%; max-width: 880px; display: flex; flex-direction: column; gap: 20px; }
.title { margin: 0; font-size: 20px; font-weight: 700; color: #1f1f1f; }
.message { margin: 0; padding: 16px 0; font-size: 14px; color: #8a8a8a; }
.error { color: #b42318; }

.search input {
  width: 100%; height: 46px; box-sizing: border-box; padding: 0 16px;
  border: 1px solid #b0b0b0; border-radius: 8px; background: #fff; font: inherit; font-size: 14px;
}
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }

.tabs { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.tab {
  border: 1px solid #b0b0b0; background: #ffffff; color: #555555; font-size: 13px; font-weight: 600;
  padding: 7px 16px; border-radius: 20px; cursor: pointer;
}
.tab.active { border-color: #444444; background: #444444; color: #ffffff; }

.list { background: #ffffff; border: 1px dashed #9a9a9a; border-radius: 6px; padding: 4px 18px; box-sizing: border-box; }
.row {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 16px 0; border-bottom: 1px dashed #e2e2e2; text-decoration: none; color: inherit;
}
.row:last-child { border-bottom: none; }
.row:hover .row-name { text-decoration: underline; }
.row-main { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.row-name { font-size: 14px; font-weight: 600; color: #2a2a2a; }
.row-meta { font-size: 12px; color: #8a8a8a; }

.status { font-size: 11px; font-weight: 600; color: #6a6a6a; background: #f0f0f0; border-radius: 10px; padding: 3px 10px; white-space: nowrap; }
.status-pending { color: #8a6d00; background: #fff4c2; }
.status-confirmed { color: #0f6e6a; background: #ddf3f1; }
.status-rejected { color: #b42318; background: #fde8e6; }

@media (max-width: 600px) {
  .row { flex-direction: column; align-items: flex-start; }
}
</style>
