<script setup>
/**
 * The assigned coordinator's view of an event request, laid out after the
 * "Event Review -- Coordinator" wireframe: status, conversation, the
 * submitted details read-only, then "Your Decision".
 *
 * Decisions:
 *   Approve  -> POST /events/<id>/approve   (under_review -> approved)
 *   Reject   -> POST /events/<id>/reject    (under_review -> rejected, reason required)
 *   Reassign -> POST /events/<id>/reassign-coordinator, choosing from
 *               GET /events/coordinators. Afterwards this coordinator no
 *               longer has the event, so they're sent back to their dashboard.
 *
 * Editing:
 *   Edit Details -> POST /events/<id>. Once a request is submitted only the
 *               assigned coordinator may change it (IS-31), while it's
 *               under review or in planning (rule_event_edit). This edits
 *               THIS session only -- each session is its own event record,
 *               reviewed on its own -- with the same form and as-you-type
 *               validation the organiser uses (EventSessionFields).
 *
 * Sessions:
 *   One coordinator is assigned to the whole request, so this page lists
 *   every session of it (the `sessions` prop, from GET /events/<id>/sessions).
 *   Each links to its own review page, where it can be viewed and edited.
 *
 * The Conversation section is a placeholder until clarification messages
 * exist (Request Clarification isn't built yet).
 */
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { apiGet, apiPost } from '../../lib/api'
import { useAuthStore } from '../../stores/auth'
import { formatDateRange, statusLabel, tabForStatus } from '../../lib/coordinatorDashboard'
import {
  minimumStartDate,
  sessionFromEvent,
  sessionHasInvalidInput,
  sessionPayload,
  validateSession,
} from '../../lib/eventSessions'
import EventSessionFields from '../../components/EventSessionFields.vue'

const props = defineProps({
  event: { type: Object, required: true },
  // Every session of this request the coordinator can see -- all of them,
  // since one coordinator handles the whole request.
  sessions: { type: Array, default: () => [] },
})
const emit = defineEmits(['updated'])

const auth = useAuthStore()
const router = useRouter()

const openPanel = ref(null) // null | 'reject' | 'reassign'
const busy = ref(false)
const error = ref('')
const success = ref('')

const rejectReason = ref('')
const coordinators = ref([])
const coordinatorsLoading = ref(false)
const newCoordinatorId = ref('')
const reassignReason = ref('')

const isUnderReview = computed(() => props.event.status === 'under_review')

function sessionWhen(session) {
  const range = formatDateRange(session.preferred_start_date, session.preferred_end_date)
  const times = [time(session.preferred_start_time), time(session.preferred_end_time)].filter(Boolean).join(' – ')
  return times ? `${range} · ${times}` : range
}
// Past events (completed / cancelled / rejected) have nothing left to hand over.
const canReassign = computed(() => ['under_review', 'approved', 'planning', 'confirmed'].includes(props.event.status))
const otherCoordinators = computed(() => coordinators.value.filter((c) => c.id !== auth.profile?.id))

// Same status window as rule_event_edit's coordinator branch on the backend.
const canEdit = computed(() => ['under_review', 'planning'].includes(props.event.status))
const editing = ref(false)
const editForm = reactive({ name: '', description: '', purpose: '', session: null })
const editErrors = reactive({})
const minimumDate = minimumStartDate()
const editHasInvalidInput = computed(() => Boolean(
  editForm.session && sessionHasInvalidInput(editForm.session, minimumDate),
))

const LABELS = {
  wheelchair_access: 'Wheelchair access',
  lift_access: 'Lift access',
  removable_seats: 'Removable seats',
  extra_legroom_seats: 'Seats with extra legroom',
  microphone: 'Microphones',
  projector: 'Projectors',
  screen: 'Screens',
  wifi: 'WiFi',
}

function describeItems(items) {
  if (!items?.length) return 'None specified'
  return items
    .map((entry) => {
      const label = LABELS[entry.item] ?? entry.item
      const quantity = entry.quantity && entry.item !== 'wifi' ? ` × ${entry.quantity}` : ''
      const notes = entry.notes ? ` (${entry.notes})` : ''
      return `${label}${quantity}${notes}`
    })
    .join(', ')
}

