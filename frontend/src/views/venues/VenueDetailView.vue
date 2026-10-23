<script setup>
/**
 * One venue's details (View Venue Catalogue). IS-61: Venue Staff also edit
 * it (VenueFormView.vue) or delete it from here. Deleting releases the
 * bookings of ongoing events that booked it; their coordinators are alerted
 * on the event page (VenueRemovedAlert.vue). A deleted venue is still shown
 * when opened by link (an old booking's venue), marked as deleted, without
 * the staff actions.
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
const canManage = computed(() => isVenueStaff.value && venue.value && !venue.value.deleted_at)
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
      <p v-if="venue.deleted_at" class="deleted-banner" role="status" data-test="venue-deleted">
        This venue has been deleted from the catalogue. It can no longer be booked.
      </p>
      <header>
        <div>
          <p class="eyebrow">Venue</p>
          <h1>{{ venue.name }}</h1>
        </div>
        <strong class="status" :class="`status-${venue.status}`">{{ venue.status }}</strong>
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
          It will be removed from the venue catalogue and can no longer be booked. Ongoing events that have
          booked it will lose their booking, and their coordinators will be asked to book another venue.
          Confirmed events go back to planning. Completed, cancelled and rejected events keep their record.
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
.saved { padding: .6rem .75rem; background: #eaf5ec; color: #2f6b3f; border-radius: 4px; }
.deleted-banner { padding: .75rem; background: #f5e6e6; color: #a33f3f; border-radius: 4px; font-weight: 600; }
.staff-actions { display: flex; gap: .6rem; flex-wrap: wrap; margin-top: 1rem; }
.delete-panel {
  margin-top: 1rem; padding: .9rem 1rem; background: #fbf1f1; border: 1px solid #d9a3a3; border-radius: 6px;
}
.delete-panel p { margin: 0 0 .5rem; }
.panel-actions { display: flex; gap: .6rem; flex-wrap: wrap; }
.btn {
  min-height: 36px; padding: 0 14px; border-radius: 4px; font: inherit; font-size: .85rem; font-weight: 700;
  cursor: pointer; display: inline-flex; align-items: center; text-decoration: none; background: #fff;
}
.btn:disabled { opacity: .6; cursor: not-allowed; }
.neutral { border: 1px solid #b8b8b8; color: #444; }
.danger { border: 1px solid #a33f3f; color: #a33f3f; }
.danger-solid { border: none; background: #a33f3f; color: #fff; }
@media (max-width: 560px) { dl { grid-template-columns: 1fr; } }
</style>
