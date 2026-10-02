<script setup>
import { computed, reactive, ref } from 'vue'
import { apiPost } from '../../lib/api'
import {
  DRAFT_NAME,
  emptySession,
  minimumStartDate,
  sessionFromEvent,
  sessionHasData,
  sessionHasInvalidInput,
  sessionIsComplete,
  sessionPayload,
  validateSession,
} from '../../lib/eventSessions'
import { useAuthStore } from '../../stores/auth'
import AppNavBar from '../../components/AppNavBar.vue'
import EventSessionFields from '../../components/EventSessionFields.vue'

const auth = useAuthStore()

// name/description/purpose are shared by every session; everything else is
// per session (see lib/eventSessions).
const form = reactive({
  name: '', description: '', purpose: '',
  sessions: [emptySession()],
})
const error = ref('')
const errors = reactive({})
const success = ref(false)
const submitting = ref(false)
const savingDraft = ref(false)
// Every visit to this page starts a brand-new request with a blank form --
// nothing is restored from an earlier visit. A saved draft is reopened from
// the events list instead (EventDetailsView). draftId only lives for this
// visit: once "Save as Draft" has created the draft, further saves and the
// final submit update THAT draft rather than creating another one. It's the
// id of one session; any session of a request addresses the whole request.
const draftId = ref(null)
const draftSaved = ref(false)

const minimumDate = minimumStartDate()

function populateForm(group) {
  form.name = group.name === DRAFT_NAME ? '' : group.name || ''
  form.description = group.description || ''
  form.purpose = group.purpose || ''
  form.sessions = group.sessions.length ? group.sessions.map(sessionFromEvent) : [emptySession()]
  draftId.value = group.sessions[0]?.id || null
}

// A fresh, blank form after a successful submit, so the next request
// doesn't start from (or accidentally resubmit) the one just sent.
// emptySession() gives each new session its own key, so every
// EventSessionFields re-mounts with no leftover per-session errors.
function resetForm() {
  form.name = ''
  form.description = ''
  form.purpose = ''
  form.sessions = [emptySession()]
  Object.keys(errors).forEach((field) => delete errors[field])
  draftId.value = null
  draftSaved.value = false
}

function addSession() {
  form.sessions.push(emptySession())
}

function removeSession(index) {
  form.sessions.splice(index, 1)
}

function payload() {
  return {
    name: form.name,
    description: form.description,
    purpose: form.purpose,
    sessions: form.sessions.map(sessionPayload),
  }
}

const hasDraftData = computed(() => [form.name, form.description, form.purpose]
  .some((value) => String(value ?? '').trim() !== '')
  || form.sessions.some(sessionHasData))

const canSubmit = computed(() => {
  const hasSharedFields = [form.name, form.description, form.purpose]
    .every((value) => String(value ?? '').trim() !== '')
  return hasSharedFields && form.sessions.every((session) => sessionIsComplete(session, minimumDate))
})

const hasInvalidInput = computed(() => form.sessions.some((session) => sessionHasInvalidInput(session, minimumDate)))

function validateForm() {
  Object.keys(errors).forEach((field) => delete errors[field])
  const requiredText = [
    ['name', 'Event name is required.'],
    ['description', 'Description is required.'],
    ['purpose', 'Purpose is required.'],
  ]
  requiredText.forEach(([field, message]) => {
    if (!form[field].trim()) errors[field] = message
  })
  // map, not every(): every session is validated so all of their errors
  // show at once, not just the first failing session's.
  const sessionResults = form.sessions.map((session) => validateSession(session, minimumDate))
  return Object.keys(errors).length === 0 && sessionResults.every(Boolean)
}

async function submitRequest() {
  error.value = ''
  success.value = false
  draftSaved.value = false
  if (!validateForm()) return
  submitting.value = true
  try {
    if (draftId.value) {
      // Save the latest edits to the draft first, then submit every session of it.
      populateForm(await apiPost(`/events/${draftId.value}/draft`, payload()))
      await apiPost(`/events/${draftId.value}/submit`, {})
    } else {
      // A brand-new request: the backend validates every session, creates
      // them all under one server-generated shared_event_id, and submits them.
      await apiPost('/events', payload())
    }
    resetForm()
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
    const group = draftId.value
      ? await apiPost(`/events/${draftId.value}/draft`, payload())
      : await apiPost('/events/draft', payload())
    populateForm(group)
    draftSaved.value = true
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    savingDraft.value = false
  }
}
</script>

<template>
  <div class="page">
    <AppNavBar />
    <main class="content">
      <div class="container">
        <router-link to="/events" class="back-link">&larr; Back to My Event Requests</router-link>

        <div class="page-heading">
          <h1 class="page-title">New Event Request</h1>
          <span v-if="auth.profile?.name" class="page-subtitle">Submitting as: {{ auth.profile.name }}</span>
        </div>

        <form class="container-form" novalidate @submit.prevent="submitRequest">
          <section class="card" aria-labelledby="event-details-heading">
            <h2 id="event-details-heading" class="card-title">Event Details</h2>
            <label class="field" :class="{ invalid: errors.name }">
              <span class="field-label">Event Name</span>
              <input v-model.trim="form.name" class="input" type="text" placeholder="e.g. Annual Tech Conference 2026" @input="delete errors.name" />
              <span v-if="errors.name" class="field-error">{{ errors.name }}</span>
            </label>
            <label class="field" :class="{ invalid: errors.description }">
              <span class="field-label">Description</span>
              <textarea v-model.trim="form.description" class="input" rows="3" placeholder="What is this event, and what should ConnectSphere know about it?" @input="delete errors.description" />
              <span v-if="errors.description" class="field-error">{{ errors.description }}</span>
            </label>
            <label class="field" :class="{ invalid: errors.purpose }">
              <span class="field-label">Purpose of the Event</span>
              <textarea v-model.trim="form.purpose" class="input" rows="3" placeholder="What is this event for?" @input="delete errors.purpose" />
              <span v-if="errors.purpose" class="field-error">{{ errors.purpose }}</span>
            </label>
          </section>

          <div class="section-heading">
            <h2 class="section-title">Sessions</h2>
            <span class="section-subtitle">Add each session that's part of this event. Timing and requirements can differ per session.</span>
          </div>

          <EventSessionFields
            v-for="(session, index) in form.sessions"
            :key="session.key"
            :session="session"
            :index="index"
            :minimum-date="minimumDate"
            :removable="form.sessions.length > 1"
            @remove="removeSession(index)"
          />

          <button type="button" class="add-session" @click="addSession">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>
            Add Another Session
          </button>

          <p v-if="error" class="message error" role="alert">{{ error }}</p>
          <p v-if="draftSaved" class="message success" role="status">Draft saved.</p>
          <p v-if="success" class="message success" role="status">Event request submitted for review.</p>

          <div class="form-footer">
            <button type="button" class="btn btn-outline" :disabled="!hasDraftData || hasInvalidInput || savingDraft || submitting" @click="saveDraft">
              {{ savingDraft ? 'Saving...' : 'Save as Draft' }}
            </button>
            <button type="submit" class="btn btn-primary" :disabled="!canSubmit || submitting || savingDraft">
              {{ submitting ? 'Submitting...' : 'Submit Request' }}
            </button>
            <span class="footer-note">{{ form.sessions.length }} session(s) will be submitted with this request</span>
          </div>
        </form>
      </div>
    </main>
  </div>
</template>

<style scoped src="../../styles/event-form.css"></style>
<style scoped>
.container-form { display: flex; flex-direction: column; gap: 18px; }
</style>
