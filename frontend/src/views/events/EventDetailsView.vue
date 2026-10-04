<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiDelete, apiGet, apiPost } from '../../lib/api'
import { useAuthStore } from '../../stores/auth'
import { statusLabel, tabForStatus } from '../../lib/coordinatorDashboard'
import {
  DRAFT_NAME,
  emptySession,
  minimumStartDate,
  sessionFromEvent,
  sessionHasInvalidInput,
  sessionIsComplete,
  sessionPayload,
  validateSession,
} from '../../lib/eventSessions'
import CoordinatorEventReview from './CoordinatorEventReview.vue'
import AppNavBar from '../../components/AppNavBar.vue'
import EventSessionFields from '../../components/EventSessionFields.vue'
import SessionSummaryCard from '../../components/SessionSummaryCard.vue'
import VenueBookingStatus from '../../components/VenueBookingStatus.vue'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
// `event` is the session this URL points at; `group` is every session of
// the same request (rows sharing shared_event_id) the caller may see.
const event = ref(null)
const group = ref(null)
const loading = ref(true)
const saving = ref(false)
const submitting = ref(false)
const deleting = ref(false)
const error = ref('')
const saved = ref(false)
const resubmitted = ref(false)
const errors = reactive({})

const form = reactive({
  name: '',
  description: '',
  purpose: '',
  sessions: [],
})

const minimumDate = minimumStartDate()

// The assigned coordinator came here from their dashboard, so Back returns
// to the dashboard tab matching this event's status; everyone else goes
// back to the events list as before.
// The assigned coordinator gets the review layout (wireframe "Event Review
// -- Coordinator") instead of the organiser's form / read-only view.
const isAssignedCoordinator = computed(() => Boolean(
  event.value && event.value.coordinator_id && event.value.coordinator_id === auth.profile?.id,
))

const backLink = computed(() => {
  const tab = tabForStatus(event.value?.status)
  if (tab && event.value.coordinator_id === auth.profile?.id) {
    return { to: { name: 'dashboard', query: { tab } }, label: 'Back to My Assigned Events' }
  }
  return { to: '/events', label: 'Back to My Event Requests' }
})

const isOwner = computed(() => Boolean(event.value && event.value.organizer_id === auth.profile?.id))
const isDraft = computed(() => event.value?.status === 'draft')

// Every session of the request, on one page. How the organiser edits it:
//   'draft'    -- the whole request: every session together, and sessions
//                 can be added or removed.
//   'rejected' -- the request has rejected session(s). Those are editable
//                 inline; the other sessions (each with its own review
//                 outcome) are shown read-only alongside them. Which
//                 session the URL points at doesn't matter -- it's the
//                 same page for the whole request.
//   'readonly' -- nothing here is the organiser's to edit.
const rejectedSessions = computed(() => (
  isOwner.value && !isDraft.value ? visibleSessions.value.filter((s) => s.status === 'rejected') : []
))
const mode = computed(() => {
  if (!isOwner.value) return 'readonly'
  if (isDraft.value) return 'draft'
  return rejectedSessions.value.length ? 'rejected' : 'readonly'
})
const canEdit = computed(() => mode.value !== 'readonly')

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
  const required = [form.name, form.description, form.purpose]
    .every((value) => String(value ?? '').trim() !== '')
  return required && form.sessions.length > 0
    && form.sessions.every((session) => sessionIsComplete(session, minimumDate))
})

const hasInvalidInput = computed(() => form.sessions.some((session) => sessionHasInvalidInput(session, minimumDate)))

const visibleSessions = computed(() => group.value?.sessions || (event.value ? [event.value] : []))

// In 'rejected' mode: every session in date order, paired with its form
// state when it's one of the editable (rejected) ones.
const sessionEntries = computed(() => visibleSessions.value.map((row, index) => ({
  row,
  index,
  form: form.sessions.find((session) => session.id === row.id) || null,
})))

function populateForm(value, sessions) {
  form.name = value.name === DRAFT_NAME ? '' : value.name || ''
  form.description = value.description || ''
  form.purpose = value.purpose || ''
  form.sessions = sessions.map(sessionFromEvent)
}

function editableSessions() {
  if (mode.value === 'rejected') return rejectedSessions.value
  if (!isDraft.value) return [event.value]
  const drafts = (group.value?.sessions || []).filter((session) => session.status === 'draft')
  return drafts.length ? drafts : [event.value]
}