function time(value) {
  return value ? value.slice(0, 5) : ''
}

function dateTime(value) {
  return value ? new Date(value).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : 'Not specified'
}

const details = computed(() => {
  const e = props.event
  const times = [time(e.preferred_start_time), time(e.preferred_end_time)].filter(Boolean).join(' – ')
  return [
    { label: 'Preferred Dates', value: formatDateRange(e.preferred_start_date, e.preferred_end_date) },
    { label: 'Time', value: times || 'Not specified' },
    { label: 'Expected Attendance', value: e.expected_attendance ?? 'Not specified' },
    { label: 'Description', value: e.description || 'Not provided', block: true },
    { label: 'Purpose', value: e.purpose || 'Not provided', block: true },
    { label: 'Room Layout', value: e.room_layout ? statusLabel(e.room_layout) : 'Not specified' },
    { label: 'Accessibility Needs', value: describeItems(e.accessibility_needs) },
    { label: 'Equipment', value: describeItems(e.equipment_needed?.equipment) },
    { label: 'Registration Needed', value: e.registration_needs ? 'Yes' : 'No' },
    ...(e.registration_needs
      ? [{ label: 'Registration Period', value: `${dateTime(e.registration_start_datetime)} – ${dateTime(e.registration_end_datetime)}` }]
      : []),
    { label: 'Special Requests', value: e.special_requests || 'None', block: Boolean(e.special_requests) },
  ]
})

function startEditing() {
  error.value = ''
  success.value = ''
  openPanel.value = null
  editForm.name = props.event.name || ''
  editForm.description = props.event.description || ''
  editForm.purpose = props.event.purpose || ''
  editForm.session = sessionFromEvent(props.event)
  Object.keys(editErrors).forEach((field) => delete editErrors[field])
  editing.value = true
}

function cancelEditing() {
  editing.value = false
  editForm.session = null
  error.value = ''
}

function validateEdit() {
  Object.keys(editErrors).forEach((field) => delete editErrors[field])
  if (!editForm.name.trim()) editErrors.name = 'Event name is required.'
  if (!editForm.description.trim()) editErrors.description = 'Description is required.'
  if (!editForm.purpose.trim()) editErrors.purpose = 'Purpose is required.'
  const sessionIsValid = validateSession(editForm.session, minimumDate)
  return Object.keys(editErrors).length === 0 && sessionIsValid
}

function saveEdits() {
  error.value = ''
  success.value = ''
  if (!validateEdit()) return
  return run(async () => {
    // sessionPayload carries the session's id for the organiser's draft
    // endpoint; the edit endpoint is already addressed by id, so drop it.
    const { id, ...sessionFields } = sessionPayload(editForm.session)
    const updated = await apiPost(`/events/${props.event.id}`, {
      name: editForm.name,
      description: editForm.description,
      purpose: editForm.purpose,
      ...sessionFields,
    })
    editing.value = false
    editForm.session = null
    success.value = 'Event details updated.'
    emit('updated', updated)
  })
}

// Moving to another session of the request reuses this component with a new
// `event`; drop anything half-done on the previous session.
watch(() => props.event.id, () => {
  editing.value = false
  editForm.session = null
  openPanel.value = null
  error.value = ''
  success.value = ''
})

function togglePanel(name) {
  error.value = ''
  success.value = ''
  openPanel.value = openPanel.value === name ? null : name
  if (openPanel.value === 'reassign' && coordinators.value.length === 0) loadCoordinators()
}

async function loadCoordinators() {
  coordinatorsLoading.value = true
  try {
    coordinators.value = await apiGet('/events/coordinators')
  } catch (requestError) {
    error.value = `Couldn't load coordinators: ${requestError.message}`
  } finally {
    coordinatorsLoading.value = false
  }
}

async function run(action) {
  busy.value = true
  error.value = ''
  success.value = ''
  try {
    await action()
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    busy.value = false
  }
}

