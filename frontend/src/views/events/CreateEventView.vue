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
import AppNavBar from '../../components/AppNavBar.vue'
import EventSessionFields from '../../components/EventSessionFields.vue'

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
  <div class="app-page">
    <AppNavBar />
  <main class="events-page">
    <p><router-link to="/">&larr; Back</router-link></p>
    <h1>Create an event request</h1>
    <p class="intro">Complete the event brief so a coordinator can review and plan it. Add a session for each date and time the event runs. Each session can have its own requirements.</p>

    <form novalidate @submit.prevent="submitRequest">
      <fieldset>
        <legend>Event details</legend>
        <label :class="{ invalid: errors.name }">Event name <input v-model.trim="form.name" @input="delete errors.name" /> <span v-if="errors.name" class="field-error">{{ errors.name }}</span></label>
        <label :class="{ invalid: errors.description }">Description <textarea v-model.trim="form.description" @input="delete errors.description" /> <span v-if="errors.description" class="field-error">{{ errors.description }}</span></label>
        <label :class="{ invalid: errors.purpose }">Purpose of the event <textarea v-model.trim="form.purpose" @input="delete errors.purpose" /> <span v-if="errors.purpose" class="field-error">{{ errors.purpose }}</span></label>
      </fieldset>

      <EventSessionFields
        v-for="(session, index) in form.sessions"
        :key="session.key"
        :session="session"
        :index="index"
        :minimum-date="minimumDate"
        :removable="form.sessions.length > 1"
        @remove="removeSession(index)"
      />
      <button type="button" class="add-session" @click="addSession">+ Add session</button>

      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <p v-if="draftSaved" class="success" role="status">Draft saved.</p>
      <p v-if="success" class="success" role="status">Event request submitted for review.</p>
      <div class="actions">
        <button type="button" class="draft-button" :disabled="!hasDraftData || hasInvalidInput || savingDraft || submitting" @click="saveDraft">
          {{ savingDraft ? 'Saving...' : 'Save as Draft' }}
        </button>
        <button type="submit" :disabled="!canSubmit || submitting || savingDraft">
          {{ submitting ? 'Submitting...' : form.sessions.length > 1 ? `Submit request (${form.sessions.length} sessions)` : 'Submit request' }}
        </button>
      </div>
    </form>
  </main>
  </div>
</template>

<style scoped>
.app-page { min-height: 100vh; background: #ffffff; }
.events-page { max-width: 760px; margin: 2rem auto; padding: 0 1rem 3rem; }
.intro { color: #52606d; }
form { display: grid; gap: 1rem; }
fieldset { display: grid; gap: .75rem; padding: 1rem; border: 1px solid #cbd5e1; border-radius: 6px; }
legend { font-weight: 700; }
label { display: grid; gap: .35rem; }
input, textarea { box-sizing: border-box; width: 100%; padding: .6rem; border: 1px solid #94a3b8; border-radius: 4px; font: inherit; }
textarea { min-height: 5rem; resize: vertical; }
button { width: fit-content; padding: .7rem 1.1rem; border: 0; border-radius: 4px; background: #0f766e; color: white; font: inherit; cursor: pointer; }
button:disabled { opacity: .6; cursor: not-allowed; }
.add-session { background: #ffffff; color: #0f766e; border: 1px dashed #0f766e; }
.actions { display: flex; gap: .75rem; flex-wrap: wrap; }
.draft-button { background: #475569; }
.error { color: #b42318; }
.invalid input, .invalid textarea { border-color: #b42318; }
.field-error { color: #b42318; font-size: .85rem; }
.success { color: #067647; }
</style>
