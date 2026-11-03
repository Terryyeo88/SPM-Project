<script setup>
/**
 * The attendee's event page, laid out after the EventDetail wireframe (and
 * its Registered / Waitlisted variants): what the session is, then a side
 * card with spots filled and the attendee's action --
 *
 *   not registered, open  -> Register (Join Waiting List when full), which
 *                            opens RegistrationForm
 *   not open yet / closed -> says when
 *   registered            -> "You're registered" + Withdraw Registration
 *   waitlisted            -> "position #n" + Leave Waiting List
 *   no registration needed -> says so, no Register button (View Events
 *                            Without Registration)
 *
 * GET /registrations/sessions/<id> (public fields only, places, my
 * registration); DELETE /registrations/<id> to withdraw. Withdrawing a
 * confirmed place moves the first person on the waiting list up.
 *
 * Venue (View Event Venue): every confirmed venue, name and location, or
 * "Venue to be confirmed". The wireframe's event image and category aren't
 * shown: events have neither yet.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { apiDelete, apiGet } from '../../lib/api'
import { formatDateRange } from '../../lib/coordinatorDashboard'
import {
  formatSgt,
  placesLabel,
  registrationRequirementLabel,
  registrationState,
  requiresRegistration,
  sessionWhen,
  spotsFilled,
  venueLines,
} from '../../lib/registrations'
import AppNavBar from '../../components/AppNavBar.vue'
import RegistrationForm from '../../components/RegistrationForm.vue'

const route = useRoute()
const session = ref(null)
const loading = ref(true)
const error = ref('')
const message = ref('')
const formOpen = ref(false)
const confirmingWithdraw = ref(false)
const withdrawing = ref(false)
const actionError = ref('')

const mine = computed(() => session.value?.my_registration ?? null)
const state = computed(() => (session.value ? registrationState(session.value) : 'closed'))
const spots = computed(() => (session.value ? spotsFilled(session.value) : null))
const full = computed(() => session.value?.places_left === 0)
const needsRegistration = computed(() => requiresRegistration(session.value))

async function load() {
  loading.value = true
  error.value = ''
  try {
    session.value = await apiGet(`/registrations/sessions/${route.params.eventId}`)
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    loading.value = false
  }
}

async function onRegistered(registration) {
  formOpen.value = false
  message.value = registration.status === 'waitlisted'
    ? "This session is full, so you're on the waiting list."
    : "You're registered."
  await load()
}

async function withdraw() {
  withdrawing.value = true
  actionError.value = ''
  try {
    const wasWaitlisted = mine.value?.status === 'waitlisted'
    await apiDelete(`/registrations/${session.value.id}`)
    confirmingWithdraw.value = false
    message.value = wasWaitlisted ? "You've left the waiting list." : 'Your registration has been withdrawn.'
    await load()
  } catch (requestError) {
    actionError.value = requestError.message
  } finally {
    withdrawing.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <AppNavBar />

    <main class="content">
      <div class="container">
        <router-link :to="{ name: 'dashboard' }" class="back-link">&larr; Back to My Events</router-link>

        <p v-if="loading" class="message">Loading event...</p>
        <p v-else-if="error" class="message error" role="alert">{{ error }}</p>

        <div v-else-if="session" class="layout">
          <div class="main">
            <h1>{{ session.name }}</h1>
            <div class="meta">
              <span class="meta-item">
                <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="#9a9a9a" stroke-width="2"
                  stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                  <rect x="3" y="4" width="18" height="18" rx="2" /><line x1="16" y1="2" x2="16" y2="6" />
                  <line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" />
                </svg>
                {{ sessionWhen(session, formatDateRange) }}
              </span>
              <span class="meta-item requirement">{{ registrationRequirementLabel(session) }}</span>
            </div>
            <hr />
            <div class="about">
              <span class="label">About this event</span>
              <p>{{ session.description || 'No description yet.' }}</p>
            </div>
            <div class="about">
              <span class="label">{{ venueLines(session).length > 1 ? 'Venues' : 'Venue' }}</span>
              <ul v-if="venueLines(session).length" class="venues">
                <li v-for="line in venueLines(session)" :key="line">{{ line }}</li>
              </ul>
              <p v-else>Venue to be confirmed</p>
            </div>
            <div v-if="needsRegistration" class="about">
              <span class="label">Registration period</span>
              <p>
                {{ session.registration_start_datetime ? formatSgt(session.registration_start_datetime) : 'Open now' }}
                – {{ session.registration_end_datetime ? formatSgt(session.registration_end_datetime) : 'until the event' }}
              </p>
            </div>
          </div>

          <aside class="card" aria-label="Registration">
            <div v-if="spots" class="spots">
              <span class="label">Spots filled</span>
              <span class="spots-count">{{ spots.filled }} / {{ spots.capacity }}</span>
              <div class="bar" role="progressbar" :aria-valuenow="spots.filled" aria-valuemin="0"
                :aria-valuemax="spots.capacity" aria-label="Spots filled">
                <div class="bar-fill" :style="{ width: `${spots.percent}%` }" />
              </div>
              <span v-if="session.waitlist_count" class="muted small">{{ session.waitlist_count }} on the waiting list</span>
            </div>

            <hr v-if="spots" />

            <p v-if="message" class="success" role="status">{{ message }}</p>

            <template v-if="mine && mine.status === 'confirmed'">
              <div class="state state-confirmed cs-pill cs-pill--available">&#10003; You're registered</div>
            </template>
            <template v-else-if="mine && mine.status === 'waitlisted'">
              <div class="state state-waitlisted cs-pill cs-pill--pending">
                You're on the waiting list<template v-if="mine.waitlist_position"> — position #{{ mine.waitlist_position }}</template>
              </div>
            </template>

            <template v-if="mine">
              <template v-if="!confirmingWithdraw">
                <button type="button" class="btn danger" :class="{ amber: mine.status === 'waitlisted' }"
                  @click="confirmingWithdraw = true">
                  {{ mine.status === 'waitlisted' ? 'Leave Waiting List' : 'Withdraw Registration' }}
                </button>
              </template>
              <div v-else class="confirm">
                <p class="small">
                  {{ mine.status === 'waitlisted'
                    ? "You'll lose your place in the queue."
                    : 'Your place will go to the next person on the waiting list.' }}
                </p>
                <div class="confirm-actions">
                  <button type="button" class="btn neutral" :disabled="withdrawing" @click="confirmingWithdraw = false">
                    Keep it
                  </button>
                  <button type="button" class="btn danger solid" :disabled="withdrawing" @click="withdraw">
                    {{ withdrawing ? 'Withdrawing...' : 'Yes, withdraw' }}
                  </button>
                </div>
              </div>
            </template>

            <template v-else-if="!needsRegistration">
              <div class="state state-none">No registration required</div>
              <span class="muted small center">You can attend this event without signing up.</span>
            </template>
            <template v-else-if="state === 'open'">
              <button type="button" class="btn primary" @click="formOpen = true">
                {{ full ? 'Join Waiting List' : 'Register' }}
              </button>
              <span class="muted small center">{{ placesLabel(session) }}</span>
            </template>
            <template v-else-if="state === 'upcoming'">
              <button type="button" class="btn primary" disabled>Register</button>
              <span class="muted small center">Registration opens {{ formatSgt(session.registration_start_datetime) }}</span>
            </template>
            <template v-else>
              <span class="muted small center">Registration closed {{ formatSgt(session.registration_end_datetime) }}</span>
            </template>

            <p v-if="actionError" class="field-error" role="alert">{{ actionError }}</p>
          </aside>
        </div>
      </div>
    </main>

    <RegistrationForm v-if="formOpen && session" :session="session" @registered="onRegistered" @cancel="formOpen = false" />
  </div>
</template>

<style scoped>
.page { min-height: 100vh; display: flex; flex-direction: column; }
.content { flex: 1 1 auto; padding: var(--cs-space-6) var(--cs-space-4) var(--cs-space-8); display: flex; justify-content: center; }
.container { width: 100%; max-width: 880px; display: flex; flex-direction: column; gap: var(--cs-space-5); }
.back-link { align-self: flex-start; font-size: var(--cs-text-sm); color: var(--cs-ink-soft); }
.message { margin: 0; font-size: var(--cs-text-base); color: var(--cs-ink-soft); }
.error, .field-error { color: var(--cs-occupied); }
.field-error { margin: 0; font-size: var(--cs-text-xs); }
.success { margin: 0; font-size: var(--cs-text-sm); color: var(--cs-available); }
.muted { color: var(--cs-ink-soft); }
.small { font-size: var(--cs-text-xs); margin: 0; }
.center { text-align: center; }

.layout { display: flex; align-items: flex-start; gap: var(--cs-space-6); }
.main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: var(--cs-space-4); }
h1 { margin: 0; font-size: var(--cs-text-xl); font-family: var(--cs-font-display); color: var(--cs-ink); line-height: 1.3; }
.meta { display: flex; flex-wrap: wrap; gap: var(--cs-space-4); font-size: var(--cs-text-sm); color: var(--cs-ink-soft); }
.meta-item { display: flex; align-items: center; gap: 6px; }
hr { border: none; height: 1px; background: var(--cs-line); margin: 0; }
.about { display: flex; flex-direction: column; gap: var(--cs-space-2); }
.about p { margin: 0; font-size: var(--cs-text-base); line-height: 1.65; color: var(--cs-ink); }
.label { font-size: var(--cs-text-xs); font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--cs-ink-soft); }

.card {
  flex: 0 0 260px; box-sizing: border-box; display: flex; flex-direction: column; gap: var(--cs-space-3);
  background: var(--cs-surface); border: 1px solid var(--cs-line); border-radius: var(--cs-radius-md); padding: var(--cs-space-5);
}
.spots { display: flex; flex-direction: column; gap: 4px; }
.spots-count { font-size: var(--cs-text-base); font-weight: 600; color: var(--cs-ink); }
.bar { height: 6px; background: var(--cs-neutral-tint); border-radius: var(--cs-radius-full); overflow: hidden; margin-top: 4px; }
.bar-fill { height: 100%; background: var(--cs-signal); }

.state-none {
  border-radius: var(--cs-radius-sm); padding: var(--cs-space-3) var(--cs-space-3);
  background: var(--cs-neutral-tint); border: 1px solid var(--cs-line); color: var(--cs-neutral);
  font-size: var(--cs-text-sm); font-weight: 600; text-align: center;
}
.requirement { font-weight: 600; color: var(--cs-ink-soft); }
.venues { margin: 0; padding-left: 18px; font-size: var(--cs-text-base); line-height: 1.65; color: var(--cs-ink); }

.btn { height: 46px; border-radius: var(--cs-radius-sm); font: inherit; font-size: var(--cs-text-base); font-weight: 700; cursor: pointer; }
.btn:disabled { opacity: 0.55; cursor: default; }
.btn.primary { border: none; background: var(--cs-signal); color: #fff; }
.btn.primary:hover:not(:disabled) { background: var(--cs-signal-strong); }
.btn.danger { border: 1px solid var(--cs-occupied); background: var(--cs-surface); color: var(--cs-occupied); }
.btn.danger.amber { border-color: var(--cs-pending); color: var(--cs-pending); }
.btn.danger.solid { background: var(--cs-occupied); color: #fff; border-color: var(--cs-occupied); }
.btn.neutral { border: 1px solid var(--cs-line-strong); background: var(--cs-surface); color: var(--cs-ink); font-weight: 600; }
.btn:focus-visible, .back-link:focus-visible { outline: 2px solid var(--cs-signal); outline-offset: 2px; }
.confirm { display: flex; flex-direction: column; gap: var(--cs-space-2); }
.confirm-actions { display: flex; gap: var(--cs-space-2); }
.confirm-actions .btn { flex: 1; height: 40px; font-size: var(--cs-text-sm); }

@media (max-width: 700px) {
  .layout { flex-direction: column; }
  .card { flex: 1 1 auto; width: 100%; }
}
</style>
