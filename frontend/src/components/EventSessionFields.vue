<script setup>
// One session of an event request: its own timing, attendance, venue
// requirements and registration window. The parent owns the session object
// (from lib/eventSessions) and this component edits it in place, running
// the same reactive validation the single-event form used to.
import {
  ACCESSIBILITY_OPTIONS,
  EQUIPMENT_OPTIONS,
  ROOM_LAYOUTS,
  validateAttendance,
  validateDateRange,
  validateQuantities,
  validateRegistrationWindow,
} from '../lib/eventSessions'

const props = defineProps({
  session: { type: Object, required: true },
  index: { type: Number, required: true },
  minimumDate: { type: String, required: true },
  removable: { type: Boolean, default: false },
})
defineEmits(['remove'])

function findItem(field, value) {
  return props.session[field].find((entry) => entry.item === value)
}

function toggleItem(field, option, selected) {
  const index = props.session[field].findIndex((entry) => entry.item === option.value)
  if (selected && index === -1) {
    const entry = { item: option.value }
    if (option.hasQuantity || option.value === 'wifi') entry.quantity = 1
    props.session[field].push(entry)
  }
  if (!selected && index !== -1) props.session[field].splice(index, 1)
  validateQuantities(props.session)
}

function updateQuantity(field, value, quantity) {
  const entry = findItem(field, value)
  if (entry) entry.quantity = Number(quantity)
  validateQuantities(props.session)
}

function updateNotes(value, notes) {
  const entry = findItem('accessibility_needs', value)
  if (entry) entry.notes = notes
}

function onRegistrationToggle() {
  if (!props.session.registration_needs) {
    props.session.registration_start_datetime = ''
    props.session.registration_end_datetime = ''
  }
  validateRegistrationWindow(props.session, props.minimumDate)
}
</script>

