<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiDelete, apiGet, apiPost } from '../../lib/api'
import { useAuthStore } from '../../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const event = ref(null)
const loading = ref(true)
const saving = ref(false)
const submitting = ref(false)
const deleting = ref(false)
const error = ref('')
const saved = ref(false)
const errors = reactive({})

const form = reactive({
  name: '',
  description: '',
  purpose: '',
  preferred_start_datetime: '',
  preferred_end_datetime: '',
  expected_attendance: '',
  accessibility_needs: [],
  room_layout: '',
  equipment: [],
  registration_needs: false,
  special_requests: '',
})

const layouts = ['theatre', 'classroom', 'boardroom', 'seminar', 'banquet', 'networking']
const equipmentOptions = [
  { value: 'microphone', label: 'Microphones', quantity: true },
  { value: 'projector', label: 'Projectors', quantity: true },
  { value: 'screen', label: 'Screens', quantity: true },
  { value: 'wifi', label: 'WiFi', quantity: false },
]
const accessibilityOptions = [
  { value: 'wheelchair_access', label: 'Wheelchair access', quantity: false },
  { value: 'lift_access', label: 'Lift access', quantity: false },
  { value: 'removable_seats', label: 'Removable seats', quantity: true },
  { value: 'extra_legroom_seats', label: 'Seats with extra legroom', quantity: true },
]

function localDateString(value) {
  const offset = value.getTimezoneOffset()
  return new Date(value.getTime() - offset * 60 * 1000).toISOString().slice(0, 10)
}

const minimumDate = localDateString(new Date(Date.now() + 24 * 60 * 60 * 1000))

const canEdit = computed(() => Boolean(
  event.value
  && ['draft', 'rejected'].includes(event.value.status)
  && event.value.organizer_id === auth.profile?.id,
))

// Deletion is narrower than editing: only a still-in-progress draft may be
// deleted -- once submitted, it's left the organizer's hands (see
// rule_event_delete on the backend), so this deliberately does NOT include
// "rejected" the way canEdit does.
const canDelete = computed(() => Boolean(
  event.value
  && event.value.status === 'draft'
  && event.value.organizer_id === auth.profile?.id,
))

const canSubmit = computed(() => {
  const required = [
    form.name,
    form.description,
    form.purpose,
    form.preferred_start_datetime,
    form.preferred_end_datetime,
    form.room_layout,
  ].every((value) => String(value ?? '').trim() !== '')
  const attendance = Number(form.expected_attendance) > 0
  const startIsValid = splitDateTime(form.preferred_start_datetime).date >= minimumDate
  // Plain string comparison is valid here because datetime-local values are
  // "YYYY-MM-DDTHH:mm", which sorts lexicographically the same as
  // chronologically -- this is the combined start-before-end check (not two
  // separate date/time rules), so an end time earlier than the start time is
  // correctly allowed as long as the end DATE is later (e.g. 22:00 on day
  // one to 06:00 on day two).
  const rangeIsValid = form.preferred_end_datetime > form.preferred_start_datetime
  const quantitiesAreValid = form.equipment.every((entry) => entry.quantity >= 1)
    && form.accessibility_needs.every((entry) => entry.quantity === undefined || entry.quantity >= 1)
  return required && attendance && startIsValid && rangeIsValid && quantitiesAreValid
})

const hasInvalidInput = computed(() => {
  const attendance = form.expected_attendance !== '' && Number(form.expected_attendance) <= 0
  const startDate = splitDateTime(form.preferred_start_datetime).date
  const startIsInvalid = startDate && startDate < minimumDate
  const rangeIsInvalid = form.preferred_start_datetime
    && form.preferred_end_datetime
    && form.preferred_end_datetime <= form.preferred_start_datetime
  const equipmentQuantity = form.equipment.some((entry) => entry.quantity < 1)
  const accessibilityQuantity = form.accessibility_needs.some(
    (entry) => entry.quantity !== undefined && entry.quantity < 1,
  )
  return attendance || startIsInvalid || rangeIsInvalid || equipmentQuantity || accessibilityQuantity
})

function timeValue(value) {
  return value ? value.slice(0, 5) : ''
}

// The two DB fields (a date column + a time column) are combined into one
// <input type="datetime-local"> value ("YYYY-MM-DDTHH:mm") for display, and
// split back apart in payload() before anything is sent to the backend --
// the backend only ever knows about the separate date/time columns.
function combineDateTime(datePart, timePart) {
  if (!datePart) return ''
  return `${datePart}T${timeValue(timePart) || '00:00'}`
}

