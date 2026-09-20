<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { apiGet, apiPost } from '../../lib/api'

const draftStorageKey = 'connectsphere-event-draft-id'

const roomLayouts = ['theatre', 'classroom', 'boardroom', 'seminar', 'banquet', 'networking']
const equipment = [
  { value: 'microphone', label: 'Microphones', hasQuantity: true },
  { value: 'projector', label: 'Projectors', hasQuantity: true },
  { value: 'screen', label: 'Screens', hasQuantity: true },
  { value: 'wifi', label: 'WiFi', hasQuantity: false },
]
const accessibilityNeeds = [
  { value: 'wheelchair_access', label: 'Wheelchair access', hasQuantity: false },
  { value: 'lift_access', label: 'Lift access', hasQuantity: false },
  { value: 'removable_seats', label: 'Removable seats', hasQuantity: true },
  { value: 'extra_legroom_seats', label: 'Seats with extra legroom', hasQuantity: true },
]

const form = reactive({
  name: '', description: '', purpose: '', preferred_start_datetime: '', preferred_end_datetime: '',
  expected_attendance: '', accessibility_needs: [],
  room_layout: '', equipment: [],
  registration_needs: false, special_requests: '',
})
const error = ref('')
const errors = reactive({})
const success = ref(false)
const submitting = ref(false)
const savingDraft = ref(false)
const draftId = ref(null)
const draftSaved = ref(false)

function localDateString(date) {
  const offset = date.getTimezoneOffset()
  return new Date(date.getTime() - offset * 60 * 1000).toISOString().slice(0, 10)
}

const minimumDate = localDateString(new Date(Date.now() + 24 * 60 * 60 * 1000))

function timeInputValue(value) {
  return value ? value.slice(0, 5) : ''
}

// The two DB fields (a date column + a time column) are combined into one
// <input type="datetime-local"> value ("YYYY-MM-DDTHH:mm") for display, and
// split back apart in payload() before anything is sent to the backend --
// the backend only ever knows about the separate date/time columns.
function combineDateTime(datePart, timePart) {
  if (!datePart) return ''
  return `${datePart}T${timeInputValue(timePart) || '00:00'}`
}

function splitDateTime(value) {
  if (!value) return { date: '', time: '' }
  const [date, time] = value.split('T')
  return { date: date || '', time: time || '' }
}

// Mirrors event_service.py's MAX_EVENT_DURATION -- an event's total span,
// start to end, may not exceed 24 hours. Both values are datetime-local
// strings, parsed as local time by `new Date()` (no timezone conversion,
// same wall-clock interpretation the rest of this form already uses).
const MAX_EVENT_DURATION_MS = 24 * 60 * 60 * 1000

function exceedsMaxDuration(startValue, endValue) {
  return new Date(endValue) - new Date(startValue) > MAX_EVENT_DURATION_MS
}

async function loadSavedDraft() {
  const savedDraftId = localStorage.getItem(draftStorageKey)
  if (!savedDraftId) return

  try {
    const event = await apiGet(`/events/${savedDraftId}`)
    if (!['draft', 'rejected'].includes(event.status)) {
      localStorage.removeItem(draftStorageKey)
      return
    }
    draftId.value = event.id
    form.name = event.name === 'Untitled event request' ? '' : event.name || ''
    form.description = event.description || ''
    form.purpose = event.purpose || ''
    form.preferred_start_datetime = combineDateTime(event.preferred_start_date, event.preferred_start_time)
    form.preferred_end_datetime = combineDateTime(event.preferred_end_date, event.preferred_end_time)
    form.expected_attendance = event.expected_attendance || ''
    form.accessibility_needs = event.accessibility_needs || []
    form.room_layout = event.room_layout || ''
    form.equipment = event.equipment_needed?.equipment || []
    form.registration_needs = event.registration_needs || false
    form.special_requests = event.special_requests || ''
  } catch (requestError) {
    localStorage.removeItem(draftStorageKey)
  }
}

onMounted(loadSavedDraft)

function findItem(field, value) {
  return form[field].find((entry) => entry.item === value)
}

