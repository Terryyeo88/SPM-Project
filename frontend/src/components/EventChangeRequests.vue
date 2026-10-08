<script setup>
/**
 * IS-21 Request for Event Change, on the event page.
 *
 *   role="organiser"   -- "Request a Change": the organiser edits a copy of
 *                         one session's details and sends the difference
 *                         (POST /events/<id>/change-requests). Nothing on
 *                         the event changes until the coordinator approves.
 *   role="coordinator" -- the assigned coordinator reviews each pending
 *                         change: Approve (writes it to the event) or Reject
 *                         (reason required).
 *
 * Both see the request's change history (GET /events/<id>/change-requests),
 * newest first, labelled by session when the request has more than one.
 */
import { computed, reactive, ref, watch } from 'vue'
import { apiGet, apiPost } from '../lib/api'
import {
  CHANGE_STATUS_LABELS,
  buildChanges,
  describeChange,
  impactAreas,
  impactsOf,
  isChangeable,
  pendingChangeFor,
  touchesSharedDetails,
} from '../lib/changeRequests'
import {
  minimumStartDate,
  sessionFromEvent,
  sessionHasInvalidInput,
  validateAttendance,
  validateDateRange,
  validateQuantities,
} from '../lib/eventSessions'
import EventSessionFields from './EventSessionFields.vue'

const props = defineProps({
  // The session the page's URL points at.
  event: { type: Object, required: true },
  // Every session of the request the caller can see.
  sessions: { type: Array, default: () => [] },
  role: { type: String, required: true, validator: (value) => ['organiser', 'coordinator'].includes(value) },
})
// `applied` carries the updated session row after an approval.
const emit = defineEmits(['applied'])

const changes = ref([])
const loading = ref(true)
const busy = ref(false)
const error = ref('')
const success = ref('')

const allSessions = computed(() => (props.sessions.length ? props.sessions : [props.event]))
const sessionNumber = (eventId) => allSessions.value.findIndex((session) => session.id === eventId) + 1

// -- organiser: the request form -------------------------------------------
const requesting = ref(false)
const minimumDate = minimumStartDate()
const form = reactive({ sessionId: '', name: '', description: '', purpose: '', session: null, reason: '' })
const targetSession = computed(() => allSessions.value.find((session) => session.id === form.sessionId) || null)
const changeableSessions = computed(() => allSessions.value.filter((session) => isChangeable(session.status)))
const canRequest = computed(() => props.role === 'organiser' && changeableSessions.value.length > 0)
const targetPending = computed(() => pendingChangeFor(changes.value, form.sessionId))
const formHasInvalidInput = computed(() => Boolean(form.session && sessionHasInvalidInput(form.session, minimumDate)))

// Name, description and purpose are shared by every session of the request,
// so they're filled once when the form opens -- switching the session below
// them must not wipe what the organiser has already typed there.
function fillSharedDetails(session) {
  form.name = session.name || ''
  form.description = session.description || ''
  form.purpose = session.purpose || ''
}

function selectSession(sessionId) {
  const session = allSessions.value.find((s) => s.id === sessionId)
  form.sessionId = sessionId
  form.session = sessionFromEvent(session)
  // The form starts from the session's CURRENT details, and one of those
  // can already be invalid -- typically a start date that has now passed.
  // That disables Send Change Request (formHasInvalidInput), and the
  // as-you-type messages only appear once a field is edited, so flag it now
  // or the button is greyed out with no reason given.
  validateDateRange(form.session, minimumDate)
  validateAttendance(form.session)
  validateQuantities(form.session)
}

function startRequest() {
  error.value = ''
  success.value = ''
  const preferred = isChangeable(props.event.status) ? props.event.id : changeableSessions.value[0].id
  fillSharedDetails(allSessions.value.find((s) => s.id === preferred))
  selectSession(preferred)
  form.reason = ''
  requesting.value = true
}

function cancelRequest() {
  requesting.value = false
  form.session = null
  error.value = ''
}

