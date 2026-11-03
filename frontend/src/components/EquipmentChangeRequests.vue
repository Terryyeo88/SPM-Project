<script setup>
/**
 * Ask Technical Support to change the quantity on a confirmed equipment
 * request (Update quantity on an existing equipment reservation, Nawaz,
 * Sprint 3, IS-43) -- the Event Coordinator's side.
 *
 * Shown under a confirmed request in the Equipment Booking section while
 * the event is still live. The ask does NOT change the reservation: it is
 * stored as pending until Technical Support accept it (the quantity and
 * the allocated units then change) or reject it with a reason, which is
 * shown here.
 *
 * It also holds the coordinator's Cancel button for the request (pending or
 * confirmed): cancelling frees its equipment so they can ask again for a
 * different date and time. Two clicks, so a mis-click cannot release
 * reserved units.
 *
 * Data: GET/POST /equipment/requests/<id>/change-requests,
 * POST /equipment/requests/<id>/cancel
 */
import { computed, onMounted, ref } from 'vue'
import { apiGet, apiPost } from '../lib/api'
import { describeChange, formatPeriod, summariseItems, validateChangeQuantity } from '../lib/equipment'

const props = defineProps({
  request: { type: Object, required: true },
  canChange: { type: Boolean, default: true },
})

const changes = ref([])
const drafts = ref({})
const errors = ref({})
const submitting = ref('')
const loadError = ref('')
const confirmingCancel = ref(false)
const cancelling = ref(false)
const cancelError = ref('')

const isConfirmed = computed(() => props.request.status === 'confirmed')

const pendingByItem = computed(() => {
  const map = new Map()
  for (const change of changes.value) {
    if (change.status === 'pending') map.set(change.request_item_id, change)
  }
  return map
})
const decided = computed(() => changes.value.filter((change) => change.status !== 'pending'))

async function load() {
  loadError.value = ''
  // A pending request has no reservations, so nothing can be changed on it.
  if (!isConfirmed.value) return
  try {
    const result = await apiGet(`/equipment/requests/${props.request.id}/change-requests`)
    changes.value = Array.isArray(result) ? result : []
  } catch (requestError) {
    loadError.value = requestError.message
  }
}

async function submit(item) {
  const check = validateChangeQuantity(drafts.value[item.id], item.quantity)
  if (!check.valid) {
    errors.value = { ...errors.value, [item.id]: check.error }
    return
  }
  errors.value = { ...errors.value, [item.id]: '' }
  submitting.value = item.id
  try {
    await apiPost(`/equipment/requests/${props.request.id}/change-requests`, {
      item_id: item.id,
      quantity: check.quantity,
    })
    drafts.value = { ...drafts.value, [item.id]: '' }
    await load()
  } catch (requestError) {
    errors.value = { ...errors.value, [item.id]: requestError.message }
  } finally {
    submitting.value = ''
  }
}

const emit = defineEmits(['cancelled'])

async function cancelRequest() {
  cancelError.value = ''
  cancelling.value = true
  try {
    await apiPost(`/equipment/requests/${props.request.id}/cancel`, {})
    confirmingCancel.value = false
    emit('cancelled')
  } catch (requestError) {
    cancelError.value = requestError.message
  } finally {
    cancelling.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="changes">
    <h4 class="manage-title">
      {{ summariseItems(request.items) }} &middot; {{ formatPeriod(request.needed_start, request.needed_end) }}
    </h4>
    <p v-if="loadError" class="error" role="alert">Couldn't load quantity changes: {{ loadError }}</p>

    <div v-if="canChange && isConfirmed" class="change-forms">
      <span class="change-label">Change a quantity</span>
      <div v-for="item in request.items" :key="item.id" class="change-row">
        <span class="change-item">{{ item.type }} × {{ item.quantity }}</span>
        <p v-if="pendingByItem.get(item.id)" class="change-pending">
          Waiting for Technical Support: {{ pendingByItem.get(item.id).old_quantity }} →
          {{ pendingByItem.get(item.id).new_quantity }}
        </p>
        <form v-else class="change-form" @submit.prevent="submit(item)">
          <label :for="`change-${item.id}`" class="visually-hidden">New quantity for {{ item.type }}</label>
          <input
            :id="`change-${item.id}`"
            v-model="drafts[item.id]"
            class="change-input"
            type="number"
            min="1"
            step="1"
            placeholder="New qty"
          />
          <button type="submit" class="btn small btn-change" :disabled="submitting === item.id">
            {{ submitting === item.id ? 'Sending...' : 'Request change' }}
          </button>
        </form>
        <p v-if="errors[item.id]" class="error" role="alert">{{ errors[item.id] }}</p>
      </div>
    </div>

    <div v-if="canChange" class="cancel-box">
      <button v-if="!confirmingCancel" type="button" class="btn small btn-cancel" @click="confirmingCancel = true">
        Cancel this booking
      </button>
      <div v-else class="cancel-confirm" role="group" aria-label="Confirm cancelling this booking">
        <p class="cancel-warning">
          Cancel this booking?
          <template v-if="isConfirmed">Its reserved equipment is released and any waiting change is dropped.</template>
          You can then request equipment again for a different date and time.
        </p>
        <button type="button" class="btn small btn-cancel-confirm" :disabled="cancelling" @click="cancelRequest">
          {{ cancelling ? 'Cancelling...' : 'Yes, cancel booking' }}
        </button>
        <button type="button" class="btn small" :disabled="cancelling" @click="confirmingCancel = false">
          Keep it
        </button>
      </div>
      <p v-if="cancelError" class="error" role="alert">{{ cancelError }}</p>
    </div>

    <ul v-if="decided.length" class="change-history" aria-label="Past quantity changes">
      <li v-for="change in decided" :key="change.id" :class="`change-${change.status}`">
        <strong>{{ change.status === 'accepted' ? 'Accepted' : 'Rejected' }}:</strong>
        {{ describeChange(change) }}
        <span v-if="change.status === 'rejected'" class="change-reason">
          Reason: {{ change.rejection_reason ?? 'No reason was recorded.' }}
        </span>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.changes { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; }
h4 { margin: 0; font-size: 13px; color: #222; }
.manage-title { font-size: 14px; }
.change-label { font-size: 12px; font-weight: 700; color: #555; }
.cancel-box { display: flex; flex-direction: column; gap: 6px; }
.cancel-confirm { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.cancel-warning { margin: 0; flex-basis: 100%; font-size: 13px; color: #8a5a12; }
.btn-cancel-confirm { background: #b42318; color: #fff; border: none; }
.change-forms { display: flex; flex-direction: column; gap: 8px; }
.change-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px 12px; font-size: 13px; }
.change-item { min-width: 140px; text-transform: capitalize; }
.change-form { display: flex; gap: 8px; align-items: center; }
.change-input { width: 90px; padding: 6px 8px; font: inherit; border: 1px solid #c8c8c8; border-radius: 4px; }
.change-pending { margin: 0; color: #8a5a12; font-weight: 600; }
.change-history { margin: 0; padding-left: 18px; font-size: 12px; color: #444; display: flex; flex-direction: column; gap: 4px; }
.change-reason { display: block; color: #a33f3f; white-space: pre-wrap; }
.error { margin: 0; font-size: 12px; color: #a33f3f; }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
</style>
