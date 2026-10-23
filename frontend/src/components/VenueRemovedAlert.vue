<script setup>
/**
 * IS-61 AC4: "Once a venue is deleted, ongoing events that have booked the
 * venue will lose their booking and the coordinator will be alerted to book
 * another venue on the event details page for coordinator."
 *
 * Shown at the top of the coordinator's event details page
 * (EventDetailsView.vue) while this session has a booking that was released
 * because Venue Staff deleted its venue and hasn't been replaced yet
 * (lib/venueBookings.js::unreplacedVenueReleases). The released booking
 * itself stays listed, marked, under Venue Booking (VenueBookingStatus.vue).
 *
 * Deleting the venue also sent a confirmed session (or one under a safety
 * check) back to planning, so the request link is there straight away.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { apiGet } from '../lib/api'
import { unreplacedVenueReleases } from '../lib/venueBookings'

const props = defineProps({
  event: { type: Object, required: true },
})

const bookings = ref([])

const released = computed(() => unreplacedVenueReleases(bookings.value, props.event))
const venueNames = computed(() => [...new Set(released.value.map((booking) => booking.venues?.name ?? 'A venue'))])
const canRequest = computed(() => props.event.status === 'planning')

async function load() {
  try {
    bookings.value = await apiGet(`/events/${props.event.id}/venue-bookings`)
  } catch {
    // VenueBookingStatus, lower on the same page, shows the load error.
    bookings.value = []
  }
}

onMounted(load)
watch(() => [props.event.id, props.event.status], load)
</script>

<template>
  <section v-if="released.length" class="venue-removed" role="alert" data-test="venue-removed-alert">
    <h2>Book another venue</h2>
    <p>
      <template v-if="venueNames.length === 1">
        <strong>{{ venueNames[0] }}</strong> was deleted from the venue catalogue
      </template>
      <template v-else>
        <strong>{{ venueNames.join(', ') }}</strong> were deleted from the venue catalogue
      </template>
      by Venue Staff, so this session's booking {{ released.length === 1 ? 'was' : 'were' }} released.
      This session no longer has {{ released.length === 1 ? 'that venue' : 'those venues' }}.
    </p>
    <router-link
      v-if="canRequest"
      :to="{ name: 'request-venue-booking', params: { eventId: event.id } }"
      class="action"
    >
      Request another venue
    </router-link>
    <p v-else class="small">
      Once this session is back in planning, request another venue under Venue Booking.
    </p>
  </section>
</template>

<style scoped>
.venue-removed {
  display: flex; flex-direction: column; gap: 8px;
  background: #fff4e5; border: 1px solid #e0a54a; border-left: 4px solid #c27c0e; border-radius: 6px;
  padding: 14px 16px;
}
h2 { margin: 0; font-size: 15px; color: #7a4a06; }
p { margin: 0; font-size: 14px; color: #4a3a22; }
.small { font-size: 13px; }
.action {
  align-self: flex-start; min-height: 36px; padding: 0 16px; border-radius: 4px;
  background: #2568e8; color: #fff; font-size: 13px; font-weight: 700;
  text-decoration: none; display: inline-flex; align-items: center;
}
</style>
