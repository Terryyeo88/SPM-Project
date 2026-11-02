<script setup>
/**
 * Block Venue (Josiah, Sprint 3, Week 7 #2) -- Venue Staff mark a venue
 * blocked for a period, with a mandatory reason. Reached via a button on
 * VenueDetailView.vue, the same reachability pattern
 * RequestVenueBookingView.vue uses from EventDetailsView.vue -- not nav-
 * linked, see lib/roles.js.
 *
 * Any already-CONFIRMED bookings overlapping the new block are released
 * server-side (app.venues.block_service.create_venue_block) -- the
 * response's released_bookings is shown here so "affected bookings
 * identified, coordinator informed" (the story's own AC) is visibly true,
 * not just a side effect the coordinator has to discover elsewhere.
 */
import { onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiGet } from '../../lib/api'
import AppNavBar from '../../components/AppNavBar.vue'
import { createVenueBlock, VENUE_BLOCK_REASONS, blockReasonLabel } from '../../lib/venues'

const route = useRoute()
const router = useRouter()

const venue = ref(null)
const loading = ref(true)
const loadError = ref('')

const form = reactive({ reason: '', note: '', block_start: '', block_end: '' })
const submitting = ref(false)
const error = ref('')
const releasedBookings = ref(null)

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    venue.value = await apiGet(`/venues/${route.params.venueId}`)
  } catch (requestError) {
    loadError.value = requestError.message
  } finally {
    loading.value = false
  }
}

async function submit() {
  error.value = ''
  if (!form.reason) {
    error.value = 'Choose a reason for blocking this venue.'
    return
  }
  if (!form.block_start || !form.block_end) {
    error.value = 'Give both a start and an end for the blocked period.'
    return
  }
  submitting.value = true
  try {
    const result = await createVenueBlock(route.params.venueId, {
      reason: form.reason,
      note: form.note.trim() || undefined,
      block_start: new Date(form.block_start).toISOString(),
      block_end: new Date(form.block_end).toISOString(),
    })
    releasedBookings.value = result.released_bookings ?? []
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    submitting.value = false
  }
}

function backToVenue() {
  router.push({ name: 'venue-details', params: { venueId: route.params.venueId } })
}

onMounted(load)
</script>

<template>
  <div class="page">
    <AppNavBar />
    <main class="content">
      <div class="container">
        <router-link :to="{ name: 'venue-details', params: { venueId: route.params.venueId } }" class="back-link">
          &larr; Back to venue
        </router-link>

        <p v-if="loading" class="message">Loading venue...</p>
        <p v-else-if="loadError" class="message error" role="alert">{{ loadError }}</p>

        <template v-else>
          <div class="page-heading">
            <h1 class="page-title">Block this venue</h1>
            <span class="page-subtitle">{{ venue.name }}</span>
          </div>

          <template v-if="releasedBookings === null">
            <form class="card" novalidate @submit.prevent="submit">
              <p class="message">
                Blocking this venue does not cancel any event using it. Any confirmed booking that overlaps the
                blocked period will be released so the coordinator can search for a replacement venue.
              </p>

              <label class="field">
                <span class="field-label">Reason</span>
                <select v-model="form.reason" class="input" required>
                  <option value="" disabled>Select a reason</option>
                  <option v-for="reason in VENUE_BLOCK_REASONS" :key="reason" :value="reason">
                    {{ blockReasonLabel(reason) }}
                  </option>
                </select>
              </label>

              <label class="field">
                <span class="field-label">Note (optional)</span>
                <textarea v-model="form.note" class="input" rows="3" placeholder="Any extra detail for the coordinator" />
              </label>

              <label class="field">
                <span class="field-label">Blocked from</span>
                <input v-model="form.block_start" type="datetime-local" class="input" required />
              </label>
              <label class="field">
                <span class="field-label">Blocked until</span>
                <input v-model="form.block_end" type="datetime-local" class="input" required />
              </label>

              <p v-if="error" class="message error" role="alert">{{ error }}</p>

              <div class="form-footer">
                <button type="submit" class="btn btn-primary" :disabled="submitting">
                  {{ submitting ? 'Blocking...' : 'Block Venue' }}
                </button>
              </div>
            </form>
          </template>

          <template v-else>
            <section class="card">
              <h2 class="card-title">Venue blocked</h2>
              <p v-if="releasedBookings.length === 0" class="message">
                No confirmed bookings overlapped the blocked period -- nothing else to do.
              </p>
              <template v-else>
                <p class="message">
                  {{ releasedBookings.length }} confirmed booking(s) were released. The affected coordinators can
                  search for a replacement venue from each event's page.
                </p>
                <ul class="released-list">
                  <li v-for="released in releasedBookings" :key="released.booking_id">
                    <router-link :to="{ name: 'event-details', params: { eventId: released.event_id } }">
                      View affected event &rarr;
                    </router-link>
                  </li>
                </ul>
              </template>
              <div class="form-footer">
                <button type="button" class="btn btn-primary" @click="backToVenue">Back to venue</button>
              </div>
            </section>
          </template>
        </template>
      </div>
    </main>
  </div>
</template>

<style scoped src="../../styles/event-form.css"></style>
<style scoped>
.released-list { display: flex; flex-direction: column; gap: 6px; margin: 10px 0; padding: 0; list-style: none; }
</style>
