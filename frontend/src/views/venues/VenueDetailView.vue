<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { apiGet } from '../../lib/api'
import { ROLES, hasAnyRole } from '../../lib/roles'
import { listAllRoomLayouts, setVenueRoomLayouts, venueLayoutChoices } from '../../lib/roomLayouts'
import { useAuthStore } from '../../stores/auth'
import AppNavBar from '../../components/AppNavBar.vue'

const route = useRoute()
const auth = useAuthStore()
const venue = ref(null)
const loading = ref(true)
const error = ref('')

// Venue Staff set which room layouts this venue supports (venue_room_layouts).
const canEditLayouts = computed(() => hasAnyRole(auth.roles, [ROLES.VENUE_STAFF]))
const editingLayouts = ref(false)
const layoutChoices = ref([])
const selectedLayoutIds = ref([])
const layoutsError = ref('')
const savingLayouts = ref(false)

// The venue's layouts for display, marking any that have been deleted
// (a venue may keep a soft-deleted layout it already listed).
const layoutSummary = computed(() => {
  const layouts = venue.value?.supported_room_layouts ?? []
  if (layouts.length === 0) return 'None listed'
  return layouts.map((layout) => (layout.is_active ? layout.name : `${layout.name} (deleted)`)).join(', ')
})

async function startEditingLayouts() {
  layoutsError.value = ''
  try {
    const all = await listAllRoomLayouts()
    layoutChoices.value = venueLayoutChoices(all, venue.value.supported_room_layouts)
    selectedLayoutIds.value = (venue.value.supported_room_layouts ?? []).map((layout) => layout.room_layout_id)
    editingLayouts.value = true
  } catch (requestError) {
    layoutsError.value = requestError.message
  }
}

async function saveLayouts() {
  savingLayouts.value = true
  layoutsError.value = ''
  try {
    venue.value = await setVenueRoomLayouts(venue.value.id, selectedLayoutIds.value)
    editingLayouts.value = false
  } catch (requestError) {
    layoutsError.value = requestError.message
  } finally {
    savingLayouts.value = false
  }
}

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
        <dt>Supported room layouts</dt>
        <dd>
          <template v-if="!editingLayouts">
            <span data-test="layout-summary">{{ layoutSummary }}</span>
            <button v-if="canEditLayouts" type="button" class="link-button" @click="startEditingLayouts">Edit layouts</button>
          </template>
          <form v-else class="layout-editor" @submit.prevent="saveLayouts">
            <p v-if="layoutChoices.length === 0" class="hint">No room layouts exist yet. Add some on the Room Layouts page.</p>
            <label v-for="choice in layoutChoices" :key="choice.room_layout_id" class="layout-choice">
              <input v-model="selectedLayoutIds" type="checkbox" :value="choice.room_layout_id" />
              {{ choice.name }}<span v-if="choice.retired" class="hint"> (deleted -- can be kept, not re-added)</span>
            </label>
            <div class="editor-actions">
              <button type="submit" class="save-button" :disabled="savingLayouts">Save layouts</button>
              <button type="button" class="link-button" :disabled="savingLayouts" @click="editingLayouts = false">Cancel</button>
            </div>
          </form>
          <p v-if="layoutsError" class="error" role="alert">{{ layoutsError }}</p>
        </dd>
        <dt>Facilities</dt><dd>{{ formatList(venue.facilities) }}</dd>
        <dt>Accessibility provisions</dt><dd>{{ formatList(venue.accessibility_features) }}</dd>
      </dl>

      <router-link :to="`/venues/${venue.id}/calendar`" class="calendar-link">
        View availability calendar &rarr;
      </router-link>
      <p class="notice">
        The status badge above is a manually-set Sprint 1 flag, kept for a quick at-a-glance read. For a real
        day/week/month view of bookings and blocked periods, see the availability calendar.
      </p>
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
.notice { margin-top: .75rem; padding: .75rem; background: #f1f5f9; font-size: .9rem; color: #475569; text-transform: none; }
.calendar-link { display: inline-block; margin-top: 2rem; font-weight: 700; color: #1f5fae; text-decoration: none; }
.calendar-link:hover { text-decoration: underline; }
.link-button { margin-left: .75rem; padding: 0; border: none; background: none; color: #1f5fae; font: inherit; font-weight: 700; cursor: pointer; text-transform: none; }
.link-button:hover { text-decoration: underline; }
.layout-editor { display: flex; flex-direction: column; gap: .5rem; }
.layout-choice { display: flex; align-items: center; gap: .5rem; }
.hint { color: #64748b; font-size: .9rem; text-transform: none; }
.editor-actions { display: flex; align-items: center; gap: .25rem; margin-top: .25rem; }
.save-button { padding: .45rem .9rem; border: none; border-radius: 4px; background: #444444; color: #ffffff; font: inherit; font-weight: 600; cursor: pointer; }
.save-button:disabled { opacity: .55; cursor: not-allowed; }
@media (max-width: 560px) { dl { grid-template-columns: 1fr; } }
</style>
