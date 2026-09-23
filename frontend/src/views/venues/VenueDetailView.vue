<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { apiGet } from '../../lib/api'

const route = useRoute()
const venue = ref(null)
const loading = ref(true)
const error = ref('')

function formatList(value) {
  if (!value || value.length === 0) return 'None listed'
  return value.map((item) => item.replaceAll('_', ' ')).join(', ')
}

async function loadVenue() {
  loading.value = true
  error.value = ''
  try {
    venue.value = await apiGet(`/venues/${route.params.venueId}`)
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    loading.value = false
  }
}

onMounted(loadVenue)
</script>

<template>
  <main class="venue-details">
    <p><router-link to="/venues">&larr; Venues</router-link></p>
    <p v-if="loading">Loading venue...</p>
    <p v-else-if="error" class="error" role="alert">{{ error }}</p>
    <template v-else-if="venue">
      <header>
        <div>
          <p class="eyebrow">Venue</p>
          <h1>{{ venue.name }}</h1>
        </div>
        <strong class="status" :class="`status-${venue.status}`">{{ venue.status }}</strong>
      </header>

      <dl>
        <dt>Location</dt><dd>{{ venue.location }}</dd>
        <dt>Maximum capacity</dt><dd>{{ venue.capacity }}</dd>
        <dt>Supported room layouts</dt><dd>{{ formatList(venue.supported_layouts) }}</dd>
        <dt>Facilities</dt><dd>{{ formatList(venue.facilities) }}</dd>
        <dt>Accessibility provisions</dt><dd>{{ formatList(venue.accessibility_features) }}</dd>
      </dl>

      <p class="notice">
        Availability reflects a manually-set status for Sprint 1, not a live booking calendar --
        that's built separately (Venue Availability Calendar), once venue bookings exist.
      </p>
    </template>
  </main>
</template>

<style scoped>
.venue-details { max-width: 760px; margin: 2rem auto; padding: 0 1rem 3rem; }
header { display: flex; justify-content: space-between; gap: 1rem; align-items: start; }
.eyebrow { font-weight: 700; }
h1 { margin-top: .25rem; }
.status { padding: .35rem .6rem; background: #e2e8f0; border-radius: 4px; text-transform: capitalize; }
.status-available { background: #d1fae5; color: #067647; }
.status-occupied { background: #fee2e2; color: #b42318; }
.status-maintenance { background: #fef3c7; color: #92400e; }
dl { display: grid; grid-template-columns: 220px 1fr; gap: .75rem 1rem; margin-top: 1.5rem; }
dt { font-weight: 700; }
dd { margin: 0; text-transform: capitalize; }
.error { color: #b42318; }
.notice { margin-top: 2rem; padding: .75rem; background: #f1f5f9; font-size: .9rem; color: #475569; text-transform: none; }
@media (max-width: 560px) { dl { grid-template-columns: 1fr; } }
</style>