async function submitRequest() {
  error.value = ''
  success.value = ''
  if (!form.name.trim() || !form.description.trim() || !form.purpose.trim()) {
    error.value = 'Event name, description and purpose cannot be blank.'
    return
  }
  const requested = buildChanges(targetSession.value, form)
  if (Object.keys(requested).length === 0) {
    error.value = 'Change at least one detail before sending the request.'
    return
  }
  await run(async () => {
    await apiPost(`/events/${form.sessionId}/change-requests`, {
      changes: requested,
      reason: form.reason.trim() || undefined,
    })
    requesting.value = false
    form.session = null
    success.value = 'Change request sent. The coordinator will review it; the event keeps its current details until then.'
    await loadChanges()
  })
}

// -- coordinator: review ----------------------------------------------------
const rejectingId = ref(null)
const rejectReason = ref('')

// Changes that would disturb arrangements already made (venue booking,
// registrations, equipment, technical support) need the coordinator to tick
// "reviewed" first; the areas they saw are sent, so the backend can refuse
// if something new turned up since the page loaded.
const acknowledged = reactive({})
const needsAcknowledgement = (change) => impactsOf(change).length > 0

function approve(change) {
  return run(async () => {
    const areas = needsAcknowledgement(change) && acknowledged[change.event_change_req_id] ? impactAreas(change) : []
    try {
      const result = await apiPost(`/events/${change.event_id}/change-requests/${change.event_change_req_id}/approve`, {
        acknowledge_impacts: areas,
      })
      success.value = 'Change approved and applied to the event.'
      await loadChanges()
      emit('applied', result.event)
    } catch (requestError) {
      if (requestError.code === 'change_impact_unacknowledged') {
        // Something new is affected: show the up-to-date list to re-review.
        delete acknowledged[change.event_change_req_id]
        await loadChanges()
      }
      throw requestError
    }
  })
}

function startReject(change) {
  error.value = ''
  success.value = ''
  rejectingId.value = change.event_change_req_id
  rejectReason.value = ''
}

function reject(change) {
  if (!rejectReason.value.trim()) {
    error.value = 'Please give the organiser a reason for rejecting this change.'
    return
  }
  return run(async () => {
    await apiPost(`/events/${change.event_id}/change-requests/${change.event_change_req_id}/reject`, { reason: rejectReason.value.trim() })
    rejectingId.value = null
    success.value = 'Change rejected. The event keeps its current details.'
    await loadChanges()
  })
}

// -- shared ------------------------------------------------------------------
async function run(action) {
  busy.value = true
  try {
    await action()
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    busy.value = false
  }
}

async function loadChanges() {
  try {
    changes.value = await apiGet(`/events/${props.event.id}/change-requests`)
  } catch (requestError) {
    error.value = `Couldn't load change requests: ${requestError.message}`
  } finally {
    loading.value = false
  }
}

function when(value) {
  return value ? new Date(value).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : ''
}

const pendingCount = computed(() => changes.value.filter((change) => change.status === 'pending').length)

watch(() => props.event.id, () => {
  requesting.value = false
  rejectingId.value = null
  error.value = ''
  success.value = ''
  loading.value = true
  loadChanges()
}, { immediate: true })
</script>

