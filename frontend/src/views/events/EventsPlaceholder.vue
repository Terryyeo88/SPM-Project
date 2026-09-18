<script setup>
import { reactive, ref } from 'vue'
import { apiPost } from '../../lib/api'

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
  name: '', description: '', purpose: '', preferred_date: '', preferred_start_time: '',
  preferred_end_time: '', expected_attendance: '', accessibility_needs: [],
  room_layout: '', equipment: [],
  registration_needs: false, special_requests: '',
})
const error = ref('')
const errors = reactive({})
const success = ref(false)
const submitting = ref(false)

function localDateString(date) {
  const offset = date.getTimezoneOffset()
  return new Date(date.getTime() - offset * 60 * 1000).toISOString().slice(0, 10)
}

const minimumDate = localDateString(new Date(Date.now() + 24 * 60 * 60 * 1000))

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
  return {
    ...form,
    expected_attendance: Number(form.expected_attendance),
  }
}

function validateDate() {
  delete errors.preferred_date
  if (!form.preferred_date) {
    errors.preferred_date = 'Preferred date is required.'
  } else if (form.preferred_date < minimumDate) {
    errors.preferred_date = 'Preferred date must be after today.'
  }
}

function validateTimeRange() {
  delete errors.preferred_start_time
  delete errors.preferred_end_time
  if (form.preferred_start_time && form.preferred_end_time && form.preferred_start_time >= form.preferred_end_time) {
    errors.preferred_start_time = 'Start time must be before the end time.'
    errors.preferred_end_time = 'End time must be after the start time.'
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

  validateDate()

  if (!form.expected_attendance || Number(form.expected_attendance) <= 0) {
    errors.expected_attendance = 'Expected attendance must be greater than zero.'
  }
  validateTimeRange()

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
    const draft = await apiPost('/events', payload())
    await apiPost(`/events/${draft.id}/submit`, {})
    success.value = true
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    submitting.value = false
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
          <label :class="{ invalid: errors.preferred_date }">Preferred date <input v-model="form.preferred_date" type="date" :min="minimumDate" @input="validateDate" /> <span v-if="errors.preferred_date" class="field-error">{{ errors.preferred_date }}</span></label>
          <label :class="{ invalid: errors.expected_attendance }">Expected attendance <input v-model="form.expected_attendance" type="number" min="1" /> <span v-if="errors.expected_attendance" class="field-error">{{ errors.expected_attendance }}</span></label>
          <label :class="{ invalid: errors.preferred_start_time }">Start time <input v-model="form.preferred_start_time" type="time" @input="validateTimeRange" /> <span v-if="errors.preferred_start_time" class="field-error">{{ errors.preferred_start_time }}</span></label>
          <label :class="{ invalid: errors.preferred_end_time }">End time <input v-model="form.preferred_end_time" type="time" :min="form.preferred_start_time || undefined" @input="validateTimeRange" /> <span v-if="errors.preferred_end_time" class="field-error">{{ errors.preferred_end_time }}</span></label>
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
      <p v-if="success" class="success" role="status">Event request submitted for review.</p>
      <button type="submit" :disabled="submitting">{{ submitting ? 'Submitting...' : 'Submit request' }}</button>
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
button:disabled { opacity: .6; cursor: wait; }
.error { color: #b42318; }
.invalid input, .invalid textarea, .invalid select { border-color: #b42318; }
.field-error { color: #b42318; font-size: .85rem; }
.success { color: #067647; }
@media (max-width: 560px) { .grid { grid-template-columns: 1fr; } }
</style>
