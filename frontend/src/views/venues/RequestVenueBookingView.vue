<script setup>
/**
 * Venue Booking Request (Josiah, Sprint 2) -- the assigned coordinator
 * picks a venue from the catalogue (GET /venues) and submits a booking
 * request for this event session (POST /events/<eventId>/venue-bookings).
 * Reached from VenueBookingStatus.vue's "Request Venue Booking" link on
 * the event details page.
 *
 * Every OTHER requirement the wireframe shows (capacity, dates,
 * accessibility, layout) already lives on the event session itself --
 * this form collects only the one thing the booking adds: which venue.
 * The backend re-validates the coordinator's assignment and the event's
 * status (approved/planning) regardless of what this page shows.
 */
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiGet, apiPost } from '../../lib/api'
import AppNavBar from '../../components/AppNavBar.vue'
import { validateBookingForm } from '../../lib/venueBookings'

const route = useRoute()
const router = useRouter()

const event = ref(null)
const venues = ref([])
const loading = ref(true)
const submitting = ref(false)
const error = ref('')
const loadError = ref('')
const form = reactive({ venue_id: '' })

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [loadedEvent, loadedVenues] = await Promise.all([
      apiGet(`/events/${route.params.eventId}`),
      apiGet('/venues'),
    ])
    event.value = loadedEvent
    venues.value = loadedVenues
  } catch (requestError) {
    loadError.value = requestError.message
  } finally {
    loading.value = false
  }
}

async function submit() {
  error.value = ''
  if (!validateBookingForm(form)) {
    error.value = 'Choose a venue to request.'
    return
  }
  submitting.value = true
  try {
    await apiPost(`/events/${route.params.eventId}/venue-bookings`, { venue_id: form.venue_id })
    router.push({ name: 'event-details', params: { eventId: route.params.eventId } })
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <AppNavBar />
    <main class="content">
      <div class="container">
        <router-link :to="{ name: 'event-details', params: { eventId: route.params.eventId } }" class="back-link">
          &larr; Back to event
        </router-link>

        <p v-if="loading" class="message">Loading...</p>
        <p v-else-if="loadError" class="message error" role="alert">{{ loadError }}</p>

        <template v-else>
          <div class="page-heading">
            <h1 class="page-title">Request Venue Booking</h1>
            <span class="page-subtitle">{{ event.name }}</span>
          </div>

          <form class="card" novalidate @submit.prevent="submit">
            <h2 class="card-title">Choose a venue</h2>
            <label class="field">
              <span class="field-label">Venue</span>
              <select v-model="form.venue_id" class="input">
                <option value="" disabled>Select a venue</option>
                <option v-for="venue in venues" :key="venue.id" :value="venue.id">
                  {{ venue.name }} &middot; capacity {{ venue.capacity }}
                </option>
              </select>
            </label>

            <p v-if="error" class="message error" role="alert">{{ error }}</p>

            <div class="form-footer">
              <button type="submit" class="btn btn-primary" :disabled="submitting">
                {{ submitting ? 'Submitting...' : 'Submit Request' }}
              </button>
            </div>
          </form>
        </template>
      </div>
    </main>
  </div>
</template>

<style scoped src="../../styles/event-form.css"></style>
