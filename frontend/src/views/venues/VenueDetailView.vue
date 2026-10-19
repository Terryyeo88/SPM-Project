<script setup>
/**
 * Venue Staff settings editing (Josiah, Sprint 3, Week 7 #1) lives here
 * as a small inline section -- not a separate page -- since the page
 * already identifies the one venue being edited and doesn't currently
 * even display these three fields. "Block this venue" (Week 7 #2) is a
 * link to its own focused form (BlockVenueView.vue), the same
 * reachability pattern RequestVenueBookingView.vue already uses from
 * EventDetailsView.vue.
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { apiGet } from '../../lib/api'
import { useAuthStore } from '../../stores/auth'
import { updateVenueSettings } from '../../lib/venues'
import AppNavBar from '../../components/AppNavBar.vue'

const route = useRoute()
const auth = useAuthStore()
const venue = ref(null)
const loading = ref(true)
const error = ref('')

const isVenueStaff = computed(() => auth.roles.includes('venue_staff'))
const editing = ref(false)
const settingsForm = reactive({ setup_minutes: null, turnaround_minutes: null, tentative_hold_minutes: null })
const saving = ref(false)
const saveError = ref('')
const saveSuccess = ref('')

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

function startEditing() {
  saveError.value = ''
  saveSuccess.value = ''
  settingsForm.setup_minutes = venue.value.setup_minutes
  settingsForm.turnaround_minutes = venue.value.turnaround_minutes
  settingsForm.tentative_hold_minutes = venue.value.tentative_hold_minutes
  editing.value = true
}

function cancelEditing() {
  editing.value = false
}

async function saveSettings() {
  saveError.value = ''
  saveSuccess.value = ''
  saving.value = true
  try {
    venue.value = await updateVenueSettings(venue.value.id, {
      setup_minutes: settingsForm.setup_minutes,
      turnaround_minutes: settingsForm.turnaround_minutes,
      tentative_hold_minutes: settingsForm.tentative_hold_minutes,
    })
    editing.value = false
    saveSuccess.value = 'Venue settings updated. Existing bookings keep their original values -- only new bookings use the new settings.'
  } catch (requestError) {
    saveError.value = requestError.message
  } finally {
    saving.value = false
  }
}

onMounted(loadVenue)
</script>

<template>
  <div class="app-page">
    <AppNavBar />
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
        <dt>Setup time</dt><dd>{{ venue.setup_minutes }} minutes</dd>
        <dt>Turnaround time</dt><dd>{{ venue.turnaround_minutes }} minutes</dd>
        <dt>Tentative hold duration</dt><dd>{{ venue.tentative_hold_minutes }} minutes</dd>
      </dl>

      <div class="links">
        <router-link :to="`/venues/${venue.id}/calendar`" class="calendar-link">
          View availability calendar &rarr;
        </router-link>
        <router-link v-if="isVenueStaff" :to="{ name: 'block-venue', params: { venueId: venue.id } }" class="block-link">
          Block this venue &rarr;
        </router-link>
      </div>
      <p class="notice">
        The status badge above is a manually-set Sprint 1 flag, kept for a quick at-a-glance read. For a real
        day/week/month view of bookings and blocked periods, see the availability calendar.
      </p>

      <section v-if="isVenueStaff" class="settings-section">
        <div class="settings-header">
          <h2>Venue Settings</h2>
          <button v-if="!editing" type="button" class="edit-btn" @click="startEditing">Edit</button>
        </div>
        <p class="notice settings-notice">
          Editing these only affects NEW bookings -- existing bookings keep the values they were made with.
        </p>

        <form v-if="editing" class="settings-form" novalidate @submit.prevent="saveSettings">
          <label>
            Setup time (minutes)
            <input v-model.number="settingsForm.setup_minutes" type="number" min="1" required />
          </label>
          <label>
            Turnaround time (minutes)
            <input v-model.number="settingsForm.turnaround_minutes" type="number" min="1" required />
          </label>
          <label>
            Tentative hold duration (minutes)
            <input v-model.number="settingsForm.tentative_hold_minutes" type="number" min="1" required />
          </label>
          <div class="settings-actions">
            <button type="submit" :disabled="saving">{{ saving ? 'Saving...' : 'Save' }}</button>
            <button type="button" :disabled="saving" @click="cancelEditing">Cancel</button>
          </div>
          <p v-if="saveError" class="error" role="alert">{{ saveError }}</p>
        </form>
        <p v-else-if="saveSuccess" class="success" role="status">{{ saveSuccess }}</p>
      </section>
    </template>
  </main>
  </div>
</template>

<style scoped>
.app-page { min-height: 100vh; background: #ffffff; }
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
.success { color: #067647; }
.notice { margin-top: .75rem; padding: .75rem; background: #f1f5f9; font-size: .9rem; color: #475569; text-transform: none; }
.links { display: flex; flex-wrap: wrap; gap: 1.5rem; margin-top: 2rem; }
.calendar-link, .block-link { display: inline-block; font-weight: 700; text-decoration: none; }
.calendar-link { color: #1f5fae; }
.block-link { color: #b42318; }
.calendar-link:hover, .block-link:hover { text-decoration: underline; }

.settings-section { margin-top: 2rem; padding-top: 1.5rem; border-top: 1px solid #e2e8f0; }
.settings-header { display: flex; justify-content: space-between; align-items: center; gap: 1rem; }
.settings-header h2 { margin: 0; font-size: 1.1rem; }
.settings-notice { margin-top: .5rem; }
.edit-btn, .settings-actions button { font: inherit; padding: .4rem .9rem; border: 1px solid #1f5fae; border-radius: 4px; background: #fff; color: #1f5fae; cursor: pointer; }
.settings-actions button[type="submit"] { background: #1f5fae; color: #fff; }
.settings-actions button:disabled { opacity: .6; cursor: not-allowed; }
.settings-form { display: flex; flex-direction: column; gap: .9rem; margin-top: 1rem; max-width: 360px; }
.settings-form label { display: flex; flex-direction: column; gap: .3rem; font-weight: 600; font-size: .9rem; }
.settings-form input { font: inherit; padding: .4rem .6rem; border: 1px solid #cbd5e1; border-radius: 4px; }
.settings-actions { display: flex; gap: .75rem; margin-top: .25rem; }
@media (max-width: 560px) { dl { grid-template-columns: 1fr; } }
</style>