function toggleItem(field, value, selected) {
  const index = form[field].findIndex((entry) => entry.item === value)
  if (selected && index === -1) {
    const option = [...equipment, ...accessibilityNeeds].find((item) => item.value === value)
    const entry = { item: value }
    if (option?.hasQuantity || value === 'wifi') entry.quantity = 1
    form[field].push(entry)
  }
  if (!selected && index !== -1) form[field].splice(index, 1)
}

function updateQuantity(field, value, quantity) {
  const entry = findItem(field, value)
  if (entry) entry.quantity = Number(quantity)
}

function updateNotes(value, notes) {
  const entry = findItem('accessibility_needs', value)
  if (entry) entry.notes = notes
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
    expected_attendance: Number(form.expected_attendance),
    accessibility_needs: form.accessibility_needs,
    room_layout: form.room_layout,
    equipment: form.equipment,
    registration_needs: form.registration_needs,
    special_requests: form.special_requests,
  }
}

const hasDraftData = computed(() => [
  form.name,
  form.description,
  form.purpose,
  form.preferred_start_datetime,
  form.preferred_end_datetime,
  form.expected_attendance,
  form.room_layout,
  form.special_requests,
].some((value) => String(value ?? '').trim() !== '')
  || form.registration_needs
  || form.accessibility_needs.length > 0
  || form.equipment.length > 0)

const canSubmit = computed(() => {
  const hasRequiredFields = [
    form.name,
    form.description,
    form.purpose,
    form.preferred_start_datetime,
    form.preferred_end_datetime,
    form.room_layout,
  ].every((value) => String(value ?? '').trim() !== '')
  const hasAttendance = Number(form.expected_attendance) > 0
  const hasValidStart = splitDateTime(form.preferred_start_datetime).date >= minimumDate
  // Plain string comparison is valid here because datetime-local values are
  // "YYYY-MM-DDTHH:mm", which sorts lexicographically the same as
  // chronologically -- this is the combined start-before-end check (not two
  // separate date/time rules), so an end time earlier than the start time is
  // correctly allowed as long as the end DATE is later (e.g. 22:00 on day
  // one to 06:00 on day two).
  const hasValidRange = form.preferred_end_datetime > form.preferred_start_datetime
    && !exceedsMaxDuration(form.preferred_start_datetime, form.preferred_end_datetime)
  const hasValidQuantities = form.equipment.every((entry) => entry.quantity >= 1)
    && form.accessibility_needs.every((entry) => entry.quantity === undefined || entry.quantity >= 1)
  return hasRequiredFields && hasAttendance && hasValidStart && hasValidRange && hasValidQuantities
})

const hasInvalidInput = computed(() => {
  const hasInvalidAttendance = form.expected_attendance !== '' && Number(form.expected_attendance) <= 0
  const startDate = splitDateTime(form.preferred_start_datetime).date
  const hasInvalidStart = startDate && startDate < minimumDate
  const hasInvalidRange = form.preferred_start_datetime
    && form.preferred_end_datetime
    && (form.preferred_end_datetime <= form.preferred_start_datetime
      || exceedsMaxDuration(form.preferred_start_datetime, form.preferred_end_datetime))
  const hasInvalidEquipmentQuantity = form.equipment.some((entry) => entry.quantity < 1)
  const hasInvalidAccessibilityQuantity = form.accessibility_needs.some(
    (entry) => entry.quantity !== undefined && entry.quantity < 1,
  )
  return hasInvalidAttendance
    || hasInvalidStart
    || hasInvalidRange
    || hasInvalidEquipmentQuantity
    || hasInvalidAccessibilityQuantity
})

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
    } else if (exceedsMaxDuration(form.preferred_start_datetime, form.preferred_end_datetime)) {
      errors.preferred_end_datetime = 'Event duration cannot exceed 24 hours.'
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

  const requiredText = [
    ['name', 'Event name is required.'],
    ['description', 'Description is required.'],
    ['purpose', 'Purpose is required.'],
    ['room_layout', 'Please select a room layout.'],
    ['special_requests', null],
  ]
  requiredText.forEach(([field, message]) => {
    if (message && !form[field].trim()) errors[field] = message
  })

  validateDateRange()
  if (!form.preferred_end_datetime) {
    errors.preferred_end_datetime = 'Preferred end date and time is required.'
  }

  validateAttendance()

  form.equipment.forEach((entry) => {
    if (entry.quantity < 1) errors.equipment = 'Equipment quantities must be at least 1.'
  })
  form.accessibility_needs.forEach((entry) => {
    if (entry.quantity !== undefined && entry.quantity < 1) errors.accessibility_needs = 'Accessibility quantities must be at least 1.'
  })
  return Object.keys(errors).length === 0
}

