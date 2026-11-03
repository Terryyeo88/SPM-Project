<script setup>
/**
 * The coordinator's Safety Check section on the event page (Week 7 change
 * #6, Operational Feasibility Check), shown below Venue Booking and
 * Equipment Booking -- a sibling section, like VenueBookingStatus, so it
 * adds to the page without editing the review component.
 *
 *   planning       "Submit for Safety Check" -> POST /events/<id>/safety-review.
 *                  The backend refuses (and says why) unless the session has a
 *                  confirmed venue and nothing pending. After the officer sent
 *                  it back, their comment is shown and the button resubmits.
 *   safety_review  Waiting for the Safety Officer; once approved, "Confirm
 *                  Event" -> POST /events/<id>/confirm (Week 9: "The
 *                  co-ordinator will decide on the subsequent action").
 *   confirmed      Done; the approval is shown.
 *
 * Emits `updated` with the session's new row, so the page refreshes its
 * status, the same as the review component's decisions.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { apiGet, apiPost } from '../lib/api'
import { reviewStatusLabel, safetyCheckState } from '../lib/safetyReviews'

const props = defineProps({
  event: { type: Object, required: true },
})
const emit = defineEmits(['updated'])

const reviews = ref([])
const loading = ref(true)
const loadError = ref('')
const busy = ref(false)
const error = ref('')
const success = ref('')

const check = computed(() => safetyCheckState(props.event, reviews.value))
const latest = computed(() => check.value.latest)

// Review statuses don't all match base.css's 17-name `.cs-status-*` table
// (changes_requested isn't one of them), so map to the indicator-light
// bucket directly -- same mapping as SafetyReviewView.vue.
const REVIEW_PILL_BUCKET = {
  pending: 'pending',
  changes_requested: 'pending',
  approved: 'available',
  confirmed: 'available',
  rejected: 'occupied',
}

function reviewPillClass(status) {
  return `cs-pill--${REVIEW_PILL_BUCKET[status] ?? 'neutral'}`
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    reviews.value = await apiGet(`/events/${props.event.id}/safety-reviews`)
  } catch (requestError) {
    loadError.value = requestError.message
  } finally {
    loading.value = false
  }
}

async function run(action, message) {
  busy.value = true
  error.value = ''
  success.value = ''
  try {
    const updated = await action()
    success.value = message
    await load()
    emit('updated', updated)
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    busy.value = false
  }
}

function submit() {
  return run(
    async () => (await apiPost(`/events/${props.event.id}/safety-review`, {})).event,
    'Submitted for a safety check. The Safety Officer will review it.',
  )
}

function confirmEvent() {
  return run(
    () => apiPost(`/events/${props.event.id}/confirm`, {}),
    'Session confirmed.',
  )
}

function when(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' })
}

onMounted(load)
watch(() => [props.event.id, props.event.status], load)
</script>

<template>
  <section class="safety-check" aria-labelledby="safety-check-heading">
    <h2 id="safety-check-heading">Safety Check</h2>

    <p v-if="loading" class="muted small">Loading safety check...</p>
    <p v-else-if="loadError" class="error" role="alert">Couldn't load the safety check: {{ loadError }}</p>

    <template v-else>
      <div v-if="latest" class="latest">
        <span class="status cs-pill" :class="[`review-${latest.status}`, reviewPillClass(latest.status)]">{{ reviewStatusLabel(latest.status) }}</span>
        <span class="muted small">
          <template v-if="latest.reviewed_at">
            {{ when(latest.reviewed_at) }}<template v-if="latest.reviewed_by_name"> by {{ latest.reviewed_by_name }}</template>
          </template>
          <template v-else>Submitted {{ when(latest.submitted_at) }}</template>
        </span>
      </div>
      <p v-if="latest?.comment" class="comment" :class="{ warn: latest.status !== 'approved' }">
        “{{ latest.comment }}”
      </p>

      <p v-if="check.state === 'not_ready'" class="muted small">
        The safety check comes after planning: once the venue (and any equipment) is confirmed.
      </p>
      <template v-else-if="check.state === 'can_submit' || check.state === 'resubmit'">
        <p class="muted small">
          <template v-if="check.state === 'resubmit' && latest.status !== 'approved'">
            The Safety Officer sent this back. Make the changes, then submit it again.
          </template>
          <template v-else-if="check.state === 'resubmit'">
            This session changed after its safety check, so it needs a new one before it can be confirmed.
          </template>
          <template v-else>
            Before this session can be confirmed, the Safety Officer must check it. Submit it once the venue is
            confirmed and no venue or equipment request is still pending.
          </template>
        </p>
        <button type="button" class="btn primary" :disabled="busy" @click="submit">
          {{ busy ? 'Submitting...' : check.state === 'resubmit' ? 'Resubmit for Safety Check' : 'Submit for Safety Check' }}
        </button>
      </template>
      <p v-else-if="check.state === 'waiting'" class="muted small">Waiting for the Safety Officer to check this session.</p>
      <template v-else-if="check.state === 'approved'">
        <p class="muted small">The Safety Officer approved this session. Confirm it when you're ready.</p>
        <button type="button" class="btn approve" :disabled="busy" @click="confirmEvent">
          {{ busy ? 'Confirming...' : 'Confirm Event' }}
        </button>
      </template>

      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <p v-if="success" class="success" role="status">{{ success }}</p>
    </template>
  </section>
</template>

<style scoped>
.safety-check { display: flex; flex-direction: column; gap: var(--cs-space-3); padding-top: var(--cs-space-4); border-top: 1px solid var(--cs-line); }
h2 { margin: 0; font-size: var(--cs-text-md); font-family: var(--cs-font-display); color: var(--cs-ink); }
.muted { color: var(--cs-ink-soft); }
.small { font-size: var(--cs-text-sm); margin: 0; }
.error { color: var(--cs-occupied); margin: 0; font-size: var(--cs-text-sm); }
.success { color: var(--cs-available); margin: 0; font-size: var(--cs-text-sm); }
.latest { display: flex; align-items: center; gap: var(--cs-space-3); }
.comment { margin: 0; font-size: var(--cs-text-sm); font-style: italic; color: var(--cs-ink); }
.comment.warn { color: var(--cs-pending); }

.btn {
  align-self: flex-start; min-height: 38px; padding: 0 var(--cs-space-4); border: none; border-radius: var(--cs-radius-sm);
  font: inherit; font-size: var(--cs-text-sm); font-weight: 700; cursor: pointer; color: #fff;
}
.btn:disabled { opacity: .6; cursor: not-allowed; }
.primary { background: var(--cs-signal); }
.primary:hover:not(:disabled) { background: var(--cs-signal-strong); }
.approve { background: var(--cs-available); }
</style>
