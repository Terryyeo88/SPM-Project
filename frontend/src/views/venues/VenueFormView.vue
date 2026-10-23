<script setup>
/**
 * IS-61 CRUD in Venue Catalogue: Venue Staff add a venue (/venues/new, AC1)
 * or edit one's details (/venues/:venueId/edit, AC2). Venue Staff only
 * (ROUTE_ACCESS; the backend checks venue.create / venue.edit).
 *
 * An edit sends only the fields that changed (lib/venueCatalogue.js::
 * changedFields). Bookings already made keep the setup/turnaround minutes
 * they were made with -- a changed buffer applies to new bookings only.
 *
 * No operating hours here: nothing but the venue calendar's note reads them,
 * so a new venue has no set hours and an edit leaves existing ones alone.
 *
 * No status either: a new venue is always "available" (lib/venueCatalogue.js
 * sends it), and an edit leaves the venue's status as it is.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppNavBar from '../../components/AppNavBar.vue'
import { apiGet } from '../../lib/api'
import { fetchRoomLayouts } from '../../lib/roomLayouts'
import {
  ACCESSIBILITY_FEATURE_OPTIONS,
  FACILITY_OPTIONS,
  MIN_BUFFER_MINUTES,
  changedFields,
  createVenue,
  emptyVenueForm,
  layoutOptions,
  newVenuePayload,
  updateVenue,
  validateVenueForm,
  venueToForm,
} from '../../lib/venueCatalogue'

const route = useRoute()
const router = useRouter()

const venueId = computed(() => route.params.venueId ?? null)
const isEdit = computed(() => Boolean(venueId.value))

const venue = ref(null)
const form = ref(emptyVenueForm())
const activeLayouts = ref([])
const loading = ref(true)
const loadError = ref('')
const saveError = ref('')
const saving = ref(false)

const layouts = computed(() => layoutOptions(activeLayouts.value, venue.value?.supported_layouts ?? []))

// Checked live as the form changes. A field's error is shown once Venue
// Staff have left that field (blur), and Save stays disabled until every
// field is valid -- so a mistake shows up where it was made, not only on save.
const errors = computed(() => validateVenueForm(form.value))
const touched = ref({})
const isValid = computed(() => Object.keys(errors.value).length === 0)

function touch(field) {
  touched.value = { ...touched.value, [field]: true }
}

function shownError(field) {
  return touched.value[field] ? errors.value[field] : ''
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [layoutNames, existing] = await Promise.all([
      fetchRoomLayouts(),
      isEdit.value ? apiGet(`/venues/${venueId.value}`) : Promise.resolve(null),
    ])
    activeLayouts.value = layoutNames
    if (existing?.deleted_at) {
      loadError.value = 'This venue has been deleted from the catalogue, so it can no longer be edited.'
      return
    }
    venue.value = existing
    form.value = existing ? venueToForm(existing) : emptyVenueForm()
    // An existing venue that already breaks a rule (e.g. no layouts) shows
    // why straight away, rather than leaving Save disabled with no reason.
    touched.value = existing ? Object.fromEntries(Object.keys(errors.value).map((field) => [field, true])) : {}
  } catch (requestError) {
    loadError.value = requestError.message
  } finally {
    loading.value = false
  }
}

async function save() {
  saveError.value = ''
  if (!isValid.value) {
    // Save is disabled while invalid; this only guards a submit some other way.
    touched.value = Object.fromEntries(Object.keys(errors.value).map((field) => [field, true]))
    return
  }

  const body = isEdit.value ? changedFields(venue.value, form.value) : newVenuePayload(form.value)
  if (isEdit.value && !Object.keys(body).length) {
    router.push({ name: 'venue-details', params: { venueId: venueId.value } })
    return
  }
  saving.value = true
  try {
    const saved = isEdit.value ? await updateVenue(venueId.value, body) : await createVenue(body)
    router.push({
      name: 'venue-details',
      params: { venueId: saved.id },
      query: { saved: isEdit.value ? 'updated' : 'created' },
    })
  } catch (requestError) {
    saveError.value = requestError.message
  } finally {
    saving.value = false
  }
}

// Only once focus leaves the whole group, not when it moves between boxes.
function onLayoutsFocusOut(event) {
  if (!event.currentTarget.contains(event.relatedTarget)) touch('supported_layouts')
}

function cancelLink() {
  return isEdit.value ? { name: 'venue-details', params: { venueId: venueId.value } } : { name: 'venues' }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <AppNavBar />
    <main class="content">
      <div class="container">
        <router-link :to="cancelLink()" class="back-link">&larr; {{ isEdit ? 'Back to venue' : 'Venues' }}</router-link>
        <h1 class="title">{{ isEdit ? 'Edit venue' : 'Add a venue' }}</h1>

        <p v-if="loading" class="message">Loading...</p>
        <p v-else-if="loadError" class="message error" role="alert">{{ loadError }}</p>

        <form v-else class="card" novalidate @submit.prevent="save">
          <!-- Only section headings, the page title and the main button are
               bold; field labels and options stay regular weight. -->
          <section class="section">
            <h2 class="section-title">Basic details</h2>

            <div class="field">
              <label for="venue-name">Name <span class="required" aria-hidden="true">*</span></label>
              <input id="venue-name" v-model="form.name" type="text" maxlength="200"
                :aria-invalid="Boolean(shownError('name'))" @blur="touch('name')" />
              <p v-if="shownError('name')" class="field-error" data-error="name">{{ shownError('name') }}</p>
            </div>

            <div class="field">
              <label for="venue-location">Location <span class="required" aria-hidden="true">*</span></label>
              <input id="venue-location" v-model="form.location" type="text" placeholder="e.g. Main Building, Level 3"
                :aria-invalid="Boolean(shownError('location'))" @blur="touch('location')" />
              <p v-if="shownError('location')" class="field-error" data-error="location">{{ shownError('location') }}</p>
            </div>

            <div class="row">
              <div class="field">
                <label for="venue-capacity">Maximum capacity <span class="required" aria-hidden="true">*</span></label>
                <input id="venue-capacity" v-model="form.capacity" type="number" min="1" step="1"
                  :aria-invalid="Boolean(shownError('capacity'))" @blur="touch('capacity')" />
                <p v-if="shownError('capacity')" class="field-error" data-error="capacity">{{ shownError('capacity') }}</p>
              </div>
            </div>
          </section>

          <section class="section">
            <h2 class="section-title">What the venue offers</h2>

            <!-- focusout: leaving the whole group (not each checkbox) counts as leaving the field. -->
            <fieldset class="field" data-field="supported_layouts" @focusout="onLayoutsFocusOut">
              <legend>Supported room layouts <span class="required" aria-hidden="true">*</span></legend>
              <p v-if="!layouts.length" class="hint">No room layouts yet -- add them under Room Layouts.</p>
              <p v-if="shownError('supported_layouts')" class="field-error" data-error="supported_layouts">
                {{ shownError('supported_layouts') }}
              </p>
              <div class="options">
                <label v-for="option in layouts" :key="option.value" class="check">
                  <input v-model="form.supported_layouts" type="checkbox" :value="option.value" />
                  {{ option.label }}
                </label>
              </div>
            </fieldset>

            <fieldset class="field">
              <legend>Facilities</legend>
              <div class="options">
                <label v-for="option in FACILITY_OPTIONS" :key="option.value" class="check">
                  <input v-model="form.facilities" type="checkbox" :value="option.value" />
                  {{ option.label }}
                </label>
              </div>
            </fieldset>

            <fieldset class="field">
              <legend>Accessibility provisions</legend>
              <div class="options">
                <label v-for="option in ACCESSIBILITY_FEATURE_OPTIONS" :key="option.value" class="check">
                  <input v-model="form.accessibility_features" type="checkbox" :value="option.value" />
                  {{ option.label }}
                </label>
              </div>
            </fieldset>
          </section>

          <section class="section">
            <h2 class="section-title">Booking buffers</h2>

            <div class="row">
              <div class="field">
                <label for="venue-setup">Setup time (minutes) <span class="required" aria-hidden="true">*</span></label>
                <input id="venue-setup" v-model="form.setup_minutes" type="number" :min="MIN_BUFFER_MINUTES" step="1"
                  :aria-invalid="Boolean(shownError('setup_minutes'))" @blur="touch('setup_minutes')" />
                <p v-if="shownError('setup_minutes')" class="field-error" data-error="setup_minutes">
                  {{ shownError('setup_minutes') }}
                </p>
              </div>
              <div class="field">
                <label for="venue-turnaround">Turnaround time (minutes) <span class="required" aria-hidden="true">*</span></label>
                <input id="venue-turnaround" v-model="form.turnaround_minutes" type="number" :min="MIN_BUFFER_MINUTES" step="1"
                  :aria-invalid="Boolean(shownError('turnaround_minutes'))" @blur="touch('turnaround_minutes')" />
                <p v-if="shownError('turnaround_minutes')" class="field-error" data-error="turnaround_minutes">
                  {{ shownError('turnaround_minutes') }}
                </p>
              </div>
            </div>
            <p class="hint">
              Added before and after every booking; at least {{ MIN_BUFFER_MINUTES }} minutes each. Existing bookings
              keep the times they were made with.
            </p>
          </section>

          <p v-if="saveError" class="message error" role="alert">{{ saveError }}</p>
          <div class="actions">
            <button type="submit" class="btn primary" :disabled="saving || !isValid">
              {{ saving ? 'Saving...' : isEdit ? 'Save changes' : 'Add venue' }}
            </button>
            <router-link :to="cancelLink()" class="btn neutral">Cancel</router-link>
          </div>
          <p v-if="!isValid" class="hint" data-test="save-hint">Fill in every field marked * to save.</p>
        </form>
      </div>
    </main>
  </div>
</template>

<style scoped>
.page { min-height: 100vh; display: flex; flex-direction: column; background: #eeeeee; }
.content { flex: 1 1 auto; padding: 32px 16px; display: flex; justify-content: center; }
.container { width: 100%; max-width: 720px; display: flex; flex-direction: column; gap: 16px; }
.back-link { font-size: 13px; color: #2568e8; text-decoration: none; }
.title { margin: 0; font-size: 20px; font-weight: 700; color: #1f1f1f; }
.card {
  background: #fff; border: 1px solid #d6d6d6; border-radius: 6px; padding: 20px;
  display: flex; flex-direction: column; gap: 20px;
}
/* Sections: the bold headings are what the eye lands on. */
.section { display: flex; flex-direction: column; gap: 14px; }
.section + .section { padding-top: 20px; border-top: 1px solid #ececec; }
.section-title { margin: 0; font-size: 15px; font-weight: 700; color: #222; }
.row { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.field { display: flex; flex-direction: column; gap: 6px; border: none; padding: 0; margin: 0; min-width: 0; }
/* Field labels and group names: regular weight, normal case. */
.field > label, legend { font-size: 13px; font-weight: 400; color: #444; padding: 0; }
.required { color: #b42318; }
input[type="text"], input[type="number"] {
  box-sizing: border-box; width: 100%; padding: 8px 10px; border: 1px solid #b8b8b8; border-radius: 4px;
  font: inherit; font-size: 14px; background: #fff;
}
.options { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 8px 16px; }
.check {
  display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 400; color: #2a2a2a;
  text-transform: capitalize; cursor: pointer;
}
.hint { margin: 0; font-size: 12px; color: #7a7a7a; }
.field-error { margin: 0; font-size: 12px; color: #b42318; }
input[aria-invalid="true"] { border-color: #b42318; }
.message { margin: 0; font-size: 14px; color: #8a8a8a; }
.error { color: #b42318; }
.actions { display: flex; gap: 10px; flex-wrap: wrap; }
.btn {
  min-height: 38px; padding: 0 16px; border-radius: 4px; font: inherit; font-size: 13px; font-weight: 700;
  cursor: pointer; display: inline-flex; align-items: center; text-decoration: none;
}
.btn:disabled { opacity: .6; cursor: not-allowed; }
.primary { border: none; background: #2568e8; color: #fff; }
.neutral { border: 1px solid #b8b8b8; background: #fff; color: #444; font-weight: 400; }
@media (max-width: 560px) { .row { grid-template-columns: 1fr; } }
</style>
