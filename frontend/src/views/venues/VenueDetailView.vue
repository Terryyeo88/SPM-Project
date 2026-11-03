<script setup>
/**
 * One venue's details (View Venue Catalogue). IS-61: Venue Staff also edit
 * it (VenueFormView.vue) or delete it from here. Deleting removes the
 * venue's record; every booking of it, completed and cancelled events'
 * included, keeps the venue's name. It also releases the bookings of
 * ongoing events that booked it; their coordinators are alerted on the
 * event page (VenueRemovedAlert.vue).
 *
 * "Block this venue" (Sprint 3, Josiah, Week 7 #2) is a link to its own
 * focused form (BlockVenueView.vue), the same reachability pattern
 * RequestVenueBookingView.vue already uses from EventDetailsView.vue --
 * not folded into the Edit venue form above, since blocking isn't an edit
 * to the venue's own record. tentative_hold_minutes (Week 7 #1) IS part
 * of the venue's own record, so it's edited through VenueFormView.vue
 * alongside setup_minutes/turnaround_minutes, not a separate form here --
 * see docs/design-decisions.md for why this merged that way.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiGet } from '../../lib/api'
import { ROLES, hasAnyRole } from '../../lib/roles'
import { deleteOutcomeMessage, deleteVenue, formatOperatingHours } from '../../lib/venueCatalogue'
import { useAuthStore } from '../../stores/auth'
import AppNavBar from '../../components/AppNavBar.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const venue = ref(null)
const loading = ref(true)
const error = ref('')

const isVenueStaff = computed(() => hasAnyRole(auth.roles, [ROLES.VENUE_STAFF]))
const canManage = computed(() => isVenueStaff.value && Boolean(venue.value))
const savedMessage = computed(() => {
  if (route.query.saved === 'created') return 'Venue added to the catalogue.'
  if (route.query.saved === 'updated') return 'Venue details saved.'
  return ''
})

const confirmingDelete = ref(false)
const deleting = ref(false)
const deleteError = ref('')

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

async function confirmDelete() {
  deleting.value = true
  deleteError.value = ''
  try {
    const result = await deleteVenue(venue.value.id)
    router.push({ name: 'venues', query: { deleted: deleteOutcomeMessage(result) } })
  } catch (requestError) {
    deleteError.value = requestError.message
  } finally {
    deleting.value = false
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
      <p v-if="savedMessage" class="saved" role="status">{{ savedMessage }}</p>
      <header>
        <div>
          <p class="eyebrow">Venue</p>
          <h1>{{ venue.name }}</h1>
        </div>
        <strong class="status cs-pill" :class="`status-${venue.status} cs-status-${venue.status}`">{{ venue.status }}</strong>
      </header>

      <div v-if="canManage" class="staff-actions" data-test="staff-actions">
        <router-link :to="{ name: 'venue-edit', params: { venueId: venue.id } }" class="btn neutral">
          Edit venue
        </router-link>
        <button v-if="!confirmingDelete" type="button" class="btn danger" @click="confirmingDelete = true">
          Delete venue
        </button>
      </div>

      <div v-if="canManage && confirmingDelete" class="delete-panel" data-test="delete-panel">
        <p><strong>Delete {{ venue.name }}?</strong></p>
        <p>
          Its record will be removed from the venue catalogue for good, and this can't be undone. Ongoing events
          that have booked it will lose their booking, and their coordinators will be asked to book another venue.
          Confirmed events go back to planning. Past bookings, including completed and cancelled events', keep the
          venue's name.
        </p>
        <div class="panel-actions">
          <button type="button" class="btn danger-solid" :disabled="deleting" @click="confirmDelete">
            {{ deleting ? 'Deleting...' : 'Delete venue' }}
          </button>
          <button type="button" class="btn neutral" :disabled="deleting" @click="confirmingDelete = false">
            Keep venue
          </button>
        </div>
        <p v-if="deleteError" class="error" role="alert">{{ deleteError }}</p>
      </div>

      <dl>
        <dt>Location</dt><dd>{{ venue.location }}</dd>
        <dt>Maximum capacity</dt><dd>{{ venue.capacity }}</dd>
        <dt>Supported room layouts</dt><dd>{{ formatList(venue.supported_layouts) }}</dd>
        <dt>Facilities</dt><dd>{{ formatList(venue.facilities) }}</dd>
        <dt>Accessibility provisions</dt><dd>{{ formatList(venue.accessibility_features) }}</dd>
        <dt>Operating hours</dt><dd>{{ formatOperatingHours(venue.operating_hours_start, venue.operating_hours_end) }}</dd>
        <dt>Setup / turnaround</dt><dd>{{ venue.setup_minutes }} / {{ venue.turnaround_minutes }} minutes</dd>
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
    </template>
  </main>
  </div>
</template>

<style scoped>
.app-page { min-height: 100vh; background: var(--cs-paper); }
.venue-details { max-width: 760px; margin: var(--cs-space-6) auto; padding: 0 var(--cs-space-4) var(--cs-space-7); }
header { display: flex; justify-content: space-between; gap: var(--cs-space-4); align-items: start; }
.eyebrow { font-weight: 700; color: var(--cs-ink-soft); }
h1 { margin-top: .25rem; font-family: var(--cs-font-display); color: var(--cs-ink); }
dl { display: grid; grid-template-columns: 220px 1fr; gap: .75rem 1rem; margin-top: var(--cs-space-5); }
dt { font-weight: 700; color: var(--cs-ink); }
dd { margin: 0; text-transform: capitalize; color: var(--cs-ink); }
.error { color: var(--cs-occupied); }
.success { color: var(--cs-available); }
.notice { margin-top: var(--cs-space-3); padding: var(--cs-space-3); background: var(--cs-neutral-tint); font-size: .9rem; color: var(--cs-ink-soft); text-transform: none; border-radius: var(--cs-radius-sm); }
.links { display: flex; flex-wrap: wrap; gap: var(--cs-space-5); margin-top: var(--cs-space-6); }
.calendar-link, .block-link { display: inline-block; font-weight: 700; text-decoration: none; }
.calendar-link { color: var(--cs-signal); }
.block-link { color: var(--cs-occupied); }
.calendar-link:hover, .block-link:hover { text-decoration: underline; }
.saved { padding: var(--cs-space-2) var(--cs-space-3); background: var(--cs-available-tint); color: var(--cs-available); border-radius: var(--cs-radius-sm); }
.staff-actions { display: flex; gap: var(--cs-space-2); flex-wrap: wrap; margin-top: var(--cs-space-4); }
.delete-panel {
  margin-top: var(--cs-space-4); padding: var(--cs-space-3) var(--cs-space-4); background: var(--cs-occupied-tint); border: 1px solid var(--cs-occupied); border-radius: var(--cs-radius-md);
}
.delete-panel p { margin: 0 0 var(--cs-space-2); }
.panel-actions { display: flex; gap: var(--cs-space-2); flex-wrap: wrap; }
.btn {
  min-height: 36px; padding: 0 var(--cs-space-4); border-radius: var(--cs-radius-sm); font: inherit; font-size: .85rem; font-weight: 700;
  cursor: pointer; display: inline-flex; align-items: center; text-decoration: none; background: var(--cs-surface);
}
.btn:disabled { opacity: .6; cursor: not-allowed; }
.neutral { border: 1px solid var(--cs-line-strong); color: var(--cs-ink); }
.danger { border: 1px solid var(--cs-occupied); color: var(--cs-occupied); }
.danger-solid { border: none; background: var(--cs-occupied); color: #fff; }
@media (max-width: 560px) { dl { grid-template-columns: 1fr; } }
</style>