<template>
  <section class="card change-requests" aria-labelledby="change-requests-heading">
    <div class="card-header">
      <div>
        <h2 id="change-requests-heading" class="card-title">Change Requests</h2>
        <p class="muted small">
          <template v-if="role === 'organiser'">
            Submitted details can't be edited directly. Request a change and the coordinator will review it first.
          </template>
          <template v-else>
            {{ pendingCount ? `${pendingCount} change request(s) waiting for your review.` : 'Changes the organiser asks for appear here for your review.' }}
          </template>
        </p>
      </div>
      <button v-if="canRequest && !requesting" type="button" class="btn btn-outline" :disabled="busy" @click="startRequest">
        Request a Change
      </button>
    </div>

    <form v-if="requesting && form.session" class="request-form" novalidate @submit.prevent="submitRequest">
      <template v-if="!targetPending">
        <p class="muted small">
          Edit the details you want changed and leave the rest as they are. Event name, description and purpose
          apply to every session of this request.
        </p>
        <label class="field">
          <span class="field-label">Event Name</span>
          <input v-model.trim="form.name" class="input" type="text" />
        </label>
        <label class="field">
          <span class="field-label">Description</span>
          <textarea v-model.trim="form.description" class="input" rows="3" />
        </label>
        <label class="field">
          <span class="field-label">Purpose of the Event</span>
          <textarea v-model.trim="form.purpose" class="input" rows="3" />
        </label>
      </template>

      <label v-if="changeableSessions.length > 1" class="field">
        <span class="field-label">Session to change</span>
        <select class="input" :value="form.sessionId" @change="selectSession($event.target.value)">
          <option v-for="session in changeableSessions" :key="session.id" :value="session.id">
            Session {{ sessionNumber(session.id) }} ({{ session.preferred_start_date || 'no date' }})
          </option>
        </select>
      </label>

      <p v-if="targetPending" class="notice" role="note">
        This session already has a change waiting for review. You can send another once the coordinator has reviewed it.
      </p>

      <template v-else>
        <EventSessionFields :session="form.session" :index="0" :minimum-date="minimumDate" title="Session details" />
        <label class="field">
          <span class="field-label">Reason for the change <span class="optional">(optional)</span></span>
          <textarea v-model="form.reason" class="input" rows="2" placeholder="e.g. more people have signed up than expected" />
        </label>
      </template>

      <div class="actions">
        <button v-if="!targetPending" type="submit" class="btn btn-primary" :disabled="busy || formHasInvalidInput">
          {{ busy ? 'Sending...' : 'Send Change Request' }}
        </button>
        <button type="button" class="btn btn-outline" :disabled="busy" @click="cancelRequest">Cancel</button>
      </div>
      <p v-if="!targetPending && formHasInvalidInput" class="muted small" role="status">
        Fix the highlighted details above to send the request -- including any current detail that's no
        longer valid, such as a start date that has already passed.
      </p>
    </form>

    <p v-if="error" class="message error" role="alert">{{ error }}</p>
    <p v-if="success" class="message success" role="status">{{ success }}</p>

    <p v-if="loading" class="muted small">Loading change requests...</p>
    <p v-else-if="!changes.length" class="muted small">No changes have been requested.</p>

    <ul v-else class="change-list">
      <li v-for="change in changes" :key="change.event_change_req_id" class="change" :class="`change-${change.status}`">
        <div class="change-header">
          <span class="change-title">
            <template v-if="allSessions.length > 1">Session {{ sessionNumber(change.event_id) || '?' }} · </template>
            Requested {{ when(change.created_at) }}
          </span>
          <span class="badge" :class="`badge-${change.status}`">{{ CHANGE_STATUS_LABELS[change.status] ?? change.status }}</span>
        </div>

        <table class="diff">
          <thead><tr><th scope="col">Detail</th><th scope="col">Current</th><th scope="col">Requested</th></tr></thead>
          <tbody>
            <tr v-for="rowItem in describeChange(change)" :key="rowItem.field">
              <th scope="row">{{ rowItem.label }}</th>
              <td>{{ rowItem.from }}</td>
              <td class="to">{{ rowItem.to }}</td>
            </tr>
          </tbody>
        </table>

        <p v-if="change.reason" class="small"><strong>Organiser's reason:</strong> {{ change.reason }}</p>
        <p v-if="change.status !== 'pending' && change.review_comment" class="small">
          <strong>{{ change.status === 'rejected' ? 'Reason for rejection' : 'Coordinator comment' }}:</strong>
          {{ change.review_comment }}
          <span v-if="change.reviewed_at" class="muted"> ({{ when(change.reviewed_at) }})</span>
        </p>
        <p v-if="change.status === 'pending' && touchesSharedDetails(change)" class="muted small">
          Approving changes the name, description or purpose of every session in this request.
        </p>

        <div v-if="change.status === 'pending' && impactsOf(change).length" class="impact" role="note">
          <span class="impact-title">
            {{ role === 'coordinator' ? 'Approving this affects arrangements already made' : 'The coordinator will need to review its effect on' }}
          </span>
          <ul>
            <li v-for="impact in impactsOf(change)" :key="impact.area + (impact.booking_id || '')" :class="`impact-${impact.severity}`">
              <strong>{{ impact.title }}</strong>
              <span class="impact-kind">{{ impact.severity === 'conflict' ? 'Conflict' : 'Check manually' }}</span>
              <ul>
                <li v-for="issue in impact.issues" :key="issue">{{ issue }}</li>
              </ul>
            </li>
          </ul>
          <label v-if="role === 'coordinator'" class="check">
            <input v-model="acknowledged[change.event_change_req_id]" type="checkbox" />
            I've reviewed these and will follow up on them
          </label>
        </div>

        <div v-if="role === 'coordinator' && change.status === 'pending'" class="review">
          <template v-if="rejectingId !== change.event_change_req_id">
            <button type="button" class="btn btn-primary"
              :disabled="busy || (needsAcknowledgement(change) && !acknowledged[change.event_change_req_id])" @click="approve(change)">
              Approve Change
            </button>
            <button type="button" class="btn btn-danger" :disabled="busy" @click="startReject(change)">Reject Change</button>
          </template>
          <form v-else class="reject-form" @submit.prevent="reject(change)">
            <label class="field">
              <span class="field-label">Reason for rejecting</span>
              <textarea v-model="rejectReason" class="input" rows="2" placeholder="Tell the organiser why this change can't be made." />
            </label>
            <div class="actions">
              <button type="submit" class="btn btn-danger" :disabled="busy">{{ busy ? 'Rejecting...' : 'Confirm Rejection' }}</button>
              <button type="button" class="btn btn-outline" :disabled="busy" @click="rejectingId = null">Cancel</button>
            </div>
          </form>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped src="../styles/event-form.css"></style>
