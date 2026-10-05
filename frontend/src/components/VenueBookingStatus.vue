<script setup>
/**
 * Small sibling section shown below CoordinatorEventReview on the event
 * details page (EventDetailsView.vue) -- NOT part of that component
 * itself, so the Venue Booking Request / Approval stories add to the
 * review page without editing Aaralyn's/Justin's review component.
 *
 * Shows the latest venue booking for this event session (if any) and a
 * link to either request one (none yet, or the last one was rejected)
 * or view the existing one's outcome (GET /events/<id>/venue-bookings,
 * which the backend already scopes to this one event's history --
 * see app.venues.booking_service.list_bookings_for_event).
 */
import { computed, onMounted, ref, watch } from 'vue'
import { apiGet } from '../lib/api'
import { statusLabel } from '../lib/coordinatorDashboard'

const props = defineProps({
  event: { type: Object, required: true },
})

const bookings = ref([])
const loading = ref(true)
const error = ref('')

// Newest first already (list_bookings_for_event orders by created_at
// desc) -- the first row is "the latest" by construction.
const latest = computed(() => bookings.value[0] ?? null)

// Same status precondition as rule_venue_booking_create: a coordinator
// may only start (or restart, after a rejection) a venue search once the
// event is approved or already in planning.
const canRequest = computed(() => ['approved', 'planning'].includes(props.event.status))

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

onMounted(load)
watch(() => props.event.id, load)
</script>

<template>
  <section class="venue-booking" aria-labelledby="venue-booking-heading">
    <h2 id="venue-booking-heading">Venue Booking</h2>

    <p v-if="loading" class="muted small">Loading venue booking status...</p>
    <p v-else-if="error" class="error" role="alert">Couldn't load venue booking status: {{ error }}</p>

    <template v-else>
      <p v-if="!latest" class="muted small">No venue has been requested for this session yet.</p>
      <div v-else class="latest">
        <span class="status" :class="`status-${latest.status}`">{{ statusLabel(latest.status) }}</span>
        <router-link :to="{ name: 'venue-booking-review', params: { bookingId: latest.id } }" class="link">
          View booking
        </router-link>
      </div>
      <p v-if="latest?.status === 'rejected'" class="rejection-reason">
        Reason: {{ latest.rejection?.reason || 'No reason was recorded.' }}
      </p>

      <router-link
        v-if="canRequest && (!latest || latest.status === 'rejected')"
        :to="{ name: 'request-venue-booking', params: { eventId: event.id } }"
        class="btn small primary"
      >
        {{ latest ? 'Request a different venue' : 'Request Venue Booking' }}
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
.latest { display: flex; align-items: center; gap: 12px; }
.link { font-size: 13px; color: #2568e8; text-decoration: underline; }
.rejection-reason { margin: 0; font-size: 13px; color: #a33f3f; }

.status { font-size: 12px; font-weight: 600; border-radius: 10px; padding: 4px 12px; background: #eee; color: #5a5a5a; }
.status-pending { background: #f7efe1; color: #8a5a12; }
.status-confirmed { background: #eaf5ec; color: #2f6b3f; }
.status-rejected { background: #f5e6e6; color: #a33f3f; }

.btn.small.primary {
  align-self: flex-start; min-height: 38px; padding: 0 16px; border: none; border-radius: 4px;
  background: #2568e8; color: #fff; font: inherit; font-size: 13px; font-weight: 700;
  text-decoration: none; display: inline-flex; align-items: center;
}
</style>
