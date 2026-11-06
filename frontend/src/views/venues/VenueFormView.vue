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
 * Operating hours (IS-11 AC5, 6 Nov) are optional: both empty means no set
 * hours. The venue calendar shows the time outside them as unavailable, and
 * new booking requests must fit inside them; existing bookings are left as
 * they are when they change.
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
  MIN_HOLD_MINUTES,
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
  <div class="page cs-page">
    <AppNavBar />
    <main class="content cs-content">
      <div class="container cs-container cs-container--narrow">
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
            <h2 class="section-title">Operating hours</h2>

            <!-- One error for the pair; leaving either box counts as leaving the field. -->
            <div class="row" data-field="operating_hours">
              <div class="field">
                <label for="venue-opens">Opens at</label>
                <input id="venue-opens" v-model="form.operating_hours_start" type="time"
                  :aria-invalid="Boolean(shownError('operating_hours'))" @blur="touch('operating_hours')" />
              </div>
              <div class="field">
                <label for="venue-closes">Closes at</label>
                <input id="venue-closes" v-model="form.operating_hours_end" type="time"
                  :aria-invalid="Boolean(shownError('operating_hours'))" @blur="touch('operating_hours')" />
              </div>
            </div>
            <p v-if="shownError('operating_hours')" class="field-error" data-error="operating_hours">
              {{ shownError('operating_hours') }}
            </p>
            <p class="hint">
              The same every day. A closing time earlier than the opening time means the venue closes the next day
              (e.g. 20:00 to 01:00, or 08:00 to 00:00 for open until midnight). Leave both empty if the venue has no
              set hours. New bookings must fit inside these
              hours, setup and turnaround included; existing bookings are not changed.
            </p>
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

            <div class="field">
              <label for="venue-hold">
                Tentative hold duration (minutes) <span class="required" aria-hidden="true">*</span>
              </label>
              <input id="venue-hold" v-model="form.tentative_hold_minutes" type="number" :min="MIN_HOLD_MINUTES" step="1"
                :aria-invalid="Boolean(shownError('tentative_hold_minutes'))" @blur="touch('tentative_hold_minutes')" />
              <p v-if="shownError('tentative_hold_minutes')" class="field-error" data-error="tentative_hold_minutes">
                {{ shownError('tentative_hold_minutes') }}
              </p>
            </div>
            <p class="hint">
              How long a confirmed venue booking is tentatively held before it expires if the coordinator hasn't
              confirmed the event. Existing bookings keep the hold they were confirmed with.
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
.container { max-width: 720px; }
.back-link { font-size: var(--cs-text-sm); color: var(--cs-signal); text-decoration: none; }
.title { margin: 0; font-size: var(--cs-text-xl); font-family: var(--cs-font-display); color: var(--cs-ink); }
.card {
  background: var(--cs-surface); border: 1px solid var(--cs-line); border-radius: var(--cs-radius-md); padding: var(--cs-space-5);
  display: flex; flex-direction: column; gap: var(--cs-space-5);
}
/* Sections: the bold headings are what the eye lands on. */
.section { display: flex; flex-direction: column; gap: var(--cs-space-3); }
.section + .section { padding-top: var(--cs-space-5); border-top: 1px solid var(--cs-line); }
.section-title { margin: 0; font-size: var(--cs-text-md); font-family: var(--cs-font-display); color: var(--cs-ink); }
.row { display: grid; grid-template-columns: 1fr 1fr; gap: var(--cs-space-3); }
.field { display: flex; flex-direction: column; gap: 6px; border: none; padding: 0; margin: 0; min-width: 0; }
/* Field labels and group names: regular weight, normal case. */
.field > label, legend { font-size: var(--cs-text-sm); font-weight: 400; color: var(--cs-ink-soft); padding: 0; }
.required { color: var(--cs-occupied); }
input[type="text"], input[type="number"], input[type="time"] {
  box-sizing: border-box; width: 100%; padding: var(--cs-space-2) var(--cs-space-3); border: 1px solid var(--cs-line-strong); border-radius: var(--cs-radius-sm);
  font: inherit; font-size: var(--cs-text-base); background: var(--cs-surface);
}
.options { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: var(--cs-space-2) var(--cs-space-4); }
.check {
  display: flex; align-items: center; gap: var(--cs-space-2); font-size: var(--cs-text-base); font-weight: 400; color: var(--cs-ink);
  text-transform: capitalize; cursor: pointer;
}
.hint { margin: 0; font-size: var(--cs-text-xs); color: var(--cs-ink-soft); }
.field-error { margin: 0; font-size: var(--cs-text-xs); color: var(--cs-occupied); }
input[aria-invalid="true"] { border-color: var(--cs-occupied); }
.message { margin: 0; font-size: var(--cs-text-base); color: var(--cs-ink-soft); }
.error { color: var(--cs-occupied); }
.actions { display: flex; gap: var(--cs-space-3); flex-wrap: wrap; }
.btn {
  min-height: 38px; padding: 0 var(--cs-space-4); border-radius: var(--cs-radius-sm); font: inherit; font-size: var(--cs-text-sm); font-weight: 700;
  cursor: pointer; display: inline-flex; align-items: center; text-decoration: none;
}
.btn:disabled { opacity: .6; cursor: not-allowed; }
.primary { border: none; background: var(--cs-signal); color: #fff; }
.primary:hover:not(:disabled) { background: var(--cs-signal-strong); }
.neutral { border: 1px solid var(--cs-line-strong); background: var(--cs-surface); color: var(--cs-ink); font-weight: 400; }
@media (max-width: 560px) { .row { grid-template-columns: 1fr; } }
</style>