async function submitRequest() {
  error.value = ''
  success.value = false
  if (!validateForm()) return
  submitting.value = true
  try {
    const draft = draftId.value
      ? await apiPost(`/events/${draftId.value}/draft`, payload())
      : await apiPost('/events', payload())
    draftId.value = draft.id
    await apiPost(`/events/${draft.id}/submit`, {})
    // localStorage is to store data locally on a user's machine
    localStorage.removeItem(draftStorageKey)
    success.value = true
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    submitting.value = false
  }
}

async function saveDraft() {
  error.value = ''
  success.value = false
  draftSaved.value = false
  if (!hasDraftData.value) return
  savingDraft.value = true
  try {
    const draft = draftId.value
      ? await apiPost(`/events/${draftId.value}/draft`, payload())
      : await apiPost('/events/draft', payload())
    draftId.value = draft.id
    localStorage.setItem(draftStorageKey, draft.id)
    draftSaved.value = true
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    savingDraft.value = false
  }
}
</script>

<template>
  <main class="events-page">
    <p><router-link to="/">&larr; Back</router-link></p>
    <h1>Create an event request</h1>
    <p class="intro">Complete the event brief so a coordinator can review and plan it.</p>

    <form novalidate @submit.prevent="submitRequest">
      <fieldset>
        <legend>Event details</legend>
        <label :class="{ invalid: errors.name }">Event name <input v-model.trim="form.name" /> <span v-if="errors.name" class="field-error">{{ errors.name }}</span></label>
        <label :class="{ invalid: errors.description }">Description <textarea v-model.trim="form.description" /> <span v-if="errors.description" class="field-error">{{ errors.description }}</span></label>
        <label :class="{ invalid: errors.purpose }">Purpose of the event <textarea v-model.trim="form.purpose" /> <span v-if="errors.purpose" class="field-error">{{ errors.purpose }}</span></label>
        <div class="grid">
          <label :class="{ invalid: errors.preferred_start_datetime }">Preferred start date &amp; time <input v-model="form.preferred_start_datetime" type="datetime-local" :min="`${minimumDate}T00:00`" @input="validateDateRange" /> <span v-if="errors.preferred_start_datetime" class="field-error">{{ errors.preferred_start_datetime }}</span></label>
          <label :class="{ invalid: errors.preferred_end_datetime }">Preferred end date &amp; time <input v-model="form.preferred_end_datetime" type="datetime-local" :min="form.preferred_start_datetime || `${minimumDate}T00:00`" @input="validateDateRange" /> <span v-if="errors.preferred_end_datetime" class="field-error">{{ errors.preferred_end_datetime }}</span></label>
          <label :class="{ invalid: errors.expected_attendance }">Expected attendance <input v-model="form.expected_attendance" type="number" min="1" @input="validateAttendance" /> <span v-if="errors.expected_attendance" class="field-error">{{ errors.expected_attendance }}</span></label>
        </div>
      </fieldset>

      <fieldset>
        <legend>Venue and access</legend>
        <span class="label" :class="{ invalid: errors.accessibility_needs }">Accessibility needs</span>
        <div v-for="item in accessibilityNeeds" :key="item.value" class="item-row">
          <label class="check">
            <input type="checkbox" :checked="Boolean(findItem('accessibility_needs', item.value))" @change="toggleItem('accessibility_needs', item.value, $event.target.checked)" />
            {{ item.label }}
          </label>
          <input v-if="findItem('accessibility_needs', item.value) && item.hasQuantity" type="number" min="1" placeholder="Quantity" :value="findItem('accessibility_needs', item.value).quantity" @input="updateQuantity('accessibility_needs', item.value, $event.target.value)" />
          <input v-if="findItem('accessibility_needs', item.value) && item.value === 'removable_seats'" type="text" placeholder="Notes" :value="findItem('accessibility_needs', item.value).notes || ''" @input="updateNotes(item.value, $event.target.value)" />
        </div>
        <span v-if="errors.accessibility_needs" class="field-error">{{ errors.accessibility_needs }}</span>
        <label :class="{ invalid: errors.room_layout }">Room layout
          <select v-model="form.room_layout">
            <option value="" disabled>Select a layout</option>
            <option v-for="layout in roomLayouts" :key="layout" :value="layout">{{ layout }}</option>
          </select>
          <span v-if="errors.room_layout" class="field-error">{{ errors.room_layout }}</span>
        </label>
      </fieldset>

      <fieldset>
        <legend>Equipment and registration</legend>
        <span class="label" :class="{ invalid: errors.equipment }">Equipment</span>
        <div v-for="item in equipment" :key="item.value" class="item-row">
          <label class="check">
            <input type="checkbox" :checked="Boolean(findItem('equipment', item.value))" @change="toggleItem('equipment', item.value, $event.target.checked)" />
            {{ item.label }}
          </label>
          <input v-if="findItem('equipment', item.value) && item.hasQuantity" type="number" min="1" placeholder="Quantity" :value="findItem('equipment', item.value).quantity" @input="updateQuantity('equipment', item.value, $event.target.value)" />
        </div>
        <span v-if="errors.equipment" class="field-error">{{ errors.equipment }}</span>
        <label class="check">
          <input v-model="form.registration_needs" type="checkbox" />
          Registration needs
        </label>
        <label>Special requests <textarea v-model.trim="form.special_requests" /></label>
      </fieldset>

      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <p v-if="draftSaved" class="success" role="status">Draft saved.</p>
      <p v-if="success" class="success" role="status">Event request submitted for review.</p>
      <div class="actions">
        <button type="button" class="draft-button" :disabled="!hasDraftData || hasInvalidInput || savingDraft || submitting" @click="saveDraft">
          {{ savingDraft ? 'Saving...' : 'Save as Draft' }}
        </button>
        <button type="submit" :disabled="!canSubmit || submitting || savingDraft">{{ submitting ? 'Submitting...' : 'Submit request' }}</button>
      </div>
    </form>
  </main>