<template>
  <fieldset class="session">
    <legend>
      Session {{ index + 1 }}
      <span v-if="session.status && session.status !== 'draft'" class="session-status">{{ session.status }}</span>
    </legend>
    <div v-if="removable" class="session-actions">
      <button v-if="removable" type="button" class="remove" @click="$emit('remove')">Remove session</button>
    </div>

    <div class="grid">
      <label :class="{ invalid: session.errors.preferred_start_datetime }">Preferred start date &amp; time
        <input v-model="session.preferred_start_datetime" type="datetime-local" :min="`${minimumDate}T00:00`" @input="validateDateRange(session, minimumDate)" />
        <span v-if="session.errors.preferred_start_datetime" class="field-error">{{ session.errors.preferred_start_datetime }}</span>
      </label>
      <label :class="{ invalid: session.errors.preferred_end_datetime }">Preferred end date &amp; time
        <input v-model="session.preferred_end_datetime" type="datetime-local" :min="session.preferred_start_datetime || `${minimumDate}T00:00`" @input="validateDateRange(session, minimumDate)" />
        <span v-if="session.errors.preferred_end_datetime" class="field-error">{{ session.errors.preferred_end_datetime }}</span>
      </label>
      <label :class="{ invalid: session.errors.expected_attendance }">Expected attendance
        <input v-model="session.expected_attendance" type="number" min="1" @input="validateAttendance(session)" />
        <span v-if="session.errors.expected_attendance" class="field-error">{{ session.errors.expected_attendance }}</span>
      </label>
      <label :class="{ invalid: session.errors.room_layout }">Room layout
        <select v-model="session.room_layout" @change="delete session.errors.room_layout">
          <option value="" disabled>Select a layout</option>
          <option v-for="layout in ROOM_LAYOUTS" :key="layout" :value="layout">{{ layout }}</option>
        </select>
        <span v-if="session.errors.room_layout" class="field-error">{{ session.errors.room_layout }}</span>
      </label>
    </div>

    <span class="label" :class="{ invalid: session.errors.accessibility_needs }">Accessibility needs</span>
    <div v-for="item in ACCESSIBILITY_OPTIONS" :key="item.value" class="item-row">
      <label class="check">
        <input type="checkbox" :checked="Boolean(findItem('accessibility_needs', item.value))" @change="toggleItem('accessibility_needs', item, $event.target.checked)" />
        {{ item.label }}
      </label>
      <input v-if="findItem('accessibility_needs', item.value) && item.hasQuantity" type="number" min="1" placeholder="Quantity" :value="findItem('accessibility_needs', item.value).quantity" @input="updateQuantity('accessibility_needs', item.value, $event.target.value)" />
      <input v-if="findItem('accessibility_needs', item.value) && item.value === 'removable_seats'" type="text" placeholder="Notes" :value="findItem('accessibility_needs', item.value).notes || ''" @input="updateNotes(item.value, $event.target.value)" />
    </div>
    <span v-if="session.errors.accessibility_needs" class="field-error">{{ session.errors.accessibility_needs }}</span>

    <span class="label" :class="{ invalid: session.errors.equipment }">Equipment</span>
    <div v-for="item in EQUIPMENT_OPTIONS" :key="item.value" class="item-row">
      <label class="check">
        <input type="checkbox" :checked="Boolean(findItem('equipment', item.value))" @change="toggleItem('equipment', item, $event.target.checked)" />
        {{ item.label }}
      </label>
      <input v-if="findItem('equipment', item.value) && item.hasQuantity" type="number" min="1" placeholder="Quantity" :value="findItem('equipment', item.value).quantity" @input="updateQuantity('equipment', item.value, $event.target.value)" />
    </div>
    <span v-if="session.errors.equipment" class="field-error">{{ session.errors.equipment }}</span>

    <label class="check">
      <input v-model="session.registration_needs" type="checkbox" @change="onRegistrationToggle" />
      Registration needed
    </label>
    <div v-if="session.registration_needs" class="grid">
      <label :class="{ invalid: session.errors.registration_start_datetime }">Registration opens
        <input v-model="session.registration_start_datetime" type="datetime-local" :max="session.preferred_start_datetime || undefined" @input="validateRegistrationWindow(session, minimumDate)" />
        <span v-if="session.errors.registration_start_datetime" class="field-error">{{ session.errors.registration_start_datetime }}</span>
      </label>
      <label :class="{ invalid: session.errors.registration_end_datetime }">Registration closes
        <input v-model="session.registration_end_datetime" type="datetime-local" :min="session.registration_start_datetime || undefined" :max="session.preferred_start_datetime || undefined" @input="validateRegistrationWindow(session, minimumDate)" />
        <span v-if="session.errors.registration_end_datetime" class="field-error">{{ session.errors.registration_end_datetime }}</span>
      </label>
    </div>

    <label>Special requests <textarea v-model.trim="session.special_requests" /></label>
  </fieldset>
</template>

<style scoped>
fieldset { display: grid; gap: .75rem; padding: 1rem; border: 1px solid #cbd5e1; border-radius: 6px; }
legend, .label { font-weight: 700; }
label { display: grid; gap: .35rem; }
input, textarea, select { box-sizing: border-box; width: 100%; padding: .6rem; border: 1px solid #94a3b8; border-radius: 4px; font: inherit; }
textarea { min-height: 4rem; resize: vertical; }
.grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: .75rem; }
.check { display: block; }
.check input { width: auto; margin-right: .5rem; }
.item-row { display: grid; gap: .35rem; }
.session-status { margin-left: .5rem; padding: .1rem .45rem; background: #e2e8f0; border-radius: 4px; font-weight: 400; text-transform: capitalize; }
.session-actions { display: flex; gap: .5rem; justify-content: flex-end; }
.session-actions button { width: fit-content; padding: .45rem .8rem; border: 0; border-radius: 4px; color: white; font: inherit; cursor: pointer; }
.remove { background: #b42318; }
.invalid input, .invalid textarea, .invalid select { border-color: #b42318; }
.field-error { color: #b42318; font-size: .85rem; font-weight: 400; }
@media (max-width: 560px) { .grid { grid-template-columns: 1fr; } }
</style>
