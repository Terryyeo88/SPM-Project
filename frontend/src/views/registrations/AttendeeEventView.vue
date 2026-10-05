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
 *
 * GET /registrations/sessions/<id> (public fields only, places, my
 * registration); DELETE /registrations/<id> to withdraw. Withdrawing a
 * confirmed place moves the first person on the waiting list up.
 *
 * The wireframe's event image, venue and category aren't shown: events have
 * none of those yet.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { apiDelete, apiGet } from '../../lib/api'
import { formatDateRange } from '../../lib/coordinatorDashboard'
import {
  formatSgt,
  placesLabel,
  registrationState,
  sessionWhen,
  spotsFilled,
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
            </div>
            <hr />
            <div class="about">
              <span class="label">About this event</span>
              <p>{{ session.description || 'No description yet.' }}</p>
            </div>
            <div class="about">
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

            <hr />

            <p v-if="message" class="success" role="status">{{ message }}</p>

            <template v-if="mine && mine.status === 'confirmed'">
              <div class="state state-confirmed">&#10003; You're registered</div>
            </template>
            <template v-else-if="mine && mine.status === 'waitlisted'">
              <div class="state state-waitlisted">
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
.page { min-height: 100vh; display: flex; flex-direction: column; background: #eeeeee; }
.content { flex: 1 1 auto; padding: 32px 16px; display: flex; justify-content: center; }
.container { width: 100%; max-width: 880px; display: flex; flex-direction: column; gap: 20px; }
.back-link { align-self: flex-start; font-size: 13px; color: #666; }
.message { margin: 0; font-size: 14px; color: #8a8a8a; }
.error, .field-error { color: #a33f3f; }
.field-error { margin: 0; font-size: 12px; }
.success { margin: 0; font-size: 13px; color: #2f6b3f; }
.muted { color: #6b6b6b; }
.small { font-size: 12px; margin: 0; }
.center { text-align: center; }

.layout { display: flex; align-items: flex-start; gap: 28px; }
.main { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 16px; }
h1 { margin: 0; font-size: 24px; font-weight: 800; color: #1f1f1f; line-height: 1.3; }
.meta { display: flex; flex-wrap: wrap; gap: 18px; font-size: 13px; color: #666; }
.meta-item { display: flex; align-items: center; gap: 6px; }
hr { border: none; height: 1px; background: #e2e2e2; margin: 0; }
.about { display: flex; flex-direction: column; gap: 8px; }
.about p { margin: 0; font-size: 14px; line-height: 1.65; color: #3a3a3a; }
.label { font-size: 11px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: #8a8a8a; }

.card {
  flex: 0 0 260px; box-sizing: border-box; display: flex; flex-direction: column; gap: 14px;
  background: #fff; border: 1px dashed #9a9a9a; border-radius: 6px; padding: 20px;
}
.spots { display: flex; flex-direction: column; gap: 4px; }
.spots-count { font-size: 14px; font-weight: 600; color: #2a2a2a; }
.bar { height: 6px; background: #eee; border-radius: 3px; overflow: hidden; margin-top: 4px; }
.bar-fill { height: 100%; background: #2568e8; }

.state { border-radius: 4px; padding: 10px 12px; font-size: 13px; font-weight: 600; }
.state-confirmed { background: #eaf5ec; border: 1px dashed #2f6b3f; color: #2f6b3f; }
.state-waitlisted { background: #f7efe1; border: 1px dashed #8a5a12; color: #8a5a12; }

.btn { height: 46px; border-radius: 4px; font: inherit; font-size: 14px; font-weight: 700; cursor: pointer; }
.btn:disabled { opacity: 0.55; cursor: default; }
.btn.primary { border: none; background: #2568e8; color: #fff; }
.btn.danger { border: 1px solid #a33f3f; background: #fff; color: #a33f3f; }
.btn.danger.amber { border-color: #8a5a12; color: #8a5a12; }
.btn.danger.solid { background: #a33f3f; color: #fff; }
.btn.neutral { border: 1px solid #b0b0b0; background: #fff; color: #444; font-weight: 600; }
.btn:focus-visible, .back-link:focus-visible { outline: 2px solid #2568e8; outline-offset: 2px; }
.confirm { display: flex; flex-direction: column; gap: 10px; }
.confirm-actions { display: flex; gap: 8px; }
.confirm-actions .btn { flex: 1; height: 40px; font-size: 13px; }

@media (max-width: 700px) {
  .layout { flex-direction: column; }
  .card { flex: 1 1 auto; width: 100%; }
}
</style>