async function loadEvent() {
  loading.value = true
  error.value = ''
  saved.value = false
  resubmitted.value = false
  try {
    event.value = await apiGet(`/events/${route.params.eventId}`)
    group.value = await apiGet(`/events/${route.params.eventId}/sessions`)
    populateForm(event.value, editableSessions())
  } catch (requestError) {
    event.value = null
    error.value = requestError.message
  } finally {
    loading.value = false
  }
}

function addSession() {
  form.sessions.push(emptySession())
}

function removeSession(index) {
  form.sessions.splice(index, 1)
}

function validateForm() {
  Object.keys(errors).forEach((field) => delete errors[field])
  if (!form.name.trim()) errors.name = 'Event name is required.'
  if (!form.description.trim()) errors.description = 'Description is required.'
  if (!form.purpose.trim()) errors.purpose = 'Purpose is required.'
  // map, not every(): validate every session so all errors show at once.
  const sessionResults = form.sessions.map((session) => validateSession(session, minimumDate))
  return Object.keys(errors).length === 0 && sessionResults.every(Boolean)
}

function payload() {
  return {
    name: form.name,
    description: form.description,
    purpose: form.purpose,
    sessions: form.sessions.map(sessionPayload),
  }
}

// Saving a draft can remove the very session this URL points at (the
// organiser removed it from the form). The request lives on in its other
// sessions, so move the URL to one of those instead of a dead id.
async function applySavedGroup(savedGroup) {
  const ids = savedGroup.sessions.map((session) => session.id)
  if (ids.length && !ids.includes(event.value.id)) {
    await router.replace(`/events/${ids[0]}`)
    return false
  }
  group.value = isDraft.value ? savedGroup : group.value
  event.value = savedGroup.sessions.find((session) => session.id === event.value.id) || event.value
  populateForm(event.value, editableSessions())
  return true
}

async function saveDraft() {
  error.value = ''
  saved.value = false
  if (hasInvalidInput.value) return
  saving.value = true
  try {
    const stayed = await applySavedGroup(await apiPost(`/events/${event.value.id}/draft`, payload()))
    saved.value = stayed
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    saving.value = false
  }
}

// Rejected sessions are saved one at a time (the backend edits a rejected
// session on its own, so its reviewed siblings are never touched), each
// with the shared details from the top of the form.
async function saveRejectedSessions() {
  for (const session of form.sessions) {
    await apiPost(`/events/${session.id}/draft`, {
      name: form.name,
      description: form.description,
      purpose: form.purpose,
      sessions: [sessionPayload(session)],
    })
  }
}

async function saveRejectedChanges() {
  error.value = ''
  saved.value = false
  resubmitted.value = false
  if (hasInvalidInput.value) return
  saving.value = true
  try {
    await saveRejectedSessions()
    await loadEvent()
    saved.value = true
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    saving.value = false
  }
}

// Save the fixes, then send every rejected session back for review in one
// submit -- they return to the coordinator who rejected them. Validated in
// full first, the same as a first submission.
async function resubmitRejected() {
  error.value = ''
  saved.value = false
  resubmitted.value = false
  if (!validateForm()) return
  submitting.value = true
  try {
    await saveRejectedSessions()
    await apiPost(`/events/${form.sessions[0].id}/submit`, {})
    await loadEvent()
    resubmitted.value = true
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    submitting.value = false
  }
}

async function submitEvent() {
  error.value = ''
  saved.value = false
  if (!validateForm()) return
  submitting.value = true
  try {
    const savedGroup = await apiPost(`/events/${event.value.id}/draft`, payload())
    const submitFrom = savedGroup.sessions.some((session) => session.id === event.value.id)
      ? event.value.id
      : savedGroup.sessions[0].id
    // Submitting from any one draft session submits every session of the request.
    await apiPost(`/events/${submitFrom}/submit`, {})
    if (submitFrom !== event.value.id) {
      await router.replace(`/events/${submitFrom}`)
    } else {
      await loadEvent()
    }
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    submitting.value = false
  }
}

