<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiDelete, apiGet, apiPost } from '../../lib/api'
import { useAuthStore } from '../../stores/auth'
import { statusLabel, tabForStatus } from '../../lib/coordinatorDashboard'
import {
  ACCESSIBILITY_OPTIONS,
  DRAFT_NAME,
  EQUIPMENT_OPTIONS,
  emptySession,
  minimumStartDate,
  sessionFromEvent,
  sessionHasInvalidInput,
  sessionIsComplete,
  sessionPayload,
  timeValue,
  validateSession,
} from '../../lib/eventSessions'
import CoordinatorEventReview from './CoordinatorEventReview.vue'
import AppNavBar from '../../components/AppNavBar.vue'
import EventSessionFields from '../../components/EventSessionFields.vue'

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

const canEdit = computed(() => Boolean(
  event.value
  && ['draft', 'rejected'].includes(event.value.status)
  && event.value.organizer_id === auth.profile?.id,
))

// A draft is edited as a whole request: every session together, and
// sessions can be added or removed. A rejected session has already been
// reviewed separately from its siblings, so only it is edited, on its own.
const isDraft = computed(() => event.value?.status === 'draft')

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

function populateForm(value, sessions) {
  form.name = value.name === DRAFT_NAME ? '' : value.name || ''
  form.description = value.description || ''
  form.purpose = value.purpose || ''
  form.sessions = sessions.map(sessionFromEvent)
}

function editableSessions() {
  if (!isDraft.value) return [event.value]
  const drafts = (group.value?.sessions || []).filter((session) => session.status === 'draft')
  return drafts.length ? drafts : [event.value]
}

async function loadEvent() {
  loading.value = true
  error.value = ''
  saved.value = false
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
        <CoordinatorEventReview
          v-else-if="event && isAssignedCoordinator"
          :event="event"
          :sessions="visibleSessions"
          @updated="event = $event"
        />
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

          <form v-if="canEdit" class="container-form" novalidate @submit.prevent="submitEvent">
            <p v-if="!isDraft && visibleSessions.length > 1" class="notice">
              Only this rejected session is edited here. The request's other sessions are reviewed separately.
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
                {{ isDraft ? 'Add each session that is part of this event. Timing and requirements can differ per session.' : 'The session that was returned to you for changes.' }}
              </span>
            </div>

            <EventSessionFields
              v-for="(session, index) in form.sessions"
              :key="session.key"
              :session="session"
              :index="index"
              :minimum-date="minimumDate"
              :removable="isDraft && form.sessions.length > 1"
              @remove="removeSession(index)"
            />
            <button v-if="isDraft" type="button" class="add-session" @click="addSession">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
              Add Another Session
            </button>

            <p v-if="error" class="message error" role="alert">{{ error }}</p>
            <p v-if="saved" class="message success" role="status">Draft saved.</p>

            <div class="form-footer">
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

            <section
              v-for="(session, index) in visibleSessions"
              :key="session.id"
              class="card session-card"
              :class="{ current: session.id === event.id }"
              :aria-labelledby="`session-${session.id}`"
            >
              <div class="card-header">
                <h3 :id="`session-${session.id}`" class="card-title">
                  <router-link v-if="session.id !== event.id" :to="`/events/${session.id}`">Session {{ index + 1 }}</router-link>
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
        </template>
      </div>
    </main>
  </div>
</template>

<style scoped src="../../styles/event-form.css"></style>
<style scoped>
.container-form { display: flex; flex-direction: column; gap: 18px; }
.card-header .page-heading { min-width: 0; }
.session-card.current { border-style: solid; border-color: #444444; }
.card-title { margin: 0; }
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