</template>

<style scoped>
.events-page { max-width: 760px; margin: 2rem auto; padding: 0 1rem 3rem; }
.intro { color: #52606d; }
form { display: grid; gap: 1rem; }
fieldset { display: grid; gap: .75rem; padding: 1rem; border: 1px solid #cbd5e1; border-radius: 6px; }
legend, .label { font-weight: 700; }
label { display: grid; gap: .35rem; }
input, textarea, select { box-sizing: border-box; width: 100%; padding: .6rem; border: 1px solid #94a3b8; border-radius: 4px; font: inherit; }
textarea { min-height: 5rem; resize: vertical; }
.grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: .75rem; }
.check { display: block; }
.check input { width: auto; margin-right: .5rem; }
button { width: fit-content; padding: .7rem 1.1rem; border: 0; border-radius: 4px; background: #0f766e; color: white; font: inherit; cursor: pointer; }
button:disabled { opacity: .6; cursor: not-allowed; }
.actions { display: flex; gap: .75rem; flex-wrap: wrap; }
.draft-button { background: #475569; }
.error { color: #b42318; }
.invalid input, .invalid textarea, .invalid select { border-color: #b42318; }
.field-error { color: #b42318; font-size: .85rem; }
.success { color: #067647; }
@media (max-width: 560px) { .grid { grid-template-columns: 1fr; } }
</style>