async function deleteDraft() {
  const message = form.sessions.length > 1
    ? `Delete this draft event request and all ${form.sessions.length} of its sessions? This cannot be undone.`
    : 'Delete this draft event request? This cannot be undone.'
  if (!window.confirm(message)) return
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

// "Rejected by Alice Tan on 3 Oct 2026, 5:00 pm" (either part may be
// missing on older records).
function rejectionByline(rejection) {
  const by = rejection.rejected_by ? `by ${rejection.rejected_by}` : ''
  const when = rejection.rejected_at
    ? `on ${new Date(rejection.rejected_at).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}`
    : ''
  return ['Rejected', by, when].filter(Boolean).join(' ')
}

onMounted(loadEvent)
// Saving/submitting can move the URL to a sibling session (see
// applySavedGroup); the component is reused, so reload on the new id.
watch(() => route.params.eventId, (eventId) => {
  if (eventId) loadEvent()
})
</script>

<template>
  <div class="page">
    <AppNavBar />
    <main class="content">
      <div class="container">
        <router-link :to="backLink.to" class="back-link">&larr; {{ backLink.label }}</router-link>

        <p v-if="loading" class="message">Loading event...</p>
        <p v-else-if="error && !event" class="message error" role="alert">{{ error }}</p>
        <template v-else-if="event && isAssignedCoordinator">
          <CoordinatorEventReview
            :event="event"
            :sessions="visibleSessions"
            @updated="event = $event"
          />
          <VenueBookingStatus :event="event" />
        </template>
        <template v-else-if="event">
          <div class="card-header">
            <div class="page-heading">
              <h1 class="page-title">{{ event.name }}</h1>
              <span class="page-subtitle">
                {{ canEdit && isDraft ? 'Draft event request' : 'Event request' }}<template v-if="visibleSessions.length > 1"> · {{ visibleSessions.length }} sessions</template>
              </span>
            </div>
            <span class="status" :class="`status-${event.status}`">{{ statusLabel(event.status) }}</span>
          </div>

          <form v-if="canEdit" class="container-form" novalidate @submit.prevent="mode === 'draft' ? submitEvent() : resubmitRejected()">
            <p v-if="mode === 'rejected'" class="notice">
              <template v-if="visibleSessions.length > 1">
                {{ rejectedSessions.length }} of {{ visibleSessions.length }} sessions were rejected by the coordinator.
                Edit them below, then resubmit them for review. The other sessions keep their own review outcome
                and are shown for reference. Changes to the event details apply to the rejected sessions.
              </template>
              <template v-else>This request was rejected by the coordinator. Edit it below, then resubmit it for review.</template>
            </p>

            <section class="card" aria-labelledby="event-details-heading">
              <h2 id="event-details-heading" class="card-title">Event Details</h2>
              <label class="field" :class="{ invalid: errors.name }">
                <span class="field-label">Event Name</span>
                <input v-model.trim="form.name" class="input" type="text" placeholder="e.g. Annual Tech Conference 2026" @input="delete errors.name" />
                <span v-if="errors.name" class="field-error">{{ errors.name }}</span>
              </label>
              <label class="field" :class="{ invalid: errors.description }">
                <span class="field-label">Description</span>
                <textarea v-model.trim="form.description" class="input" rows="3" @input="delete errors.description" />
                <span v-if="errors.description" class="field-error">{{ errors.description }}</span>
              </label>
              <label class="field" :class="{ invalid: errors.purpose }">
                <span class="field-label">Purpose of the Event</span>
                <textarea v-model.trim="form.purpose" class="input" rows="3" @input="delete errors.purpose" />
                <span v-if="errors.purpose" class="field-error">{{ errors.purpose }}</span>
              </label>
            </section>

            <div class="section-heading">
              <h2 class="section-title">Sessions</h2>
              <span class="section-subtitle">
                {{ isDraft ? 'Add each session that is part of this event. Timing and requirements can differ per session.' : 'Rejected sessions are editable; the rest are shown as they are.' }}
              </span>
            </div>

            <template v-if="mode === 'draft'">
              <EventSessionFields
                v-for="(session, index) in form.sessions"
                :key="session.key"
                :session="session"
                :index="index"
                :minimum-date="minimumDate"
                :removable="form.sessions.length > 1"
                @remove="removeSession(index)"
              />
            </template>
            <template v-else>
              <template v-for="entry in sessionEntries" :key="entry.row.id">
                <EventSessionFields
                  v-if="entry.form"
                  :session="entry.form"
                  :index="entry.index"
                  :minimum-date="minimumDate"
                >
                  <template #notice>
                    <div class="rejection" role="note">
                      <span class="rejection-title">Reason for rejection</span>
                      <p class="rejection-reason">{{ entry.row.rejection?.reason || 'No reason was recorded.' }}</p>
                      <span v-if="entry.row.rejection" class="rejection-meta">
                        {{ rejectionByline(entry.row.rejection) }}
                      </span>
                    </div>
                  </template>
                </EventSessionFields>
                <SessionSummaryCard v-else :session="entry.row" :index="entry.index" />
              </template>
            </template>
            <button v-if="isDraft" type="button" class="add-session" @click="addSession">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
              Add Another Session
            </button>

            <p v-if="error" class="message error" role="alert">{{ error }}</p>
            <p v-if="saved" class="message success" role="status">{{ mode === 'draft' ? 'Draft saved.' : 'Changes saved.' }}</p>

            <div v-if="mode === 'rejected'" class="form-footer">
              <button type="button" class="btn btn-outline" :disabled="hasInvalidInput || saving || submitting" @click="saveRejectedChanges">
                {{ saving ? 'Saving...' : 'Save Changes' }}
              </button>
              <button type="submit" class="btn btn-primary" :disabled="!canSubmit || saving || submitting">
                {{ submitting ? 'Resubmitting...' : 'Resubmit Request' }}
              </button>
              <span class="footer-note">
                {{ form.sessions.length }} rejected session(s) will be resubmitted for review
              </span>
            </div>
            <div v-else class="form-footer">
              <button type="button" class="btn btn-outline" :disabled="hasInvalidInput || saving || submitting || deleting" @click="saveDraft">
                {{ saving ? 'Saving...' : 'Save as Draft' }}
              </button>
              <button type="submit" class="btn btn-primary" :disabled="!canSubmit || submitting || saving || deleting">
                {{ submitting ? 'Submitting...' : 'Submit Request' }}
              </button>
              <span class="footer-note">{{ form.sessions.length }} session(s) will be submitted with this request</span>
              <button v-if="canDelete" type="button" class="btn btn-danger push-right" :disabled="saving || submitting || deleting" @click="deleteDraft">
                {{ deleting ? 'Deleting...' : 'Delete Draft' }}
              </button>
            </div>
          </form>

          <template v-else>
            <p v-if="resubmitted" class="message success" role="status">
              Request resubmitted. It's back with the coordinator for review.
            </p>
            <p class="notice">This event is {{ statusLabel(event.status).toLowerCase() }} and can't be edited here.</p>

            <section class="card" aria-labelledby="event-details-heading">
              <h2 id="event-details-heading" class="card-title">Event Details</h2>
              <dl>
                <dt>Description</dt><dd>{{ event.description || 'Not provided' }}</dd>
                <dt>Purpose</dt><dd>{{ event.purpose || 'Not provided' }}</dd>
              </dl>
            </section>

            <div class="section-heading">
              <h2 class="section-title">Sessions</h2>
            </div>

            <SessionSummaryCard
              v-for="(session, index) in visibleSessions"
              :key="session.id"
              :session="session"
              :index="index"
              :current="visibleSessions.length > 1 && session.id === event.id"
            />
          </template>
        </template>
      </div>
    </main>
  </div>
</template>

<style scoped src="../../styles/event-form.css"></style>
<style scoped>
.container-form { display: flex; flex-direction: column; gap: 18px; }
.card-header .page-heading { min-width: 0; }
.card-title { margin: 0; }
.rejection {
  display: flex; flex-direction: column; gap: 4px;
  padding: 12px 16px; border-left: 3px solid #b42318; border-radius: 4px; background: #fde8e6;
}
.rejection-title { font-size: 12px; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; color: #b42318; }
.rejection-reason { margin: 0; font-size: 14px; color: #2a2a2a; white-space: pre-line; }
.rejection-meta { font-size: 12px; color: #6a6a6a; }
dl { display: grid; grid-template-columns: 180px 1fr; gap: 10px 16px; margin: 0; font-size: 14px; }
dt { font-weight: 600; color: #6a6a6a; }
dd { margin: 0; color: #2a2a2a; }
@media (max-width: 640px) {
  dl { grid-template-columns: 1fr; gap: 4px; }
  dd { margin-bottom: 8px; }
}
</style>