function approve() {
  return run(async () => {
    const updated = await apiPost(`/events/${props.event.id}/approve`, {})
    openPanel.value = null
    success.value = 'Request approved -- it is now in your In Planning tab.'
    emit('updated', updated)
  })
}

function reject() {
  if (!rejectReason.value.trim()) {
    error.value = 'Please give the organiser a reason for rejecting.'
    return
  }
  return run(async () => {
    const updated = await apiPost(`/events/${props.event.id}/reject`, { reason: rejectReason.value.trim() })
    openPanel.value = null
    rejectReason.value = ''
    success.value = 'Request rejected. The organiser can revise and resubmit it.'
    emit('updated', updated)
  })
}

function reassign() {
  if (!newCoordinatorId.value) {
    error.value = 'Choose a coordinator to hand this event to.'
    return
  }
  return run(async () => {
    await apiPost(`/events/${props.event.id}/reassign-coordinator`, {
      new_coordinator_id: newCoordinatorId.value,
      reason: reassignReason.value.trim() || undefined,
    })
    // No longer ours -- back to the dashboard tab the event was listed under.
    router.push({ name: 'dashboard', query: { tab: tabForStatus(props.event.status) ?? 'needsReview' } })
  })
}
</script>

<template>
  <div class="review">
    <div class="title-row">
      <h1>{{ event.name }}</h1>
      <span class="status" :class="`status-${event.status}`">{{ statusLabel(event.status) }}</span>
    </div>

    <section aria-labelledby="conversation-heading" class="stack">
      <div>
        <h2 id="conversation-heading">Conversation</h2>
        <p class="muted small">Clarification messages between you and the organiser will appear here.</p>
      </div>
      <p class="note">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
          stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" />
        </svg>
        No messages yet.
      </p>
    </section>

    <section v-if="sessions.length > 1" class="card" aria-labelledby="sessions-heading">
      <h2 id="sessions-heading">Sessions in this Request</h2>
      <p class="muted small">You're the coordinator for every session. Open one to review or edit it.</p>
      <ul class="session-list">
        <li v-for="(session, index) in sessions" :key="session.id" :class="{ current: session.id === event.id }">
          <router-link v-if="session.id !== event.id" :to="`/events/${session.id}`" class="session-link">
            Session {{ index + 1 }}
          </router-link>
          <span v-else class="session-link" aria-current="page">Session {{ index + 1 }} (this one)</span>
          <span class="muted small">{{ sessionWhen(session) }}</span>
          <span class="status" :class="`status-${session.status}`">{{ statusLabel(session.status) }}</span>
        </li>
      </ul>
    </section>

    <section class="card" aria-labelledby="details-heading">
      <div class="card-heading">
        <h2 id="details-heading">Event Details</h2>
        <button v-if="canEdit && !editing" type="button" class="btn small neutral" :disabled="busy" @click="startEditing">
          Edit Details
        </button>
      </div>

      <form v-if="editing" class="edit-form" novalidate @submit.prevent="saveEdits">
        <label :class="{ invalid: editErrors.name }">Event name
          <input v-model.trim="editForm.name" @input="delete editErrors.name" />
          <span v-if="editErrors.name" class="field-error">{{ editErrors.name }}</span>
        </label>
        <label :class="{ invalid: editErrors.description }">Description
          <textarea v-model.trim="editForm.description" rows="3" @input="delete editErrors.description" />
          <span v-if="editErrors.description" class="field-error">{{ editErrors.description }}</span>
        </label>
        <label :class="{ invalid: editErrors.purpose }">Purpose
          <textarea v-model.trim="editForm.purpose" rows="3" @input="delete editErrors.purpose" />
          <span v-if="editErrors.purpose" class="field-error">{{ editErrors.purpose }}</span>
        </label>
        <EventSessionFields :session="editForm.session" :index="0" :minimum-date="minimumDate" title="Session details" />
        <div class="panel-actions">
          <button type="submit" class="btn small primary" :disabled="busy || editHasInvalidInput">
            {{ busy ? 'Saving...' : 'Save Changes' }}
          </button>
          <button type="button" class="btn small neutral" :disabled="busy" @click="cancelEditing">Cancel</button>
        </div>
      </form>

      <template v-else>
        <div v-for="row in details" :key="row.label" class="detail-row" :class="{ block: row.block }">
          <span class="muted">{{ row.label }}</span>
          <span class="value">{{ row.value }}</span>
        </div>
      </template>
    </section>

    <section class="decision" aria-labelledby="decision-heading">
      <h2 id="decision-heading">Your Decision</h2>

      <p v-if="!isUnderReview" class="muted">
        This request is {{ statusLabel(event.status).toLowerCase() }}, so there's nothing to approve or reject.
      </p>

      <p v-if="editing" class="muted small">Save or cancel your edits before making a decision.</p>

      <div class="buttons">
        <template v-if="isUnderReview">
          <button type="button" class="btn approve" :disabled="busy || editing" @click="approve">
            {{ busy && !openPanel ? 'Approving...' : 'Approve Request' }}
          </button>
          <button type="button" class="btn reject" :aria-expanded="openPanel === 'reject'" :disabled="busy || editing"
            @click="togglePanel('reject')">
            Reject Request
          </button>
        </template>
        <button v-if="canReassign" type="button" class="btn neutral" :aria-expanded="openPanel === 'reassign'"
          :disabled="busy || editing" @click="togglePanel('reassign')">
          Reassign Coordinator
        </button>
      </div>

      <form v-if="openPanel === 'reject'" class="panel panel-reject" @submit.prevent="reject">
        <label for="reject-reason">Reason for rejecting</label>
        <textarea id="reject-reason" v-model="rejectReason" rows="3"
          placeholder="Tell the organiser why, so they know what to change before resubmitting." />
        <div class="panel-actions">
          <button type="submit" class="btn small reject-solid" :disabled="busy">
            {{ busy ? 'Rejecting...' : 'Confirm Rejection' }}
          </button>
          <button type="button" class="btn small neutral" :disabled="busy" @click="togglePanel('reject')">Cancel</button>
        </div>
      </form>

      <form v-if="openPanel === 'reassign'" class="panel" @submit.prevent="reassign">
        <label for="reassign-to">Reassign to</label>
        <p v-if="coordinatorsLoading" class="muted small">Loading coordinators...</p>
        <select v-else id="reassign-to" v-model="newCoordinatorId">
          <option value="" disabled>Choose a coordinator</option>
          <option v-for="c in otherCoordinators" :key="c.id" :value="c.id">{{ c.name }} ({{ c.email }})</option>
        </select>
        <label for="reassign-reason">Reason <span class="muted">(optional)</span></label>
        <input id="reassign-reason" v-model="reassignReason" type="text" placeholder="e.g. on leave that week" />
        <p class="muted small">Agree the handover with them first. Once confirmed, the event leaves your dashboard.</p>
        <div class="panel-actions">
          <button type="submit" class="btn small primary" :disabled="busy || coordinatorsLoading">
            {{ busy ? 'Reassigning...' : 'Confirm Reassignment' }}
          </button>
          <button type="button" class="btn small neutral" :disabled="busy" @click="togglePanel('reassign')">Cancel</button>
        </div>
      </form>

      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <p v-if="success" class="success" role="status">{{ success }}</p>
    </section>
  </div>