function splitDateTime(value) {
  if (!value) return { date: '', time: '' }
  const [date, time] = value.split('T')
  return { date: date || '', time: time || '' }
}

function populateForm(value) {
  form.name = value.name === 'Untitled event request' ? '' : value.name || ''
  form.description = value.description || ''
  form.purpose = value.purpose || ''
  form.preferred_start_datetime = combineDateTime(value.preferred_start_date, value.preferred_start_time)
  form.preferred_end_datetime = combineDateTime(value.preferred_end_date, value.preferred_end_time)
  form.expected_attendance = value.expected_attendance || ''
  form.accessibility_needs = value.accessibility_needs || []
  form.room_layout = value.room_layout || ''
  form.equipment = value.equipment_needed?.equipment || []
  form.registration_needs = value.registration_needs || false
  form.special_requests = value.special_requests || ''
}

async function loadEvent() {
  loading.value = true
  error.value = ''
  try {
    event.value = await apiGet(`/events/${route.params.eventId}`)
    populateForm(event.value)
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    loading.value = false
  }
}

function findItem(field, value) {
  return form[field].find((entry) => entry.item === value)
}

function toggleItem(field, option) {
  const index = form[field].findIndex((entry) => entry.item === option.value)
  if (index === -1) {
    const entry = { item: option.value }
    if (option.quantity || option.value === 'wifi') entry.quantity = 1
    form[field].push(entry)
  } else {
    form[field].splice(index, 1)
  }
}

function validateDateRange() {
  delete errors.preferred_start_datetime
  delete errors.preferred_end_datetime
  const startDate = splitDateTime(form.preferred_start_datetime).date
  if (!form.preferred_start_datetime) {
    errors.preferred_start_datetime = 'Preferred start date and time is required.'
  } else if (startDate < minimumDate) {
    errors.preferred_start_datetime = 'Preferred start date must be after today.'
  }
  // Deliberately does NOT flag a still-empty end date here -- this runs on
  // every keystroke in either field (see the @input bindings below), and
  // the end field is naturally still empty while the user is filling in
  // the start field first. That "required" check only belongs in
  // validateForm(), which runs once, at actual submit time. An end date
  // that IS filled in but out of order is still flagged immediately,
  // since that's a genuine mistake worth catching right away.
  if (form.preferred_end_datetime && form.preferred_start_datetime) {
    if (form.preferred_end_datetime <= form.preferred_start_datetime) {
      errors.preferred_end_datetime = 'End date and time must be after the start date and time.'
    }
  }
}

function validateAttendance() {
  delete errors.expected_attendance
  if (form.expected_attendance !== '' && Number(form.expected_attendance) <= 0) {
    errors.expected_attendance = 'Expected attendance must be greater than zero.'
  }
}

function validateForm() {
  Object.keys(errors).forEach((field) => delete errors[field])
  if (!form.name.trim()) errors.name = 'Event name is required.'
  if (!form.description.trim()) errors.description = 'Description is required.'
  if (!form.purpose.trim()) errors.purpose = 'Purpose is required.'
  if (!form.room_layout) errors.room_layout = 'Please select a room layout.'
  validateDateRange()
  if (!form.preferred_end_datetime) {
    errors.preferred_end_datetime = 'Preferred end date and time is required.'
  }
  validateAttendance()
  if (!canSubmit.value) {
    form.equipment.forEach((entry) => {
      if (entry.quantity < 1) errors.equipment = 'Equipment quantities must be at least 1.'
    })
    form.accessibility_needs.forEach((entry) => {
      if (entry.quantity !== undefined && entry.quantity < 1) {
        errors.accessibility_needs = 'Accessibility quantities must be at least 1.'
      }
    })
  }
  return Object.keys(errors).length === 0
}

function payload() {
  const start = splitDateTime(form.preferred_start_datetime)
  const end = splitDateTime(form.preferred_end_datetime)
  return {
    name: form.name,
    description: form.description,
    purpose: form.purpose,
    preferred_start_date: start.date,
    preferred_start_time: start.time,
    preferred_end_date: end.date,
    preferred_end_time: end.time,
    expected_attendance: form.expected_attendance === '' ? null : Number(form.expected_attendance),
    accessibility_needs: form.accessibility_needs,
    room_layout: form.room_layout,
    equipment: form.equipment,
    registration_needs: form.registration_needs,
    special_requests: form.special_requests,
  }
}

