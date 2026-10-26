<script setup>
/**
 * Small sibling section shown below CoordinatorEventReview on the event
 * details page (EventDetailsView.vue) -- NOT part of that component
 * itself, so the Venue Booking Request / Approval stories add to the
 * review page without editing Aaralyn's/Justin's review component.
 *
 * Lists every venue booking for this event session (GET
 * /events/<id>/venue-bookings, which the backend already scopes to this
 * one event's history -- see app.venues.booking_service.list_bookings_for_event),
 * newest first, with a link to each one and to request a venue.
 *
 * IS-9: "Changes or cancellation of one venue arrangement should not
 * automatically remove the other venue bookings." A session may hold more
 * than one booking (another venue can be requested while one is active),
 * and each pending or confirmed booking can be cancelled on its own
 * (POST /venues/bookings/<id>/cancel, reason required) -- the others stay
 * exactly as they were.
 *
 * IS-61: a booking released because Venue Staff deleted its venue is marked
 * as such; VenueRemovedAlert, at the top of the page, asks for a new venue.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { apiGet, apiPost } from '../lib/api'
import { statusLabel } from '../lib/coordinatorDashboard'
import { canCancelBooking } from '../lib/venueBookings'

const props = defineProps({
  event: { type: Object, required: true },
})
// IS-9: cancelling a booking of a confirmed event reverts it to planning;
// the page refreshes the event with the row passed here.
const emit = defineEmits(['updated'])

const bookings = ref([])
const loading = ref(true)
const error = ref('')

// Newest first already (list_bookings_for_event orders by created_at desc).
const hasActive = computed(() => bookings.value.some((booking) => ['pending', 'confirmed'].includes(booking.status)))

// Same status precondition as rule_venue_booking_create: a coordinator
// may only request a venue once the event is in planning -- an approved
// event is moved there first with Start Planning. The request link is
// shown only while no booking is pending or confirmed (hasActive): a
// session with a venue booked doesn't request another.
const canRequest = computed(() => props.event.status === 'planning')

// The booking whose cancel form is open, and its reason / outcome.
const cancelling = ref(null)
const cancelReason = ref('')
const cancelError = ref('')
const busy = ref(false)
const success = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    bookings.value = await apiGet(`/events/${props.event.id}/venue-bookings`)
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    loading.value = false
  }
}

function openCancel(booking) {
  cancelling.value = booking.id
  cancelReason.value = ''
  cancelError.value = ''
  success.value = ''
}

function closeCancel() {
  cancelling.value = null
  cancelError.value = ''
}

async function confirmCancel(booking) {
  if (!cancelReason.value.trim()) {
    cancelError.value = 'Please give a reason for cancelling this booking.'
    return
  }
  busy.value = true
  cancelError.value = ''
  try {
    const cancelled = await apiPost(`/venues/bookings/${booking.id}/cancel`, { reason: cancelReason.value.trim() })
    // Replace only this booking: the others are unchanged by design.
    bookings.value = bookings.value.map((row) => (row.id === booking.id ? { ...row, ...cancelled } : row))
    cancelling.value = null
    success.value = 'Venue booking cancelled. Your other venue bookings for this session are unchanged.'
    if (cancelled.event_reverted_to_planning) {
      success.value += ' The event was confirmed, so it has gone back to planning.'
      try {
        emit('updated', await apiGet(`/events/${props.event.id}`))
      } catch {
        // The cancellation itself succeeded; a stale status corrects on reload.
      }
    }
  } catch (requestError) {
    cancelError.value = requestError.message
  } finally {
    busy.value = false
  }
}

function venueName(booking) {
  return booking.venues?.name ?? null
}

onMounted(load)
watch(() => props.event.id, () => {
  cancelling.value = null
  success.value = ''
  load()
})
</script>

<template>
  <section class="venue-booking" aria-labelledby="venue-booking-heading">
    <h2 id="venue-booking-heading">Venue Booking</h2>

    <p v-if="loading" class="muted small">Loading venue booking status...</p>
    <p v-else-if="error" class="error" role="alert">Couldn't load venue booking status: {{ error }}</p>

    <template v-else>
      <p v-if="!bookings.length" class="muted small">No venue has been requested for this session yet.</p>
      <ul v-else class="bookings">
        <li v-for="booking in bookings" :key="booking.id" class="booking" :data-booking="booking.id">
          <div class="latest">
            <span class="status" :class="`status-${booking.status}`">{{ statusLabel(booking.status) }}</span>
            <span v-if="venueName(booking)" class="venue-name">{{ venueName(booking) }}</span>
            <router-link :to="{ name: 'venue-booking-review', params: { bookingId: booking.id } }" class="link">
              View booking
            </router-link>
            <button v-if="canCancelBooking(booking, event) && cancelling !== booking.id" type="button"
              class="btn small reject" :disabled="busy" @click="openCancel(booking)">
              Cancel booking
            </button>
          </div>
          <p v-if="booking.status === 'rejected'" class="rejection-reason">
            Reason: {{ booking.rejection?.reason || 'No reason was recorded.' }}
          </p>
          <p v-if="booking.released_by_venue_deletion" class="released small" data-test="released-by-deletion">
            Released: this venue was deleted from the venue catalogue by Venue Staff.
          </p>
          <p v-else-if="booking.status === 'cancelled'" class="muted small">
            Cancelled: {{ booking.cancellation?.reason || 'No reason was recorded.' }}
          </p>

          <form v-if="cancelling === booking.id" class="panel" @submit.prevent="confirmCancel(booking)">
            <label :for="`cancel-booking-${booking.id}`">Reason for cancelling this booking</label>
            <textarea :id="`cancel-booking-${booking.id}`" v-model="cancelReason" rows="2"
              placeholder="e.g. moved the breakout session to another room." />
            <p class="muted small">Only this booking is cancelled. Any other venue bookings for this session stay as they are.</p>
            <p v-if="event.status === 'confirmed'" class="muted small" data-test="reverts-to-planning">
              This event is confirmed, so cancelling this booking sends it back to planning.
            </p>
            <div class="panel-actions">
              <button type="submit" class="btn small reject-solid" :disabled="busy">
                {{ busy ? 'Cancelling...' : 'Confirm Cancellation' }}
              </button>
              <button type="button" class="btn small neutral" :disabled="busy" @click="closeCancel">Keep Booking</button>
            </div>
            <p v-if="cancelError" class="error" role="alert">{{ cancelError }}</p>
          </form>
        </li>
      </ul>
      <p v-if="success" class="success" role="status">{{ success }}</p>

      <p v-if="event.status === 'approved'" class="muted small">
        Start planning (under Your Decision) to request a venue.
      </p>
      <router-link
        v-if="canRequest && !hasActive"
        :to="{ name: 'request-venue-booking', params: { eventId: event.id } }"
        class="btn small primary"
      >
        {{ bookings.length ? 'Request a different venue' : 'Request Venue Booking' }}
      </router-link>
    </template>
  </section>
</template>

<style scoped>
.venue-booking { display: flex; flex-direction: column; gap: 10px; padding-top: 16px; border-top: 1px solid #dcdcdc; }
h2 { margin: 0; font-size: 15px; color: #222; }
.muted { color: #6b6b6b; }
.small { font-size: 13px; margin: 0; }
.error { color: #a33f3f; margin: 0; }
.success { color: #2f6b3f; margin: 0; font-size: 13px; }
.bookings { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
.booking { display: flex; flex-direction: column; gap: 6px; }
.latest { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.venue-name { font-size: 13px; font-weight: 600; color: #2a2a2a; }
.link { font-size: 13px; color: #2568e8; text-decoration: underline; }
.rejection-reason { margin: 0; font-size: 13px; color: #a33f3f; }
.released { color: #7a4a06; }

.status { font-size: 12px; font-weight: 600; border-radius: 10px; padding: 4px 12px; background: #eee; color: #5a5a5a; }
.status-pending { background: #f7efe1; color: #8a5a12; }
.status-confirmed { background: #eaf5ec; color: #2f6b3f; }
.status-rejected { background: #f5e6e6; color: #a33f3f; }
.status-cancelled { background: #fcebdd; color: #a3521b; }

.panel {
  display: flex; flex-direction: column; gap: 8px;
  background: #fbf1f1; border: 1px solid #d9a3a3; border-radius: 6px; padding: 12px 14px;
}
.panel label { font-size: 12px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: #6a6a6a; }
.panel textarea {
  box-sizing: border-box; width: 100%; padding: 8px 10px; border: 1px solid #b8b8b8; border-radius: 4px;
  background: #fff; font: inherit; font-size: 14px; resize: vertical;
}
.panel-actions { display: flex; gap: 10px; flex-wrap: wrap; }

.btn {
  min-height: 34px; padding: 0 14px; border-radius: 4px; font: inherit; font-size: 13px; font-weight: 700;
  cursor: pointer; background: #fff;
}
.btn:disabled { opacity: .6; cursor: not-allowed; }
.reject { border: 1px solid #a33f3f; color: #a33f3f; }
.reject-solid { border: none; background: #a33f3f; color: #fff; }
.neutral { border: 1px solid #b8b8b8; color: #444; }

.btn.small.primary {
  align-self: flex-start; min-height: 38px; padding: 0 16px; border: none; border-radius: 4px;
  background: #2568e8; color: #fff; font: inherit; font-size: 13px; font-weight: 700;
  text-decoration: none; display: inline-flex; align-items: center;
}
</style>
