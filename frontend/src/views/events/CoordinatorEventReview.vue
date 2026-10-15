<script setup>
/**
 * The assigned coordinator's view of an event request, laid out after the
 * "Event Review -- Coordinator" wireframe: status, conversation, the
 * submitted details read-only, then "Your Decision".
 *
 * Decisions:
 *   Approve  -> POST /events/<id>/approve   (under_review -> approved)
 *   Reject   -> POST /events/<id>/reject    (under_review -> rejected, reason required)
 *   Both decide the whole request: every session still under review moves
 *   together, so the organiser resubmits a rejected request as one.
 *   Start Planning -> POST /events/<id>/start-planning (approved -> planning,
 *               every approved session of the request, like Approve). Venue requests open only from planning
 *               (rule_venue_booking_create), so the coordinator moves the
 *               event there themselves when they're ready to arrange it.
 *   Cancel   -> POST /events/<id>/cancel    (approved / planning / confirmed ->
 *               cancelled, reason required; IS-39's route, this button added
 *               with Release Equipment on Cancel). Cancels THIS session only.
 *               The backend then releases the session's reserved equipment
 *               and says how many units it freed.
 *   No Reassign here: since the Week 9 clarification only the Event
 *   Coordinator Lead reassigns ("it is now manually assigned by the lead"),
 *   from the Lead dashboard -- rule_event_reassign_coordinator.
 *
 * Editing:
 *   Edit Details -> POST /events/<id>. Once a request is submitted only the
 *               assigned coordinator may change it (IS-31), at any point
 *               until it's completed or cancelled (rule_event_edit).
 *               Each edit is recorded in the event's Change History. This edits
 *               THIS session only -- each session is its own event record,
 *               reviewed on its own -- with the same form and as-you-type
 *               validation the organiser uses (EventSessionFields). Name,
 *               description and purpose are shared, so the backend copies
 *               those to the other sessions.
 *   IS-9:       Save first asks POST /events/<id>/update-preview what the
 *               update would do. A significant change (date, time,
 *               attendance, layout, equipment), one touching arrangements
 *               already made (venue, equipment, technical support,
 *               registrations), or any change to a confirmed event (it goes
 *               back to planning) is shown for review before it's saved;
 *               affected arrangements must be acknowledged (lib/eventUpdates).
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
import { apiPost } from '../../lib/api'
import { formatDateRange, statusLabel } from '../../lib/coordinatorDashboard'
import {
  minimumStartDate,
  sessionFromEvent,
  sessionHasInvalidInput,
  sessionPayload,
  validateSession,
} from '../../lib/eventSessions'
import {
  SIGNIFICANCE_LABELS,
  describePreviewChanges,
  impactsOfPreview,
  isNoChange,
  needsReview,
  previewImpactAreas,
  savedMessage,
} from '../../lib/eventUpdates'
import EventSessionFields from '../../components/EventSessionFields.vue'

const props = defineProps({
  event: { type: Object, required: true },
  // Every session of this request the coordinator can see -- all of them,
  // since one coordinator handles the whole request.
  sessions: { type: Array, default: () => [] },
})
const emit = defineEmits(['updated'])

const openPanel = ref(null) // null | 'reject' | 'cancel'
const busy = ref(false)
const error = ref('')
const success = ref('')

const rejectReason = ref('')
const cancelReason = ref('')

const isUnderReview = computed(() => props.event.status === 'under_review')
const isApproved = computed(() => props.event.status === 'approved')

function sessionWhen(session) {
  const range = formatDateRange(session.preferred_start_date, session.preferred_end_date)
  const times = [time(session.preferred_start_time), time(session.preferred_end_time)].filter(Boolean).join(' – ')
  return times ? `${range} · ${times}` : range
}
// Same status window as rule_event_cancel (_CANCELLABLE_STATUSES) on the
// backend: after approval, until the event is completed.
const canCancel = computed(() => ['approved', 'planning', 'confirmed'].includes(props.event.status))

// Same status window as rule_event_edit's coordinator branch on the backend:
// any time, until the event is completed or cancelled.
const canEdit = computed(() => !['completed', 'cancelled'].includes(props.event.status))
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
  review.value = null
  error.value = ''
}

// IS-9: the previewed update awaiting the coordinator's go-ahead, and
// whether they've ticked "reviewed" for the arrangements it touches.
const review = ref(null) // null | { body, preview }
const reviewAcknowledged = ref(false)
const reviewImpacts = computed(() => impactsOfPreview(review.value?.preview))
const reviewChanges = computed(() => describePreviewChanges(review.value?.preview))

function validateEdit() {
  Object.keys(editErrors).forEach((field) => delete editErrors[field])
  if (!editForm.name.trim()) editErrors.name = 'Event name is required.'
  if (!editForm.description.trim()) editErrors.description = 'Description is required.'
  if (!editForm.purpose.trim()) editErrors.purpose = 'Purpose is required.'
  const sessionIsValid = validateSession(editForm.session, minimumDate)
  return Object.keys(editErrors).length === 0 && sessionIsValid
}

function editBody() {
  // sessionPayload carries the session's id for the organiser's draft
  // endpoint; the edit endpoint is already addressed by id, so drop it.
  const { id, ...sessionFields } = sessionPayload(editForm.session)
  return {
    name: editForm.name,
    description: editForm.description,
    purpose: editForm.purpose,
    ...sessionFields,
  }
}

async function previewEdits(body) {
  const preview = await apiPost(`/events/${props.event.id}/update-preview`, body)
  if (isNoChange(preview)) {
    editing.value = false
    editForm.session = null
    success.value = 'Nothing was changed.'
    return null
  }
  return preview
}

function saveEdits() {
  error.value = ''
  success.value = ''
  if (!validateEdit()) return
  return run(async () => {
    const body = editBody()
    const preview = await previewEdits(body)
    if (!preview) return
    if (needsReview(preview)) {
      review.value = { body, preview }
      reviewAcknowledged.value = false
      return
    }
    await commitEdits(body, [])
  })
}

function confirmReviewedEdits() {
  return run(async () => {
    const { body, preview } = review.value
    try {
      await commitEdits(body, reviewAcknowledged.value ? previewImpactAreas(preview) : [])
    } catch (requestError) {
      if (requestError.code === 'change_impact_unacknowledged') {
        // Something new is affected since the preview: show it again.
        const refreshed = await previewEdits(body)
        review.value = refreshed ? { body, preview: refreshed } : null
        reviewAcknowledged.value = false
      }
      throw requestError
    }
  })
}

async function commitEdits(body, acknowledged) {
  const previousStatus = props.event.status
  const updated = await apiPost(`/events/${props.event.id}`, { ...body, acknowledge_impacts: acknowledged })
  editing.value = false
  editForm.session = null
  review.value = null
  success.value = savedMessage(previousStatus, updated)
  emit('updated', updated)
}

// Moving to another session of the request reuses this component with a new
// `event`; drop anything half-done on the previous session.
watch(() => props.event.id, () => {
  editing.value = false
  editForm.session = null
  review.value = null
  openPanel.value = null
  error.value = ''
  success.value = ''
})

function togglePanel(name) {
  error.value = ''
  success.value = ''
  openPanel.value = openPanel.value === name ? null : name
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
    success.value = 'Request approved (every session under review) -- it is now in your In Planning tab.'
    emit('updated', updated)
  })
}

function startPlanning() {
  return run(async () => {
    const updated = await apiPost(`/events/${props.event.id}/start-planning`, {})
    openPanel.value = null
    success.value = 'Request moved to In Planning (every approved session). You can now request a venue and equipment.'
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
    success.value = 'Request rejected (every session under review). The organiser can revise and resubmit it.'
    emit('updated', updated)
  })
}

function cancelEvent() {
  if (!cancelReason.value.trim()) {
    error.value = 'Please give a reason for cancelling.'
    return
  }
  return run(async () => {
    const updated = await apiPost(`/events/${props.event.id}/cancel`, { reason: cancelReason.value.trim() })
    openPanel.value = null
    cancelReason.value = ''
    const released = updated.released_equipment_units ?? 0
    const unitWord = released === 1 ? 'unit' : 'units'
    success.value = released
      ? `Session cancelled. ${released} reserved equipment ${unitWord} released for other events.`
      : 'Session cancelled.'
    emit('updated', updated)
  })
}
</script>

<template>
  <div class="review">
    <div class="title-row">
      <h1>{{ event.name }}</h1>
      <span class="status" :class="`status-${event.status}`">{{ statusLabel(event.status) }}</span>
    </div>
    <dl class="event-summary">
      <dt>Description</dt><dd>{{ event.description || 'Not provided' }}</dd>
      <dt>Purpose</dt><dd>{{ event.purpose || 'Not provided' }}</dd>
    </dl>

    <section class="decision" aria-labelledby="decision-heading">
      <h2 id="decision-heading">Your Decision</h2>

      <p v-if="!isUnderReview" class="muted">
        This request is {{ statusLabel(event.status).toLowerCase() }}, so there's nothing to approve or reject.
      </p>

      <p v-if="isApproved" class="muted small">
        Start planning when you're ready to request a venue or equipment.
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
        <button v-if="isApproved" type="button" class="btn approve" :disabled="busy || editing" @click="startPlanning">
          {{ busy && !openPanel ? 'Starting...' : 'Start Planning' }}
        </button>
        <button v-if="canCancel" type="button" class="btn reject" :aria-expanded="openPanel === 'cancel'"
          :disabled="busy || editing" @click="togglePanel('cancel')">
          Cancel Event
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

      <form v-if="openPanel === 'cancel'" class="panel panel-reject" @submit.prevent="cancelEvent">
        <label for="cancel-reason">Reason for cancelling</label>
        <textarea id="cancel-reason" v-model="cancelReason" rows="3"
          placeholder="e.g. no suitable venue for the requested date. The organiser will see this." />
        <p class="muted small">
          This cancels this session only. Any equipment reserved for it is released for other events.
          It can't be undone.
        </p>
        <div class="panel-actions">
          <button type="submit" class="btn small reject-solid" :disabled="busy">
            {{ busy ? 'Cancelling...' : 'Confirm Cancellation' }}
          </button>
          <button type="button" class="btn small neutral" :disabled="busy" @click="togglePanel('cancel')">
            Keep Event
          </button>
        </div>
      </form>

      <p v-if="error && !review" class="error" role="alert">{{ error }}</p>
      <p v-if="success" class="success" role="status">{{ success }}</p>
    </section>

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

      <div v-if="editing && review" class="update-review" role="region" aria-labelledby="update-review-heading">
        <div class="update-review-heading">
          <h3 id="update-review-heading">Review before saving</h3>
          <span v-if="review.preview.significance" class="significance"
            :class="`significance-${review.preview.significance}`">
            {{ SIGNIFICANCE_LABELS[review.preview.significance] }}
          </span>
        </div>
        <table class="diff">
          <thead><tr><th scope="col">Detail</th><th scope="col">Current</th><th scope="col">New</th></tr></thead>
          <tbody>
            <tr v-for="change in reviewChanges" :key="change.field" :class="{ significant: change.significant }">
              <th scope="row">{{ change.label }}</th>
              <td>{{ change.from }}</td>
              <td class="to">{{ change.to }}</td>
            </tr>
          </tbody>
        </table>

        <p v-if="review.preview.reverts_to_planning" class="notice" role="note">
          This event is confirmed. Saving these changes moves it back to In Planning until you confirm it again.
        </p>

        <div v-if="reviewImpacts.length" class="impact" role="note">
          <span class="impact-title">This affects arrangements already made</span>
          <ul>
            <li v-for="impact in reviewImpacts" :key="impact.area + (impact.booking_id || '')"
              :class="`impact-${impact.severity}`">
              <strong>{{ impact.title }}</strong>
              <span class="impact-kind">{{ impact.severity === 'conflict' ? 'Conflict' : 'Check manually' }}</span>
              <ul>
                <li v-for="issue in impact.issues" :key="issue">{{ issue }}</li>
              </ul>
            </li>
          </ul>
          <p class="muted small">Nothing here is changed or cancelled automatically -- follow up on each one yourself.</p>
          <label class="check">
            <input v-model="reviewAcknowledged" type="checkbox" />
            I've reviewed these and will follow up on them
          </label>
        </div>
        <p v-else class="muted small">No venue booking, equipment, technical support or registration is affected.</p>

        <div class="panel-actions">
          <button type="button" class="btn small primary" :disabled="busy || (reviewImpacts.length > 0 && !reviewAcknowledged)"
            @click="confirmReviewedEdits">
            {{ busy ? 'Saving...' : 'Confirm and Save' }}
          </button>
          <button type="button" class="btn small neutral" :disabled="busy" @click="review = null">Back to Editing</button>
        </div>
        <p v-if="error" class="error" role="alert">{{ error }}</p>
      </div>

      <form v-else-if="editing" class="edit-form" novalidate @submit.prevent="saveEdits">
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
  </div>
</template>

<style scoped>
.review { display: flex; flex-direction: column; gap: 18px; }
.stack { display: flex; flex-direction: column; gap: 10px; }
.title-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
h1 { margin: 0; font-size: 22px; color: #1f1f1f; }
.event-summary { margin: 0; display: grid; grid-template-columns: max-content 1fr; gap: 4px 16px; font-size: 14px; }
.event-summary dt { color: #6a6a6a; }
.event-summary dd { margin: 0; color: #2a2a2a; white-space: pre-line; overflow-wrap: anywhere; }
h2 { margin: 0 0 4px; font-size: 15px; color: #222; }
.muted { color: #6b6b6b; }
.small { font-size: 13px; margin: 0; }

.status { font-size: 12px; font-weight: 600; border-radius: 10px; padding: 4px 12px; background: #eee; color: #5a5a5a; }
.status-draft { color: #5f5f5f; background: #efefef; }
.status-submitted { color: #6b3fa0; background: #f1ebf8; }
.status-under_review { color: #8a6d00; background: #fff4c2; }
.status-approved { color: #1f5a9e; background: #e4eefb; }
.status-planning { color: #2f7a3f; background: #e4f5e8; }
.status-confirmed { color: #0f6e6a; background: #ddf3f1; }
.status-completed { color: #3f4a57; background: #e3e7ec; }
.status-cancelled { color: #a3521b; background: #fcebdd; }
.status-rejected { color: #b42318; background: #fde8e6; }

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

.update-review { display: flex; flex-direction: column; gap: 12px; margin-top: 12px; }
.update-review-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.update-review h3 { margin: 0; font-size: 14px; color: #222; }
.significance { font-size: 12px; font-weight: 600; border-radius: 10px; padding: 3px 10px; background: #eee; color: #5a5a5a; }
.significance-significant { background: #f7efe1; color: #8a5a12; }
.diff { width: 100%; border-collapse: collapse; font-size: 13px; }
.diff th, .diff td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #ececec; vertical-align: top; overflow-wrap: anywhere; }
.diff thead th { font-size: 12px; color: #6a6a6a; font-weight: 600; }
.diff tbody th { font-weight: 600; color: #444; width: 30%; }
.diff tr.significant th { color: #8a5a12; }
.diff .to { font-weight: 600; color: #1f1f1f; }
.notice { margin: 0; padding: 10px 14px; border-radius: 4px; background: #e7f0fb; color: #1f5fae; font-size: 13px; }
.impact { display: flex; flex-direction: column; gap: 8px; padding: 12px 14px; border-left: 3px solid #b7791f; border-radius: 4px; background: #fdf6e9; font-size: 13px; }
.impact-title { font-size: 12px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; color: #8a5a12; }
.impact ul { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 6px; }
.impact > ul { padding-left: 0; list-style: none; }
.impact-kind { margin-left: 8px; font-size: 11px; font-weight: 600; border-radius: 8px; padding: 1px 8px; background: #eee; color: #5a5a5a; }
.impact-conflict .impact-kind { background: #f5e6e6; color: #a33f3f; }
.check { display: flex; align-items: center; gap: 8px; font-weight: 600; color: #444; }

@media (max-width: 600px) {
  .card { padding: 16px; }
  .detail-row { flex-direction: column; gap: 4px; }
  .value { text-align: left; }
  .btn { flex: 1 1 100%; }
}
</style>