async function saveDraft() {
  error.value = ''
  saved.value = false
  if (hasInvalidInput.value) return
  saving.value = true
  try {
    event.value = await apiPost(`/events/${event.value.id}/draft`, payload())
    populateForm(event.value)
    saved.value = true
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    saving.value = false
  }
}

async function submitEvent() {
  error.value = ''
  if (!validateForm()) return
  submitting.value = true
  try {
    await apiPost(`/events/${event.value.id}/draft`, payload())
    event.value = await apiPost(`/events/${event.value.id}/submit`, {})
    populateForm(event.value)
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    submitting.value = false
  }
}

async function deleteDraft() {
  if (!window.confirm('Delete this draft event request? This cannot be undone.')) return
  error.value = ''
  deleting.value = true
  try {
    await apiDelete(`/events/${event.value.id}`)
    router.push('/events')
  } catch (requestError) {
    error.value = requestError.message
    deleting.value = false
  }
}

onMounted(loadEvent)
</script>

<template>
  <main class="event-details">
    <p><router-link to="/events">&larr; Events</router-link></p>
    <p v-if="loading">Loading event...</p>
    <p v-else-if="error" class="error" role="alert">{{ error }}</p>
    <template v-else-if="event">
      <header>
        <div>
          <p class="eyebrow">Event request</p>
          <h1>{{ event.name }}</h1>
        </div>
        <strong class="status">{{ event.status }}</strong>
      </header>

      <form v-if="canEdit" @submit.prevent="submitEvent">
        <fieldset>
          <legend>Event details</legend>
          <label :class="{ invalid: errors.name }">Event name <input v-model.trim="form.name" @input="delete errors.name" /> <span v-if="errors.name" class="field-error">{{ errors.name }}</span></label>
          <label :class="{ invalid: errors.description }">Description <textarea v-model.trim="form.description" @input="delete errors.description" /> <span v-if="errors.description" class="field-error">{{ errors.description }}</span></label>
          <label :class="{ invalid: errors.purpose }">Purpose <textarea v-model.trim="form.purpose" @input="delete errors.purpose" /> <span v-if="errors.purpose" class="field-error">{{ errors.purpose }}</span></label>
          <div class="grid">
            <label :class="{ invalid: errors.preferred_start_datetime }">Preferred start date &amp; time <input v-model="form.preferred_start_datetime" type="datetime-local" :min="`${minimumDate}T00:00`" @input="validateDateRange" /> <span v-if="errors.preferred_start_datetime" class="field-error">{{ errors.preferred_start_datetime }}</span></label>
            <label :class="{ invalid: errors.preferred_end_datetime }">Preferred end date &amp; time <input v-model="form.preferred_end_datetime" type="datetime-local" :min="form.preferred_start_datetime || `${minimumDate}T00:00`" @input="validateDateRange" /> <span v-if="errors.preferred_end_datetime" class="field-error">{{ errors.preferred_end_datetime }}</span></label>
            <label :class="{ invalid: errors.expected_attendance }">Expected attendance <input v-model="form.expected_attendance" type="number" min="1" @input="validateAttendance" /> <span v-if="errors.expected_attendance" class="field-error">{{ errors.expected_attendance }}</span></label>
          </div>
        </fieldset>
        <fieldset>
          <legend>Venue and access</legend>
          <label :class="{ invalid: errors.room_layout }">Room layout
            <select v-model="form.room_layout" @change="delete errors.room_layout">
              <option value="">Select a layout</option>
              <option v-for="layout in layouts" :key="layout" :value="layout">{{ layout }}</option>
            </select>
            <span v-if="errors.room_layout" class="field-error">{{ errors.room_layout }}</span>
          </label>
          <span class="label">Accessibility needs</span>
          <label v-for="option in accessibilityOptions" :key="option.value" class="check">
            <input type="checkbox" :checked="Boolean(findItem('accessibility_needs', option.value))" @change="toggleItem('accessibility_needs', option)" />
            {{ option.label }}
            <input v-if="option.quantity && findItem('accessibility_needs', option.value)" type="number" min="1" :value="findItem('accessibility_needs', option.value).quantity" @input="findItem('accessibility_needs', option.value).quantity = Number($event.target.value)" />
          </label>
        </fieldset>
        <fieldset>
          <legend>Equipment and requests</legend>
          <label v-for="option in equipmentOptions" :key="option.value" class="check">
            <input type="checkbox" :checked="Boolean(findItem('equipment', option.value))" @change="toggleItem('equipment', option)" />
            {{ option.label }}
            <input v-if="option.quantity && findItem('equipment', option.value)" type="number" min="1" :value="findItem('equipment', option.value).quantity" @input="findItem('equipment', option.value).quantity = Number($event.target.value)" />
          </label>
          <label class="check"><input v-model="form.registration_needs" type="checkbox" /> Registration needs</label>
          <label>Special requests <textarea v-model.trim="form.special_requests" /></label>
        </fieldset>
        <span v-if="errors.accessibility_needs" class="field-error">{{ errors.accessibility_needs }}</span>
        <span v-if="errors.equipment" class="field-error">{{ errors.equipment }}</span>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
        <p v-if="saved" class="success" role="status">Draft saved.</p>
        <div class="actions">
          <button type="button" :disabled="hasInvalidInput || saving || submitting || deleting" @click="saveDraft">Save as Draft</button>
          <button type="submit" :disabled="!canSubmit || submitting || saving || deleting">{{ submitting ? 'Submitting...' : 'Submit request' }}</button>
          <button v-if="canDelete" type="button" class="delete-button" :disabled="saving || submitting || deleting" @click="deleteDraft">
            {{ deleting ? 'Deleting...' : 'Delete draft' }}
          </button>
        </div>
      </form>

      <section v-else class="read-only">
        <p class="notice">This event is {{ event.status }} and cannot be edited here.</p>
        <dl>
          <dt>Description</dt><dd>{{ event.description || 'Not provided' }}</dd>
          <dt>Purpose</dt><dd>{{ event.purpose || 'Not provided' }}</dd>
          <dt>Preferred start date</dt><dd>{{ event.preferred_start_date || 'Not provided' }}<template v-if="event.preferred_start_time"> at {{ timeValue(event.preferred_start_time) }}</template></dd>
          <dt>Preferred end date</dt><dd>{{ event.preferred_end_date || 'Not provided' }}<template v-if="event.preferred_end_time"> at {{ timeValue(event.preferred_end_time) }}</template></dd>
          <dt>Expected attendance</dt><dd>{{ event.expected_attendance || 'Not provided' }}</dd>
          <dt>Room layout</dt><dd>{{ event.room_layout || 'Not provided' }}</dd>
          <dt>Registration needs</dt><dd>{{ event.registration_needs ? 'Yes' : 'No' }}</dd>
          <dt>Special requests</dt><dd>{{ event.special_requests || 'None' }}</dd>
        </dl>
      </section>
    </template>
  </main>
