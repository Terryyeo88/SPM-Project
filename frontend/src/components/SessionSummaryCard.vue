<script setup>
// Read-only card for one session of an event request, used on the event
// page wherever a session is shown but not edited: every session of a
// request that can't be edited, and the sessions shown alongside rejected
// ones while those are being fixed.
import { statusLabel } from '../lib/coordinatorDashboard'
import { ACCESSIBILITY_OPTIONS, EQUIPMENT_OPTIONS, timeValue } from '../lib/eventSessions'

defineProps({
  session: { type: Object, required: true },
  index: { type: Number, required: true },
  // Highlights the session the page's URL points at.
  current: { type: Boolean, default: false },
  // Makes the heading a link to that session's own page.
  link: { type: Boolean, default: false },
})

const itemLabels = Object.fromEntries(
  [...EQUIPMENT_OPTIONS, ...ACCESSIBILITY_OPTIONS].map((option) => [option.value, option.label]),
)

function describeItems(items) {
  if (!items?.length) return 'None'
  return items
    .map((entry) => {
      const quantity = entry.quantity && entry.item !== 'wifi' ? ` × ${entry.quantity}` : ''
      const notes = entry.notes ? ` (${entry.notes})` : ''
      return `${itemLabels[entry.item] ?? entry.item}${quantity}${notes}`
    })
    .join(', ')
}

function formatDateTime(value) {
  return value ? new Date(value).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : 'Not provided'
}
</script>

<template>
  <section class="card session-card" :class="{ current }" :aria-labelledby="`session-${session.id}`">
    <div class="card-header">
      <h3 :id="`session-${session.id}`" class="card-title">
        <router-link v-if="link" :to="`/events/${session.id}`">Session {{ index + 1 }}</router-link>
        <template v-else>Session {{ index + 1 }}</template>
      </h3>
      <span class="status" :class="`status-${session.status}`">{{ statusLabel(session.status) }}</span>
    </div>
    <dl>
      <dt>Preferred start</dt><dd>{{ session.preferred_start_date || 'Not provided' }}<template v-if="session.preferred_start_time"> at {{ timeValue(session.preferred_start_time) }}</template></dd>
      <dt>Preferred end</dt><dd>{{ session.preferred_end_date || 'Not provided' }}<template v-if="session.preferred_end_time"> at {{ timeValue(session.preferred_end_time) }}</template></dd>
      <dt>Expected attendance</dt><dd>{{ session.expected_attendance || 'Not provided' }}</dd>
      <dt>Room layout</dt><dd class="capitalize">{{ session.room_layout || 'Not provided' }}</dd>
      <dt>Accessibility needs</dt><dd>{{ describeItems(session.accessibility_needs) }}</dd>
      <dt>Equipment</dt><dd>{{ describeItems(session.equipment_needed?.equipment) }}</dd>
      <dt>Registration needed</dt><dd>{{ session.registration_needs ? 'Yes' : 'No' }}</dd>
      <template v-if="session.registration_needs">
        <dt>Registration opens</dt><dd>{{ formatDateTime(session.registration_start_datetime) }}</dd>
        <dt>Registration closes</dt><dd>{{ formatDateTime(session.registration_end_datetime) }}</dd>
      </template>
      <dt>Special requests</dt><dd>{{ session.special_requests || 'None' }}</dd>
    </dl>
  </section>
</template>

<style scoped src="../styles/event-form.css"></style>
<style scoped>
.session-card.current { border-style: solid; border-color: #444444; }
.card-title a { color: inherit; }
dl { display: grid; grid-template-columns: 180px 1fr; gap: 10px 16px; margin: 0; font-size: 14px; }
dt { font-weight: 600; color: #6a6a6a; }
dd { margin: 0; color: #2a2a2a; }
.capitalize { text-transform: capitalize; }
@media (max-width: 640px) {
  dl { grid-template-columns: 1fr; gap: 4px; }
  dd { margin-bottom: 8px; }
}
</style>
