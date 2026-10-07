<script setup>
/**
 * Venue Booking Request (Josiah, Sprint 2) -- the assigned coordinator
 * picks a venue and submits a booking request for this event session
 * (POST /events/<eventId>/venue-bookings).
 *
 * Also where Search Venues by Event Requirements (IS-12) and Flag
 * Unsuitable Venues for an Event (IS-13, both Nawaz, Sprint 2) live --
 * this is the one screen where a Coordinator is actually choosing a
 * venue for a specific event, so it's the natural place to shortlist
 * candidates by criteria (IS-12) and see a non-blocking suitability
 * check per candidate before submitting (IS-13), rather than building
 * either as a separate standalone page. Flagged in docs/open-questions.md
 * as a placement call, same as any other judgement call in this
 * codebase.
 *
 * IS-12 is a pure client-side filter (lib/venueSearch.js) over the same
 * GET /venues this page already fetched -- no new backend route, see
 * that module's own docstring for why. IS-13 is lib/venueSuitability.js's
 * checkSuitabilityForEvent -- a SEPARATE function from the one Josiah's
 * Booking Review screen uses, not a shared one; see that module's own
 * comment for why reusing checkSuitability itself would have been wrong.
 */
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiGet, apiPost } from '../../lib/api'
import AppNavBar from '../../components/AppNavBar.vue'
import { validateBookingForm } from '../../lib/venueBookings'
import { filterVenues, hasActiveCriteria } from '../../lib/venueSearch'
import { checkSuitabilityForEvent, isSuitableOverall } from '../../lib/venueSuitability'

const route = useRoute()
const router = useRouter()

const event = ref(null)
const venues = ref([])
const loading = ref(true)
const submitting = ref(false)
const error = ref('')
const loadError = ref('')
const form = reactive({ venue_id: '' })

// IS-12 search criteria. Kept as one reactive object (not several refs)
// so "clear criteria" is a single assignment, and so filterVenues can
// take it as-is -- see that function's own docstring on why an unset
// field imposes no constraint.
const criteria = reactive({
  minCapacity: null,
  location: '',
  roomLayout: '',
  accessibilityFeatures: [],
  facilities: [],
})

function clearCriteria() {
  criteria.minCapacity = null
  criteria.location = ''
  criteria.roomLayout = ''
  criteria.accessibilityFeatures = []
  criteria.facilities = []
}

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

// The checkbox option lists are derived from whatever the catalogue
// actually has -- not a hardcoded guess at what accessibility
// features/facilities exist -- same "don't invent a closed list the
// schema doesn't have" stance venues.facilities itself took in Sprint 1.
const accessibilityOptions = computed(() => [...new Set(venues.value.flatMap((v) => v.accessibility_features ?? []))].sort())
const facilityOptions = computed(() => [...new Set(venues.value.flatMap((v) => v.facilities ?? []))].sort())
const layoutOptions = computed(() => [...new Set(venues.value.flatMap((v) => v.supported_layouts ?? []))].sort())

const filteredVenues = computed(() => filterVenues(venues.value, criteria))
const showEmptyState = computed(() => hasActiveCriteria(criteria) && filteredVenues.value.length === 0)

function suitabilityFor(venue) {
  return checkSuitabilityForEvent(event.value, venue)
}
function overallSuitable(venue) {
  return isSuitableOverall(suitabilityFor(venue))
}

const selectedVenue = computed(() => venues.value.find((v) => v.id === form.venue_id) ?? null)
const selectedSuitability = computed(() => (selectedVenue.value ? suitabilityFor(selectedVenue.value) : []))