</template>

<style scoped>
.event-details { max-width: 760px; margin: 2rem auto; padding: 0 1rem 3rem; }
header { display: flex; justify-content: space-between; gap: 1rem; align-items: start; }
.eyebrow, .label { font-weight: 700; }
h1 { margin-top: .25rem; }
.status { padding: .35rem .6rem; background: #e2e8f0; border-radius: 4px; text-transform: capitalize; }
form { display: grid; gap: 1rem; }
fieldset { display: grid; gap: .75rem; padding: 1rem; border: 1px solid #cbd5e1; border-radius: 6px; }
label { display: grid; gap: .35rem; }
input, textarea, select { box-sizing: border-box; width: 100%; padding: .6rem; border: 1px solid #94a3b8; border-radius: 4px; font: inherit; }
textarea { min-height: 5rem; resize: vertical; }
.grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: .75rem; }
.check { display: block; }
.check input[type='checkbox'] { width: auto; margin-right: .5rem; }
.check input[type='number'] { margin-top: .35rem; }
.actions { display: flex; gap: .75rem; }
button { padding: .7rem 1rem; border: 0; border-radius: 4px; background: #0f766e; color: white; font: inherit; cursor: pointer; }
button:disabled { opacity: .6; cursor: not-allowed; }
.delete-button { background: #b42318; margin-left: auto; }
.error { color: #b42318; }
.invalid input, .invalid textarea, .invalid select { border-color: #b42318; }
.field-error { color: #b42318; font-size: .85rem; }
.success { color: #067647; }
.notice { padding: .75rem; background: #f1f5f9; }
dl { display: grid; grid-template-columns: 180px 1fr; gap: .75rem 1rem; }
dt { font-weight: 700; }
dd { margin: 0; }
@media (max-width: 560px) { .grid, dl { grid-template-columns: 1fr; } }
</style>
