<script setup>
/**
 * Booking Review -- Venue Staff approve/reject a pending venue booking
 * (Venue Booking Approval, Josiah, Sprint 2), after the wireframe's
 * "Booking Review" screen: requested booking details, a suitability
 * panel, then Approve/Reject.
 *
 * Also reachable by the REQUESTING coordinator (rule_venue_booking_view
 * allows both) to view the outcome read-only -- satisfies Approval AC2
 * ("the Coordinator can view it") for a rejection reason. Decision
 * buttons only render for venue_staff on a still-pending booking;
 * app.authz.rules.rule_venue_booking_approve/reject is the real
 * enforcement regardless of what this page shows.
 *
 * Suitability panel: capacity/layout/accessibility are a pure client-side
 * comparison (lib/venueSuitability.js) between the event session already
 * fetched and the venue already fetched -- no new endpoint needed. The
 * turnaround-conflict half is server-computed (booking.conflict, from
 * app.venues.booking_service.get_booking) since it needs cross-booking
 * knowledge only the backend has.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { apiGet, apiPost } from '../../lib/api'
import { useAuthStore } from '../../stores/auth'
import { statusLabel } from '../../lib/coordinatorDashboard'
import { checkSuitability } from '../../lib/venueSuitability'
import AppNavBar from '../../components/AppNavBar.vue'

const route = useRoute()
const auth = useAuthStore()

const booking = ref(null)
const event = ref(null)
const venue = ref(null)
const loading = ref(true)
const loadError = ref('')

const openPanel = ref(null) // null | 'reject'
const busy = ref(false)
const error = ref('')
const success = ref('')
const rejectReason = ref('')

const isVenueStaff = computed(() => auth.roles.includes('venue_staff'))
const isPending = computed(() => booking.value?.status === 'pending')
const canDecide = computed(() => isVenueStaff.value && isPending.value)

const suitability = computed(() => (event.value && venue.value ? checkSuitability(event.value, venue.value) : []))

function time(value) {
  return value ? value.slice(0, 5) : ''
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    booking.value = await apiGet(`/venues/bookings/${route.params.bookingId}`)
    const [loadedEvent, loadedVenue] = await Promise.all([
      apiGet(`/events/${booking.value.event_id}`),
      apiGet(`/venues/${booking.value.venue_id}`),
    ])
    event.value = loadedEvent
    venue.value = loadedVenue
  } catch (requestError) {
    loadError.value = requestError.message
  } finally {
    loading.value = false
  }
}

async function run(action) {
  busy.value = true
  error.value = ''
  success.value = ''
  try {
    await action()
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    busy.value = false
  }
}

function approve() {
  return run(async () => {
    booking.value = await apiPost(`/venues/bookings/${booking.value.id}/approve`, {})
    success.value = 'Booking confirmed -- the venue is now unavailable for this period.'
  })
}

function reject() {
  if (!rejectReason.value.trim()) {
    error.value = 'Please give the coordinator a reason for rejecting.'
    return
  }
  return run(async () => {
    booking.value = await apiPost(`/venues/bookings/${booking.value.id}/reject`, { reason: rejectReason.value.trim() })
    openPanel.value = null
    rejectReason.value = ''
    success.value = 'Booking rejected. The coordinator can see the reason.'
  })
}

function togglePanel(name) {
  error.value = ''
  success.value = ''
  openPanel.value = openPanel.value === name ? null : name
}

onMounted(load)
</script>

<template>
  <div class="page">
    <AppNavBar />
    <main class="content">
      <div class="container">
        <router-link v-if="isVenueStaff" :to="{ name: 'venue-booking-queue' }" class="back-link">&larr; Back to queue</router-link>
        <router-link v-else-if="booking" :to="{ name: 'event-details', params: { eventId: booking.event_id } }" class="back-link">
          &larr; Back to event
        </router-link>

        <p v-if="loading" class="message">Loading booking...</p>
        <p v-else-if="loadError" class="message error" role="alert">{{ loadError }}</p>

        <template v-else-if="booking">
          <div class="page-heading">
            <h1 class="page-title">{{ event?.name }}</h1>
            <span class="page-subtitle">{{ venue?.name }}</span>
          </div>
          <span class="status" :class="`status-${booking.status}`">{{ statusLabel(booking.status) }}</span>

          <section class="card" aria-labelledby="booking-details-heading">
            <h2 id="booking-details-heading" class="card-title">Booking Details</h2>
            <div class="detail-row">
              <span class="muted">Session</span>
              <span class="value">
                {{ event?.preferred_start_date }}<template v-if="event?.preferred_start_time">
                  , {{ time(event.preferred_start_time) }} – {{ time(event.preferred_end_time) }}</template>
              </span>
            </div>
            <div class="detail-row">
              <span class="muted">Expected attendance</span>
              <span class="value">{{ event?.expected_attendance ?? 'Not specified' }}</span>
            </div>
            <div class="detail-row">
              <span class="muted">Requested venue</span>
              <span class="value">{{ venue?.name }} (capacity {{ venue?.capacity }})</span>
            </div>
          </section>

          <section class="card" aria-labelledby="suitability-heading">
            <h2 id="suitability-heading" class="card-title">Suitability Check</h2>
            <div v-for="check in suitability" :key="check.label" class="suitability-row">
              <span class="suitability-icon" :class="check.ok ? 'ok' : 'warn'">{{ check.ok ? '✓' : '!' }}</span>
              <div>
                <span class="suitability-label">{{ check.label }}</span>
                <p class="muted small">{{ check.detail }}</p>
              </div>
            </div>
            <div v-if="booking.conflict" class="suitability-row">
              <span class="suitability-icon warn">!</span>
              <div>
                <span class="suitability-label">Turnaround conflict</span>
                <p class="muted small">
                  This venue already has another confirmed booking overlapping this period (including
                  setup/turnaround buffers).
                </p>
              </div>
            </div>
          </section>

          <section class="decision" aria-labelledby="decision-heading">
            <h2 id="decision-heading">Decision</h2>

            <p v-if="!isPending && booking.status === 'rejected'" class="muted small">
              Rejected{{ booking.rejection?.reason ? `: ${booking.rejection.reason}` : '' }}
            </p>
            <p v-else-if="!isPending" class="muted small">
              This booking is {{ statusLabel(booking.status).toLowerCase() }}.
            </p>
            <p v-else-if="!isVenueStaff" class="muted small">Waiting on Venue Staff to decide.</p>

            <div v-if="canDecide" class="buttons">
              <button type="button" class="btn approve" :disabled="busy" @click="approve">
                {{ busy && !openPanel ? 'Confirming...' : 'Approve Booking' }}
              </button>
              <button type="button" class="btn reject" :aria-expanded="openPanel === 'reject'" :disabled="busy"
                @click="togglePanel('reject')">
                Reject Booking
              </button>
            </div>

            <form v-if="openPanel === 'reject'" class="panel" @submit.prevent="reject">
              <label for="reject-reason">Reason for rejecting</label>
              <textarea id="reject-reason" v-model="rejectReason" rows="3"
                placeholder="Tell the coordinator why, so they can request a different venue." />
              <div class="panel-actions">
                <button type="submit" class="btn small reject-solid" :disabled="busy">
                  {{ busy ? 'Rejecting...' : 'Confirm Rejection' }}
                </button>
                <button type="button" class="btn small neutral" :disabled="busy" @click="togglePanel('reject')">Cancel</button>
              </div>
            </form>

            <p v-if="error" class="message error" role="alert">{{ error }}</p>
            <p v-if="success" class="message success" role="status">{{ success }}</p>
          </section>
        </template>
      </div>
    </main>
  </div>
</template>

<style scoped src="../../styles/event-form.css"></style>
<style scoped>
.detail-row { display: flex; justify-content: space-between; gap: 16px; padding: 8px 0; border-bottom: 1px solid #ececec; font-size: 13px; }
.detail-row:last-child { border-bottom: none; }
.muted { color: #6b6b6b; }
.small { font-size: 12px; margin: 4px 0 0; }
.value { color: #2a2a2a; font-weight: 600; text-align: right; }

.suitability-row { display: flex; align-items: flex-start; gap: 10px; padding: 8px 0; }
.suitability-icon {
  flex: 0 0 auto; width: 20px; height: 20px; border-radius: 50%; display: flex; align-items: center;
  justify-content: center; font-size: 12px; font-weight: 700;
}
.suitability-icon.ok { background: #eaf5ec; color: #2f6b3f; }
.suitability-icon.warn { background: #fdf6ec; color: #8a5a12; }
.suitability-label { font-size: 13px; font-weight: 600; color: #2a2a2a; }

.decision { display: flex; flex-direction: column; gap: 14px; }
.decision h2 { margin: 0; font-size: 15px; color: #222; }
.buttons { display: flex; flex-wrap: wrap; gap: 12px; }
.btn {
  min-height: 46px; padding: 0 22px; border-radius: 4px; font: inherit; font-size: 14px; font-weight: 700;
  cursor: pointer; background: #fff;
}
.btn:disabled { opacity: .6; cursor: not-allowed; }
.btn.small { min-height: 38px; padding: 0 16px; font-size: 13px; }
.approve { border: none; background: #2f6b3f; color: #fff; }
.reject { border: 1px solid #a33f3f; color: #a33f3f; }
.reject-solid { border: none; background: #a33f3f; color: #fff; }
.neutral { border: 1px solid #b8b8b8; color: #444; }

.panel {
  display: flex; flex-direction: column; gap: 8px;
  background: #fbf1f1; border: 1px solid #d9a3a3; border-radius: 6px; padding: 16px 18px;
}
.panel label { font-size: 12px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: #6a6a6a; }
.panel textarea {
  box-sizing: border-box; width: 100%; padding: 10px 12px; border: 1px solid #b8b8b8; border-radius: 4px;
  background: #fff; font: inherit; font-size: 14px; resize: vertical;
}
.panel-actions { display: flex; gap: 10px; margin-top: 4px; }
</style>