function selectVenue(venueId) {
  form.venue_id = venueId
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

          <section class="card" aria-labelledby="search-heading">
            <div class="search-header">
              <h2 id="search-heading" class="card-title">Search venues</h2>
              <button type="button" class="link-btn" @click="clearCriteria">Clear criteria</button>
            </div>

            <div class="filters-grid">
              <label class="field">
                <span class="field-label">Minimum capacity</span>
                <input v-model.number="criteria.minCapacity" type="number" min="0" class="input" placeholder="Any" />
              </label>
              <label class="field">
                <span class="field-label">Location contains</span>
                <input v-model="criteria.location" type="text" class="input" placeholder="e.g. Level 3" />
              </label>
              <label class="field">
                <span class="field-label">Room layout</span>
                <select v-model="criteria.roomLayout" class="input">
                  <option value="">Any</option>
                  <option v-for="layout in layoutOptions" :key="layout" :value="layout">{{ layout }}</option>
                </select>
              </label>
            </div>

            <div class="checkbox-group">
              <span class="field-label">Accessibility features</span>
              <label v-for="feature in accessibilityOptions" :key="feature" class="checkbox-label">
                <input v-model="criteria.accessibilityFeatures" type="checkbox" :value="feature" />
                {{ feature.replaceAll('_', ' ') }}
              </label>
            </div>

            <div class="checkbox-group">
              <span class="field-label">Facilities</span>
              <label v-for="facility in facilityOptions" :key="facility" class="checkbox-label">
                <input v-model="criteria.facilities" type="checkbox" :value="facility" />
                {{ facility.replaceAll('_', ' ') }}
              </label>
            </div>
          </section>

          <form class="card" novalidate @submit.prevent="submit">
            <h2 class="card-title">Choose a venue</h2>

            <p v-if="showEmptyState" class="message">No venues match your search criteria.</p>

            <div v-else class="venue-list">
              <button
                v-for="venue in filteredVenues"
                :key="venue.id"
                type="button"
                class="venue-card"
                :class="{ selected: form.venue_id === venue.id }"
                @click="selectVenue(venue.id)"
              >
                <div class="venue-card-header">
                  <span class="venue-name">{{ venue.name }}</span>
                  <span class="suitability-badge" :class="overallSuitable(venue) ? 'ok' : 'warn'">
                    {{ overallSuitable(venue) ? 'Appears suitable' : 'Flagged' }}
                  </span>
                </div>
                <span class="venue-meta">{{ venue.location }} &middot; capacity {{ venue.capacity }}</span>
                <span class="venue-tags">
                  <span v-for="layout in venue.supported_layouts" :key="layout" class="tag">{{ layout }}</span>
                  <span v-for="feature in venue.accessibility_features" :key="feature" class="tag tag-accessibility">
                    {{ feature.replaceAll('_', ' ') }}
                  </span>
                  <span v-for="facility in venue.facilities" :key="facility" class="tag tag-facility">
                    {{ facility.replaceAll('_', ' ') }}
                  </span>
                </span>
              </button>
            </div>

            <section v-if="selectedVenue" class="suitability-panel" aria-labelledby="suitability-heading">
              <h3 id="suitability-heading" class="suitability-heading">Suitability check -- {{ selectedVenue.name }}</h3>
              <p class="suitability-note">
                This is a report, not a block -- you can still request this venue even if something below is flagged.
              </p>
              <div v-for="check in selectedSuitability" :key="check.label" class="suitability-row">
                <span class="suitability-icon" :class="check.status">
                  {{ check.status === 'suitable' ? '✓' : check.status === 'unsuitable' ? '!' : '?' }}
                </span>
                <div>
                  <span class="suitability-label">{{ check.label }}</span>
                  <span class="suitability-detail">{{ check.detail }}</span>
                </div>
              </div>
            </section>

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
<style scoped>
.search-header { display: flex; align-items: center; justify-content: space-between; }
.link-btn {
  border: none; background: none; color: #1f5fae; font-size: 13px; font-weight: 600; cursor: pointer; padding: 0;
}
.filters-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-top: 12px; }
.checkbox-group { display: flex; flex-direction: column; gap: 6px; margin-top: 16px; }
.checkbox-label { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: #444444; margin-right: 14px; }

.venue-list { display: flex; flex-direction: column; gap: 10px; }
.venue-card {
  display: flex; flex-direction: column; gap: 6px; text-align: left; border: 1px solid #d8d8d8; border-radius: 6px;
  background: #ffffff; padding: 14px 16px; cursor: pointer; font-family: inherit;
}
.venue-card.selected { border-color: #1f5fae; box-shadow: 0 0 0 1px #1f5fae inset; }
.venue-card-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.venue-name { font-size: 14px; font-weight: 700; color: #1f1f1f; }
.venue-meta { font-size: 12px; color: #8a8a8a; }
.venue-tags { display: flex; flex-wrap: wrap; gap: 6px; }
.tag { font-size: 10px; font-weight: 600; background: #f0f0f0; color: #6a6a6a; border-radius: 10px; padding: 2px 8px; text-transform: capitalize; }
.tag-accessibility { background: #e4eefb; color: #1f5fae; }
.tag-facility { background: #eaf5ec; color: #2f6b3f; }

.suitability-badge { font-size: 10px; font-weight: 700; border-radius: 10px; padding: 3px 10px; white-space: nowrap; }
.suitability-badge.ok { background: #eaf5ec; color: #2f6b3f; }
.suitability-badge.warn { background: #fdf6ec; color: #8a5a12; }

.suitability-panel { margin-top: 20px; padding-top: 16px; border-top: 1px dashed #dcdcdc; }
.suitability-heading { margin: 0 0 4px; font-size: 14px; font-weight: 700; color: #1f1f1f; }
.suitability-note { margin: 0 0 10px; font-size: 12px; color: #8a8a8a; }
.suitability-row { display: flex; align-items: flex-start; gap: 10px; padding: 8px 0; }
.suitability-icon {
  flex: 0 0 auto; width: 20px; height: 20px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
  font-size: 12px; font-weight: 700;
}
.suitability-icon.suitable { background: #eaf5ec; color: #2f6b3f; }
.suitability-icon.unsuitable { background: #fdf6ec; color: #8a5a12; }
.suitability-icon.not_assessed { background: #f0f0f0; color: #8a8a8a; }
.suitability-label { display: block; font-size: 13px; font-weight: 600; color: #2a2a2a; }
.suitability-detail { display: block; font-size: 12px; color: #8a8a8a; }
</style>
