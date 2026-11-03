<script setup>
/**
 * Technical Support's side of Update quantity on an existing equipment
 * reservation (Nawaz, Sprint 3, IS-43), shown on the equipment request
 * page.
 *
 * AC1  each pending ask comes with a fresh recalculation: how many units
 *      could cover the request for its date/time vs the quantity asked for
 * AC2  Accept applies the new quantity (reserves extra units or releases
 *      surplus ones) -- only enabled when it can be accommodated
 * AC3  Reject needs an explanation, which the coordinator then reads
 *
 * Data: GET /equipment/requests/<id>/change-requests (the `check` on each
 * pending ask is computed by the backend), POST
 * /equipment/change-requests/<id>/accept|reject.
 */
import { computed, onMounted, ref } from 'vue'
import { apiGet, apiPost } from '../lib/api'
import { describeChange } from '../lib/equipment'

const props = defineProps({
  requestId: { type: String, required: true },
  // False once the event is cancelled/completed/rejected: accepting would
  // move stock for an event that no longer needs it (rule_equipment_change_accept).
  eventLive: { type: Boolean, default: true },
})
const emit = defineEmits(['decided'])

const changes = ref([])
const reasons = ref({})
const errors = ref({})
const busy = ref('')
const loadError = ref('')

const pending = computed(() => changes.value.filter((change) => change.status === 'pending'))
const decided = computed(() => changes.value.filter((change) => change.status !== 'pending'))

async function load() {
  loadError.value = ''
  try {
    const result = await apiGet(`/equipment/requests/${props.requestId}/change-requests`)
    changes.value = Array.isArray(result) ? result : []
  } catch (requestError) {
    loadError.value = requestError.message
  }
}

function canAccept(change) {
  return props.eventLive && change.check?.accommodated === true
}

function canReject(change) {
  return (reasons.value[change.id] ?? '').trim().length > 0
}

async function decide(change, action, body) {
  errors.value = { ...errors.value, [change.id]: '' }
  busy.value = change.id
  try {
    await apiPost(`/equipment/change-requests/${change.id}/${action}`, body)
    await load()
    emit('decided')
  } catch (requestError) {
    errors.value = { ...errors.value, [change.id]: requestError.message }
  } finally {
    busy.value = ''
  }
}

const accept = (change) => decide(change, 'accept', {})
const reject = (change) => decide(change, 'reject', { reason: (reasons.value[change.id] ?? '').trim() })

onMounted(load)
</script>

<template>
  <section v-if="pending.length || decided.length || loadError" class="card" aria-labelledby="changes-heading">
    <h2 id="changes-heading" class="card-title">Quantity changes</h2>
    <p v-if="loadError" class="error" role="alert">Couldn't load quantity changes: {{ loadError }}</p>

    <div v-for="change in pending" :key="change.id" class="change">
      <p class="change-head">
        The coordinator asks to change <strong>{{ change.type }}</strong> from {{ change.old_quantity }} to
        <strong>{{ change.new_quantity }}</strong>.
      </p>
      <p class="change-check" :class="change.check?.accommodated ? 'ok' : 'warn'">
        {{ change.check?.available }} {{ change.type }} available for this period &middot;
        <template v-if="change.check?.accommodated">this can be accommodated.</template>
        <template v-else>
          short by {{ change.check?.shortfall }}. We suggest rejecting this change and telling the coordinator why.
        </template>
      </p>
      <p v-if="!eventLive" class="hint">This event is no longer live, so the change can only be rejected.</p>
      <p v-if="errors[change.id]" class="error" role="alert">{{ errors[change.id] }}</p>
      <button type="button" class="btn-accept-change" :disabled="!canAccept(change) || busy === change.id" @click="accept(change)">
        {{ busy === change.id ? 'Working...' : 'Accept change' }}
      </button>
      <div class="reject-box">
        <label :for="`change-reason-${change.id}`" class="reject-label">
          Reason for rejecting (sent to the Event Coordinator)
        </label>
        <textarea :id="`change-reason-${change.id}`" v-model="reasons[change.id]" class="change-reason-input" rows="2" maxlength="1000"></textarea>
        <button type="button" class="btn-reject-change" :disabled="!canReject(change) || busy === change.id" @click="reject(change)">
          Reject change
        </button>
      </div>
    </div>

    <ul v-if="decided.length" class="history" aria-label="Past quantity changes">
      <li v-for="change in decided" :key="change.id">
        <strong>{{ change.status === 'accepted' ? 'Accepted' : 'Rejected' }}:</strong> {{ describeChange(change) }}
        <span v-if="change.status === 'rejected'" class="history-reason">Reason: {{ change.rejection_reason }}</span>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.card { background: var(--cs-surface); border: 1px solid var(--cs-line); border-radius: var(--cs-radius-md); padding: var(--cs-space-4) var(--cs-space-5); box-sizing: border-box; display: flex; flex-direction: column; gap: var(--cs-space-3); }
.card-title { margin: 0; font-size: var(--cs-text-sm); font-weight: 700; color: var(--cs-ink); }
.change { display: flex; flex-direction: column; gap: var(--cs-space-2); padding-bottom: var(--cs-space-3); border-bottom: 1px solid var(--cs-line); }
.change-head { margin: 0; font-size: var(--cs-text-base); color: var(--cs-ink); }
.change-check { margin: 0; font-size: var(--cs-text-sm); font-weight: 600; }
.ok { color: var(--cs-available); }
.warn { color: var(--cs-pending); }
.hint { margin: 0; font-size: var(--cs-text-xs); color: var(--cs-ink-soft); }
.error { margin: 0; font-size: var(--cs-text-sm); color: var(--cs-occupied); }
.btn-accept-change, .btn-reject-change { align-self: flex-start; min-height: 38px; padding: 0 var(--cs-space-4); border: none; border-radius: var(--cs-radius-sm); color: #fff; font: inherit; font-size: var(--cs-text-base); font-weight: 700; cursor: pointer; }
.btn-accept-change { background: var(--cs-signal); }
.btn-accept-change:hover:not(:disabled) { background: var(--cs-signal-strong); }
.btn-accept-change:disabled { background: var(--cs-line-strong); cursor: not-allowed; }
.btn-reject-change { background: var(--cs-occupied); }
.btn-reject-change:disabled { background: var(--cs-occupied-tint); color: var(--cs-occupied); cursor: not-allowed; }
.reject-box { display: flex; flex-direction: column; gap: 6px; }
.reject-label { font-size: var(--cs-text-sm); font-weight: 600; color: var(--cs-ink); }
.change-reason-input { font: inherit; font-size: var(--cs-text-base); padding: var(--cs-space-2) var(--cs-space-3); border: 1px solid var(--cs-line-strong); border-radius: var(--cs-radius-sm); resize: vertical; }
.history { margin: 0; padding-left: 18px; font-size: var(--cs-text-sm); color: var(--cs-ink-soft); display: flex; flex-direction: column; gap: 4px; }
.history-reason { display: block; color: var(--cs-occupied); white-space: pre-wrap; }
</style>