</template>

<style scoped>
.review { display: flex; flex-direction: column; gap: 18px; }
.stack { display: flex; flex-direction: column; gap: 10px; }
.title-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
h1 { margin: 0; font-size: 22px; color: #1f1f1f; }
h2 { margin: 0 0 4px; font-size: 15px; color: #222; }
.muted { color: #6b6b6b; }
.small { font-size: 13px; margin: 0; }

.status { font-size: 12px; font-weight: 600; border-radius: 10px; padding: 4px 12px; background: #eee; color: #5a5a5a; }
.status-under_review { background: #f7efe1; color: #8a5a12; }
.status-approved, .status-planning { background: #e7f0fb; color: #1f5fae; }
.status-confirmed { background: #eaf5ec; color: #2f6b3f; }
.status-cancelled, .status-rejected { background: #f5e6e6; color: #a33f3f; }

.note {
  display: flex; align-items: center; gap: 8px; margin: 0;
  background: #f5f5f5; border: 1px solid #ddd; border-radius: 6px; padding: 12px 16px; font-size: 13px; color: #666;
}

.card { background: #fff; border: 1px solid #d0d0d0; border-radius: 6px; padding: 22px 28px; }
.card h2 { margin-bottom: 10px; }
.card-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 4px; }
.card-heading h2 { margin: 0; }
.session-list { list-style: none; margin: 12px 0 0; padding: 0; }
.session-list li {
  display: grid; grid-template-columns: 170px 1fr auto; align-items: center; gap: 12px;
  padding: 10px 0; border-bottom: 1px solid #ececec; font-size: 13px;
}
.session-list li:last-child { border-bottom: none; }
.session-link { font-weight: 600; color: #2a2a2a; }
.session-list li.current .session-link { color: #1f1f1f; }
@media (max-width: 600px) { .session-list li { grid-template-columns: 1fr; gap: 4px; } }
.edit-form { display: flex; flex-direction: column; gap: 12px; margin-top: 12px; }
.edit-form > label { display: grid; gap: 6px; font-size: 13px; font-weight: 600; color: #444; }
.edit-form > label input, .edit-form > label textarea {
  box-sizing: border-box; width: 100%; padding: 10px 12px; border: 1px solid #b8b8b8; border-radius: 4px;
  font: inherit; font-size: 14px; font-weight: 400;
}
.edit-form > label textarea { resize: vertical; }
.edit-form .invalid input, .edit-form .invalid textarea { border-color: #a33f3f; }
.field-error { color: #a33f3f; font-size: 12px; font-weight: 400; }
.detail-row { display: flex; justify-content: space-between; gap: 16px; padding: 10px 0; border-bottom: 1px solid #ececec; font-size: 13px; }
.detail-row:last-child { border-bottom: none; }
.detail-row.block { flex-direction: column; gap: 6px; }
.value { color: #2a2a2a; font-weight: 600; text-align: right; }
.detail-row.block .value { font-weight: 400; text-align: left; line-height: 1.6; white-space: pre-line; }

.decision { display: flex; flex-direction: column; gap: 14px; padding-top: 20px; border-top: 1px solid #dcdcdc; }
.decision h2 { margin: 0; }
.decision > p { margin: 0; }
.buttons { display: flex; flex-wrap: wrap; gap: 12px; }
.btn {
  min-height: 46px; padding: 0 22px; border-radius: 4px; font: inherit; font-size: 14px; font-weight: 700;
  cursor: pointer; background: #fff;
}
.btn:disabled { opacity: .6; cursor: not-allowed; }
.btn:focus-visible { outline: 2px solid #2568e8; outline-offset: 2px; }
.btn.small { min-height: 38px; padding: 0 16px; font-size: 13px; }
.approve { border: none; background: #2f6b3f; color: #fff; }
.reject { border: 1px solid #a33f3f; color: #a33f3f; }
.reject-solid { border: none; background: #a33f3f; color: #fff; }
.neutral { border: 1px solid #b8b8b8; color: #444; }
.primary { border: none; background: #2568e8; color: #fff; }

.panel {
  display: flex; flex-direction: column; gap: 8px;
  background: #f7f7f7; border: 1px solid #c9c9c9; border-radius: 6px; padding: 16px 18px;
}
.panel-reject { background: #fbf1f1; border-color: #d9a3a3; }
.panel label { font-size: 12px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: #6a6a6a; }
.panel textarea, .panel select, .panel input {
  box-sizing: border-box; width: 100%; padding: 10px 12px; border: 1px solid #b8b8b8; border-radius: 4px;
  background: #fff; font: inherit; font-size: 14px;
}
.panel textarea { resize: vertical; }
.panel-actions { display: flex; gap: 10px; margin-top: 4px; }

.error { color: #a33f3f; margin: 0; }
.success { color: #2f6b3f; margin: 0; }

@media (max-width: 600px) {
  .card { padding: 16px; }
  .detail-row { flex-direction: column; gap: 4px; }
  .value { text-align: left; }
  .btn { flex: 1 1 100%; }
}
</style>
