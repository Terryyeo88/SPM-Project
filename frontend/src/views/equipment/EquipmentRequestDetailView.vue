<script setup>
/**
 * One equipment request plus its availability check -- Check Equipment
 * Availability (Nawaz, Sprint 2, IS-18), the story's main screen.
 *
 *   AC1  the request and its required date/time are shown at the top
 *   AC2  per item: requested quantity vs how many units are available
 *   AC3  items where available < requested are flagged
 *   AC4  "available" already has other events' reservations for the same
 *        period subtracted (done by the backend; the "held by" list shows
 *        which units and which events, so the number can be checked)
 *   AC5  the request is a stored row, so it is viewable again later
 *
 * The check is fetched fresh on every load rather than stored, so
 * reopening the request later reflects reservations made in the meantime.
 *
 * Reject (IS-41, Nawaz, Sprint 3): when stock is short the page suggests
 * rejecting, and Technical Support rejects with a required reason that the
 * coordinator then reads on their event (POST .../reject).
 *
 * Accept an equipment request and reserve stock (IS-19, Nawaz, Sprint 3):
 * a pending request on an event still in planning can be accepted from
 * here (POST /equipment/requests/<id>/accept). The button is only enabled
 * when every line is covered -- the backend refuses otherwise -- and a
 * successful accept lists the units that were reserved, then reloads so
 * the status and the availability numbers reflect the new reservations.
 * Rejecting is a separate story and is not here.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { apiGet, apiPost } from '../../lib/api'
import AppNavBar from '../../components/AppNavBar.vue'
import { describeAvailability, formatPeriod, summariseCheck } from '../../lib/equipment'
import { statusLabel } from '../../lib/coordinatorDashboard'
import EquipmentChangeDecisions from '../../components/EquipmentChangeDecisions.vue'
import { CHANGEABLE_EVENT_STATUSES } from '../../lib/equipment'

const route = useRoute()
const request = ref(null)
const check = ref(null)
const loading = ref(true)
const error = ref('')
const accepting = ref(false)
const acceptError = ref('')
const accepted = ref([])
const rejectReason = ref('')
const rejecting = ref(false)
const rejectError = ref('')

const summary = computed(() => summariseCheck(check.value))
const techRequirements = computed(() => {
  const byType = new Map((request.value?.items ?? []).map((item) => [item.equipment_type_id, item]))
  return byType
})
const lines = computed(() =>
  (check.value?.items ?? []).map((item) => ({
    ...item,
    ...describeAvailability(item),
    technical_requirements: techRequirements.value.get(item.equipment_type_id)?.technical_requirements ?? null,
  })),
)

// Accept needs the same preconditions as rule_equipment_request_accept:
// pending, event still in planning, AND enough stock. Reject (IS-41,
// rule_equipment_request_reject) needs only "pending" -- a pending request
// on a cancelled event can still be cleared, and rejecting takes no stock.
const canDecide = computed(() => request.value?.status === 'pending')
const canAccept = computed(
  () => canDecide.value && request.value?.event_status === 'planning' && check.value?.all_sufficient === true,
)
const shortOnStock = computed(() => check.value?.all_sufficient === false)
const canReject = computed(() => rejectReason.value.trim().length > 0)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const id = route.params.requestId
    const [loadedRequest, loadedCheck] = await Promise.all([
      apiGet(`/equipment/requests/${id}`),
      apiGet(`/equipment/requests/${id}/availability`),
    ])
    request.value = loadedRequest
    check.value = loadedCheck
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    loading.value = false
  }
}

async function accept() {
  acceptError.value = ''
  accepting.value = true
  try {
    const result = await apiPost(`/equipment/requests/${route.params.requestId}/accept`, {})
    accepted.value = result.allocated ?? []
    await load()
  } catch (requestError) {
    acceptError.value = requestError.message
  } finally {
    accepting.value = false
  }
}

async function reject() {
  rejectError.value = ''
  rejecting.value = true
  try {
    await apiPost(`/equipment/requests/${route.params.requestId}/reject`, { reason: rejectReason.value.trim() })
    rejectReason.value = ''
    await load()
  } catch (requestError) {
    rejectError.value = requestError.message
  } finally {
    rejecting.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <AppNavBar />
    <main class="content">
      <div class="container">
        <router-link :to="{ name: 'equipment-requests' }" class="back-link">&larr; Back to equipment requests</router-link>

        <p v-if="loading" class="message">Loading availability...</p>
        <p v-else-if="error" class="message error" role="alert">Couldn't load this request: {{ error }}</p>

        <template v-else>
          <div class="heading">
            <h1 class="title">{{ request.event_name ?? 'Untitled event' }}</h1>
            <span class="status cs-pill" :class="`status-${request.status} cs-status-${request.status}`">{{ statusLabel(request.status) }}</span>
          </div>

          <section class="card" aria-labelledby="needed-heading">
            <h2 id="needed-heading" class="card-title">Required date and time</h2>
            <p class="period">{{ formatPeriod(request.needed_start, request.needed_end) }}</p>
            <p class="hint">Times shown in Singapore time.</p>
          </section>

          <div class="banner" :class="summary.sufficient ? 'banner-ok' : 'banner-warn'" role="status">
            {{ summary.message }}
          </div>

          <section class="card" aria-labelledby="items-heading">
            <h2 id="items-heading" class="card-title">Equipment availability</h2>
            <p v-if="lines.length === 0" class="message">This request has no items.</p>

            <div v-for="line in lines" :key="line.equipment_type_id" class="line" :class="`line-${line.state}`">
              <div class="line-head">
                <span class="line-type">{{ line.type }}</span>
                <span class="flag cs-pill" :class="[`flag-${line.state}`, line.state === 'insufficient' ? 'cs-pill--pending' : 'cs-pill--available']">
                  {{ line.state === 'insufficient' ? '⚠ ' : '✓ ' }}{{ line.label }}
                </span>
              </div>
              <p class="line-numbers">
                Requested <strong>{{ line.requested }}</strong> &middot; available <strong>{{ line.available }}</strong>
              </p>
              <p class="line-detail">{{ line.detail }}</p>
              <p v-if="line.technical_requirements" class="line-notes">
                Technical requirements: {{ line.technical_requirements }}
              </p>
              <p v-if="line.available_units.length" class="line-units">
                Free units: {{ line.available_units.join(', ') }}
              </p>
              <ul v-if="line.conflicts.length" class="conflicts" :aria-label="`${line.type} units held for other events`">
                <li v-for="conflict in line.conflicts" :key="`${conflict.asset_tag}-${conflict.reserved_start}`">
                  <strong>{{ conflict.asset_tag }}</strong> held for
                  {{ conflict.event_name ?? 'another event' }},
                  {{ formatPeriod(conflict.reserved_start, conflict.reserved_end) }}
                </li>
              </ul>
            </div>
          </section>

          <section v-if="canDecide" class="card" aria-labelledby="decision-heading">
            <h2 id="decision-heading" class="card-title">Your decision</h2>
            <p v-if="shortOnStock" class="hint suggest">
              There is not enough equipment available for this period. We suggest rejecting this request and telling the
              Event Coordinator why.
            </p>
            <p v-else-if="!canAccept" class="hint">This request can't be accepted, but it can still be rejected.</p>
            <p v-else class="hint">
              Accepting reserves the units above for this event's date and time and confirms the request.
            </p>
            <p v-if="acceptError" class="error" role="alert">{{ acceptError }}</p>
            <button type="button" class="btn-accept" :disabled="!canAccept || accepting" @click="accept">
              {{ accepting ? 'Accepting...' : 'Accept request' }}
            </button>

            <div class="reject-box">
              <label for="reject-reason" class="reject-label">Reason for rejecting (sent to the Event Coordinator)</label>
              <textarea
                id="reject-reason"
                v-model="rejectReason"
                class="reject-reason"
                rows="3"
                maxlength="1000"
                placeholder="e.g. Only 1 projector is free on that date."
              ></textarea>
              <p v-if="rejectError" class="error" role="alert">{{ rejectError }}</p>
              <button type="button" class="btn-reject" :disabled="!canReject || rejecting" @click="reject">
                {{ rejecting ? 'Rejecting...' : 'Reject request' }}
              </button>
            </div>
          </section>

          <section v-if="request.status === 'rejected'" class="card" aria-labelledby="rejection-heading">
            <h2 id="rejection-heading" class="card-title">Why this request was rejected</h2>
            <p class="rejection-reason">{{ request.rejection_reason ?? 'No reason was recorded.' }}</p>
          </section>

          <EquipmentChangeDecisions
            v-if="request.status === 'confirmed'"
            :request-id="request.id"
            :event-live="CHANGEABLE_EVENT_STATUSES.includes(request.event_status)"
            @decided="load"
          />

          <section v-if="accepted.length" class="card" aria-labelledby="reserved-heading">
            <h2 id="reserved-heading" class="card-title">Reserved for this event</h2>
            <ul class="reserved">
              <li v-for="group in accepted" :key="group.equipment_type_id">
                <strong>{{ group.type }}</strong> &times; {{ group.quantity }}:
                {{ group.units.map((unit) => unit.asset_tag).join(', ') }}
              </li>
            </ul>
          </section>
        </template>
      </div>
    </main>
  </div>
</template>

<style scoped>
.page { min-height: 100vh; display: flex; flex-direction: column; }
.content { flex: 1 1 auto; padding: var(--cs-space-6) var(--cs-space-4) var(--cs-space-8); display: flex; justify-content: center; }
.container { width: 100%; max-width: 760px; display: flex; flex-direction: column; gap: var(--cs-space-4); }
.back-link { font-size: var(--cs-text-sm); color: var(--cs-signal); text-decoration: none; }
.heading { display: flex; align-items: center; justify-content: space-between; gap: var(--cs-space-3); }
.title { margin: 0; font-size: var(--cs-text-xl); font-family: var(--cs-font-display); color: var(--cs-ink); }
.message { margin: 0; padding: var(--cs-space-2) 0; font-size: var(--cs-text-base); color: var(--cs-ink-soft); }
.error { color: var(--cs-occupied); }
.hint { margin: 0; font-size: var(--cs-text-xs); color: var(--cs-ink-soft); }

.card { background: var(--cs-surface); border: 1px solid var(--cs-line); border-radius: var(--cs-radius-md); padding: var(--cs-space-4) var(--cs-space-5); box-sizing: border-box; }
.card-title { margin: 0 0 var(--cs-space-2); font-size: var(--cs-text-sm); font-weight: 700; color: var(--cs-ink); }
.period { margin: 0 0 4px; font-size: var(--cs-text-base); font-weight: 600; color: var(--cs-ink); }

.banner { border-radius: var(--cs-radius-sm); padding: var(--cs-space-3) var(--cs-space-4); font-size: var(--cs-text-base); font-weight: 600; }
.banner-ok { background: var(--cs-available-tint); color: var(--cs-available); }
.banner-warn { background: var(--cs-pending-tint); color: var(--cs-pending); }

.line { padding: var(--cs-space-4) 0; border-bottom: 1px solid var(--cs-line); }
.line:last-child { border-bottom: none; padding-bottom: 0; }
.line-head { display: flex; align-items: center; justify-content: space-between; gap: var(--cs-space-3); }
.line-type { font-size: var(--cs-text-base); font-weight: 700; color: var(--cs-ink); text-transform: capitalize; }
.line-numbers { margin: 6px 0 0; font-size: var(--cs-text-sm); color: var(--cs-ink); }
.line-detail, .line-units, .line-notes { margin: 4px 0 0; font-size: var(--cs-text-xs); color: var(--cs-ink-soft); }
.conflicts { margin: var(--cs-space-2) 0 0; padding-left: 18px; font-size: var(--cs-text-xs); color: var(--cs-ink-soft); }
.conflicts li { margin: 2px 0; }

.error { margin: 0; font-size: var(--cs-text-sm); color: var(--cs-occupied); }
.btn-accept {
  align-self: flex-start; min-height: 40px; padding: 0 var(--cs-space-4); border: none; border-radius: var(--cs-radius-sm);
  background: var(--cs-signal); color: #fff; font: inherit; font-size: var(--cs-text-base); font-weight: 700; cursor: pointer;
}
.btn-accept:hover:not(:disabled) { background: var(--cs-signal-strong); }
.btn-accept:disabled { background: var(--cs-line-strong); cursor: not-allowed; }
.suggest { color: var(--cs-pending); font-weight: 600; }
.reject-box { margin-top: var(--cs-space-4); padding-top: var(--cs-space-4); border-top: 1px solid var(--cs-line); display: flex; flex-direction: column; gap: var(--cs-space-2); }
.reject-label { font-size: var(--cs-text-sm); font-weight: 600; color: var(--cs-ink); }
.reject-reason { font: inherit; font-size: var(--cs-text-base); padding: var(--cs-space-2) var(--cs-space-3); border: 1px solid var(--cs-line-strong); border-radius: var(--cs-radius-sm); resize: vertical; }
.btn-reject {
  align-self: flex-start; min-height: 40px; padding: 0 var(--cs-space-4); border: none; border-radius: var(--cs-radius-sm);
  background: var(--cs-occupied); color: #fff; font: inherit; font-size: var(--cs-text-base); font-weight: 700; cursor: pointer;
}
.btn-reject:disabled { background: var(--cs-occupied-tint); color: var(--cs-occupied); cursor: not-allowed; }
.rejection-reason { margin: 0; font-size: var(--cs-text-base); color: var(--cs-ink); white-space: pre-wrap; }
.reserved { margin: 0; padding-left: 18px; font-size: var(--cs-text-base); color: var(--cs-ink); display: flex; flex-direction: column; gap: 4px; }
</style>
