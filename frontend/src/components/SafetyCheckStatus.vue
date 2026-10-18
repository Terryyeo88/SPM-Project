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
        <span class="status" :class="`review-${latest.status}`">{{ reviewStatusLabel(latest.status) }}</span>
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
.safety-check { display: flex; flex-direction: column; gap: 10px; padding-top: 16px; border-top: 1px solid #dcdcdc; }
h2 { margin: 0; font-size: 15px; color: #222; }
.muted { color: #6b6b6b; }
.small { font-size: 13px; margin: 0; }
.error { color: #a33f3f; margin: 0; font-size: 13px; }
.success { color: #2f6b3f; margin: 0; font-size: 13px; }
.latest { display: flex; align-items: center; gap: 12px; }
.comment { margin: 0; font-size: 13px; font-style: italic; color: #444; }
.comment.warn { color: #8a5a12; }

.status { font-size: 12px; font-weight: 600; border-radius: 10px; padding: 4px 12px; background: #eee; color: #5a5a5a; }
.review-pending { color: #3d4fa8; background: #e8ebfa; }
.review-approved { color: #2f6b3f; background: #eaf5ec; }
.review-changes_requested { color: #8a5a12; background: #f7efe1; }
.review-rejected { color: #a33f3f; background: #f5e6e6; }

.btn {
  align-self: flex-start; min-height: 38px; padding: 0 16px; border: none; border-radius: 4px;
  font: inherit; font-size: 13px; font-weight: 700; cursor: pointer; color: #fff;
}
.btn:disabled { opacity: .6; cursor: not-allowed; }
.primary { background: #2568e8; }
.approve { background: #2f6b3f; }
</style>
