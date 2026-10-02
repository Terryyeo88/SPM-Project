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
  // Replaces the "Session N" heading (and its status badge) where the form
  // edits a single session on its own, e.g. the coordinator's review page.
  title: { type: String, default: '' },
})
defineEmits(['remove'])

// Ties the card's heading to the section for screen readers. Keyed by the
// session's own key, so ids stay unique with several sessions on one page.
const headingId = `session-heading-${props.session.key}`

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
  <section class="card session" :aria-labelledby="headingId">
    <div class="card-header">
      <h3 :id="headingId" class="card-title">
        {{ title || `Session ${index + 1}` }}
        <span v-if="!title && session.status && session.status !== 'draft'" class="status" :class="`status-${session.status}`">{{ session.status.replace('_', ' ') }}</span>
      </h3>
      <button v-if="removable" type="button" class="remove-session" aria-label="Remove session" @click="$emit('remove')">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="3 6 5 6 21 6" /><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" /><path d="M10 11v6" /><path d="M14 11v6" /><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" /></svg>
        Remove
      </button>
    </div>

    <!-- Optional message shown at the top of the card, e.g. the coordinator's
         reason when this session was rejected. -->
    <slot name="notice" />

    <div class="grid-2">
      <label class="field" :class="{ invalid: session.errors.preferred_start_datetime }">
        <span class="field-label">Preferred Start Date &amp; Time</span>
        <input v-model="session.preferred_start_datetime" class="input" type="datetime-local" :min="`${minimumDate}T00:00`" @input="validateDateRange(session, minimumDate)" />
        <span v-if="session.errors.preferred_start_datetime" class="field-error">{{ session.errors.preferred_start_datetime }}</span>
      </label>
      <label class="field" :class="{ invalid: session.errors.preferred_end_datetime }">
        <span class="field-label">Preferred End Date &amp; Time</span>
        <input v-model="session.preferred_end_datetime" class="input" type="datetime-local" :min="session.preferred_start_datetime || `${minimumDate}T00:00`" @input="validateDateRange(session, minimumDate)" />
        <span v-if="session.errors.preferred_end_datetime" class="field-error">{{ session.errors.preferred_end_datetime }}</span>
      </label>
    </div>

    <div class="grid-2">
      <label class="field" :class="{ invalid: session.errors.expected_attendance }">
        <span class="field-label">Expected Attendance</span>
        <input v-model="session.expected_attendance" class="input" type="number" min="1" placeholder="e.g. 150" @input="validateAttendance(session)" />
        <span v-if="session.errors.expected_attendance" class="field-error">{{ session.errors.expected_attendance }}</span>
      </label>
      <label class="field" :class="{ invalid: session.errors.room_layout }">
        <span class="field-label">Room Layout</span>
        <select v-model="session.room_layout" class="input" @change="delete session.errors.room_layout">
          <option value="" disabled>Select a layout</option>
          <option v-for="layout in ROOM_LAYOUTS" :key="layout" :value="layout">{{ layout }}</option>
        </select>
        <span v-if="session.errors.room_layout" class="field-error">{{ session.errors.room_layout }}</span>
      </label>
    </div>

    <div class="field" :class="{ invalid: session.errors.accessibility_needs }">
      <span class="field-label">Accessibility Needs <span class="optional">(optional)</span></span>
      <div class="option-list">
        <div v-for="item in ACCESSIBILITY_OPTIONS" :key="item.value" class="option-row">
          <label class="check">
            <input type="checkbox" :checked="Boolean(findItem('accessibility_needs', item.value))" @change="toggleItem('accessibility_needs', item, $event.target.checked)" />
            {{ item.label }}
          </label>
          <input v-if="findItem('accessibility_needs', item.value) && item.hasQuantity" class="input small" type="number" min="1" placeholder="Quantity" :aria-label="`${item.label} quantity`" :value="findItem('accessibility_needs', item.value).quantity" @input="updateQuantity('accessibility_needs', item.value, $event.target.value)" />
          <input v-if="findItem('accessibility_needs', item.value) && item.value === 'removable_seats'" class="input small notes" type="text" placeholder="Notes" :aria-label="`${item.label} notes`" :value="findItem('accessibility_needs', item.value).notes || ''" @input="updateNotes(item.value, $event.target.value)" />
        </div>
      </div>
      <span v-if="session.errors.accessibility_needs" class="field-error">{{ session.errors.accessibility_needs }}</span>
    </div>

    <div class="field" :class="{ invalid: session.errors.equipment }">
      <span class="field-label">Equipment &amp; Technical Requirements <span class="optional">(optional)</span></span>
      <div class="option-list">
        <div v-for="item in EQUIPMENT_OPTIONS" :key="item.value" class="option-row">
          <label class="check">
            <input type="checkbox" :checked="Boolean(findItem('equipment', item.value))" @change="toggleItem('equipment', item, $event.target.checked)" />
            {{ item.label }}
          </label>
          <input v-if="findItem('equipment', item.value) && item.hasQuantity" class="input small" type="number" min="1" placeholder="Quantity" :aria-label="`${item.label} quantity`" :value="findItem('equipment', item.value).quantity" @input="updateQuantity('equipment', item.value, $event.target.value)" />
        </div>
      </div>
      <span v-if="session.errors.equipment" class="field-error">{{ session.errors.equipment }}</span>
    </div>

    <div class="field">
      <span class="field-label">Registration</span>
      <label class="check">
        <input v-model="session.registration_needs" type="checkbox" @change="onRegistrationToggle" />
        Registration needed
      </label>
    </div>
    <div v-if="session.registration_needs" class="grid-2">
      <label class="field" :class="{ invalid: session.errors.registration_start_datetime }">
        <span class="field-label">Registration Opens</span>
        <input v-model="session.registration_start_datetime" class="input" type="datetime-local" :max="session.preferred_start_datetime || undefined" @input="validateRegistrationWindow(session, minimumDate)" />
        <span v-if="session.errors.registration_start_datetime" class="field-error">{{ session.errors.registration_start_datetime }}</span>
      </label>
      <label class="field" :class="{ invalid: session.errors.registration_end_datetime }">
        <span class="field-label">Registration Closes</span>
        <input v-model="session.registration_end_datetime" class="input" type="datetime-local" :min="session.registration_start_datetime || undefined" :max="session.preferred_start_datetime || undefined" @input="validateRegistrationWindow(session, minimumDate)" />
        <span v-if="session.errors.registration_end_datetime" class="field-error">{{ session.errors.registration_end_datetime }}</span>
      </label>
    </div>

    <label class="field">
      <span class="field-label">Special Requests <span class="optional">(optional)</span></span>
      <textarea v-model.trim="session.special_requests" class="input" rows="2" placeholder="e.g. near the main entrance, quiet room for speakers" />
    </label>
  </section>
</template>

<style scoped src="../styles/event-form.css"></style>
<style scoped>
.card-title { margin: 0; display: flex; align-items: center; gap: 8px; }
.input.notes { width: 220px; }
</style>