<style scoped>
.card-header { align-items: flex-start; }
.muted { color: #6b6b6b; }
.small { font-size: 13px; margin: 4px 0 0; }
.notice { margin: 0; padding: 10px 14px; border-radius: 4px; background: #f7efe1; color: #8a5a12; font-size: 13px; }
.request-form, .reject-form { display: flex; flex-direction: column; gap: 14px; }
.actions, .review { display: flex; flex-wrap: wrap; gap: 10px; }
.message { margin: 0; font-size: 14px; }
.error { color: #b42318; }
.success { color: #2f6b3f; }

.change-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 14px; }
.change { border: 1px solid #d0d0d0; border-radius: 6px; padding: 14px 16px; display: flex; flex-direction: column; gap: 8px; }
.change-pending { border-color: #d9b779; }
.change-header { display: flex; justify-content: space-between; align-items: center; gap: 12px; flex-wrap: wrap; }
.change-title { font-size: 13px; font-weight: 600; color: #333; }
.badge { font-size: 12px; font-weight: 600; border-radius: 10px; padding: 3px 10px; background: #eee; color: #5a5a5a; }
.badge-pending { background: #f7efe1; color: #8a5a12; }
.badge-approved { background: #eaf5ec; color: #2f6b3f; }
.badge-rejected { background: #f5e6e6; color: #a33f3f; }

.impact { display: flex; flex-direction: column; gap: 8px; padding: 12px 14px; border-left: 3px solid #b7791f; border-radius: 4px; background: #fdf6e9; font-size: 13px; }
.impact-title { font-size: 12px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; color: #8a5a12; }
.impact ul { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 6px; }
.impact > ul { padding-left: 0; list-style: none; }
.impact-kind { margin-left: 8px; font-size: 11px; font-weight: 600; border-radius: 8px; padding: 1px 8px; background: #eee; color: #5a5a5a; }
.impact-conflict .impact-kind { background: #f5e6e6; color: #a33f3f; }
.diff { width: 100%; border-collapse: collapse; font-size: 13px; }
.diff th, .diff td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #ececec; vertical-align: top; overflow-wrap: anywhere; }
.diff thead th { font-size: 12px; color: #6a6a6a; font-weight: 600; }
.diff tbody th { font-weight: 600; color: #444; width: 30%; }
.diff .to { font-weight: 600; color: #1f1f1f; }

@media (max-width: 640px) {
  .card-header { flex-direction: column; }
  .actions .btn, .review .btn { flex: 1 1 100%; }
}
</style>
