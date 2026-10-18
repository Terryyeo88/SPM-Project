<script setup>
/**
 * Safety Review -- the Safety Officer's Operational Safety Check of one
 * event session (Week 7 change #6). Laid out like the Venue Staff "Booking
 * Review" screen: what to check, then the decision.
 *
 * What to check, per Week 7: "expected attendance, venue capacity and
 * layout, emergency access, accessibility requirements, equipment
 * placement, crowd movement, and any known venue restrictions". The page
 * shows what the system records (the session, its confirmed venue with a
 * capacity / layout / accessibility comparison from lib/venueSuitability,
 * its equipment); emergency access, crowd movement and restrictions are the
 * officer's own judgement -- Week 9: "The safety officer do not need to
 * input but to approve in the system based on all his check".
 *
 * Decisions (POST /safety-reviews/<id>/approve | request-changes | reject):
 * a comment is required to request changes or reject (it tells the
 * coordinator what to fix) and optional to approve. Request changes and
 * reject both send the session back to planning; approve leaves it for the
 * coordinator to confirm (Week 9: "The co-ordinator will decide on the
 * subsequent action"). app.authz is the real enforcement; this page only
 * hides the buttons once the review is decided.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { apiGet, apiPost } from '../../lib/api'
import { formatDateRange, statusLabel } from '../../lib/coordinatorDashboard'
import { timeValue } from '../../lib/eventSessions'
import { DECISIONS, decisionCommentError, reviewStatusLabel } from '../../lib/safetyReviews'
import { checkSuitability } from '../../lib/venueSuitability'
import AppNavBar from '../../components/AppNavBar.vue'

const route = useRoute()

const review = ref(null)
const loading = ref(true)
const loadError = ref('')

const decision = ref(null) // null | 'approve' | 'request_changes' | 'reject'
const comment = ref('')
const busy = ref(false)
const error = ref('')
const success = ref('')

const event = computed(() => review.value?.event ?? null)
const isPending = computed(() => review.value?.status === 'pending')
const backTab = computed(() => (isPending.value ? 'checkSafety' : 'checked'))

const LABELS = {
  wheelchair_access: 'Wheelchair access',
  lift_access: 'Lift access',
  removable_seats: 'Removable seats',
  extra_legroom_seats: 'Seats with extra legroom',
  microphone: 'Microphones',
  projector: 'Projectors',
  screen: 'Screens',
  wifi: 'WiFi',
}

function label(item) {
  return LABELS[item] ?? item
}

function listItems(items) {
  if (!items?.length) return 'None specified'
  return items
    .map((entry) => {
      const item = entry?.item ?? entry
      const quantity = entry?.quantity && item !== 'wifi' ? ` × ${entry.quantity}` : ''
      return `${label(item)}${quantity}`
    })
    .join(', ')
}

const sessionWhen = computed(() => {
  if (!event.value) return ''
  const range = formatDateRange(event.value.preferred_start_date, event.value.preferred_end_date)
  const times = [timeValue(event.value.preferred_start_time), timeValue(event.value.preferred_end_time)]
    .filter(Boolean).join(' – ')
  return times ? `${range} · ${times}` : range
})

const venues = computed(() => (review.value?.venue_bookings ?? []).map((booking) => ({
  booking,
  venue: booking.venues ?? {},
  checks: checkSuitability(event.value, booking.venues ?? {}),
})))

function requestLines(request) {
  return (request.equipment_request_items ?? [])
    .map((line) => `${label(line.equipment_types?.name)} × ${line.quantity}`)
    .join(', ') || 'No items'
}

function when(iso) {
  if (!iso) return ''
  return new Date(iso).toLocaleString('en-GB', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    review.value = await apiGet(`/safety-reviews/${route.params.reviewId}`)
  } catch (requestError) {
    loadError.value = requestError.message
  } finally {
    loading.value = false
  }
}

function choose(key) {
  decision.value = decision.value === key ? null : key
  error.value = ''
}

async function submitDecision() {
  const problem = decisionCommentError(decision.value, comment.value)
  if (problem) {
    error.value = problem
    return
  }
  busy.value = true
  error.value = ''
  try {
    const { path } = DECISIONS[decision.value]
    const decided = await apiPost(`/safety-reviews/${review.value.id}/${path}`, { comment: comment.value.trim() || null })
    review.value = { ...review.value, ...decided }
    success.value = decided.status === 'approved'
      ? 'Approved. The coordinator can now confirm this session.'
      : 'Sent back to the coordinator. The session is in planning again until they resubmit it.'
    decision.value = null
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    busy.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <AppNavBar />
    <main class="content">
      <div class="container">
        <router-link :to="{ name: 'dashboard', query: { tab: backTab } }" class="back-link">&larr; Back to safety checks</router-link>

        <p v-if="loading" class="message">Loading safety review...</p>
        <p v-else-if="loadError" class="message error" role="alert">{{ loadError }}</p>

        <template v-else-if="review">
          <div class="page-heading">
            <h1 class="page-title">{{ event?.name }}</h1>
            <span class="page-subtitle">{{ sessionWhen }}</span>
          </div>
          <span class="status" :class="`review-${review.status}`">{{ reviewStatusLabel(review.status) }}</span>
          <p class="muted small">
            Submitted by {{ review.submitted_by_name || 'the coordinator' }} on {{ when(review.submitted_at) }}.
          </p>

          <section class="card" aria-labelledby="session-heading">
            <h2 id="session-heading" class="card-title">The Session</h2>
            <div class="detail-row"><span class="muted">When</span><span class="value">{{ sessionWhen }}</span></div>
            <div class="detail-row">
              <span class="muted">Expected attendance</span>
              <span class="value">{{ event?.expected_attendance ?? 'Not specified' }}</span>
            </div>
            <div class="detail-row">
              <span class="muted">Room layout</span>
              <span class="value">{{ event?.room_layout || 'Not specified' }}</span>
            </div>
            <div class="detail-row">
              <span class="muted">Accessibility needs</span>
              <span class="value">{{ listItems(event?.accessibility_needs) }}</span>
            </div>
            <div class="detail-row">
              <span class="muted">Equipment asked for</span>
              <span class="value">{{ listItems(event?.equipment_needed?.equipment) }}</span>
            </div>
            <div v-if="event?.special_requests" class="detail-row">
              <span class="muted">Special requests</span>
              <span class="value value-text">{{ event.special_requests }}</span>
            </div>
          </section>

          <section class="card" aria-labelledby="venue-heading">
            <h2 id="venue-heading" class="card-title">Venue</h2>
            <p v-if="!venues.length" class="muted small">No confirmed venue booking found for this session.</p>
            <div v-for="{ booking, venue, checks } in venues" :key="booking.id" class="venue">
              <div class="detail-row">
                <span class="muted">Venue</span>
                <span class="value">{{ venue.name }}<template v-if="venue.location"> · {{ venue.location }}</template></span>
              </div>
              <div class="detail-row"><span class="muted">Capacity</span><span class="value">{{ venue.capacity ?? '—' }}</span></div>
              <div class="detail-row">
                <span class="muted">Supported layouts</span>
                <span class="value">{{ (venue.supported_layouts ?? []).join(', ') || 'None listed' }}</span>
              </div>
              <div class="detail-row">
                <span class="muted">Accessibility features</span>
                <span class="value">{{ listItems(venue.accessibility_features) }}</span>
              </div>
              <div v-for="check in checks" :key="check.label" class="suitability-row">
                <span class="suitability-icon" :class="check.ok ? 'ok' : 'warn'">{{ check.ok ? '✓' : '!' }}</span>
                <div>
                  <span class="suitability-label">{{ check.label }}</span>
                  <p class="muted small">{{ check.detail }}</p>
                </div>
              </div>
            </div>
          </section>

          <section class="card" aria-labelledby="equipment-heading">
            <h2 id="equipment-heading" class="card-title">Equipment</h2>
            <p v-if="!review.equipment_requests?.length" class="muted small">No equipment has been requested for this session.</p>
            <div v-for="request in review.equipment_requests" :key="request.id" class="detail-row">
              <span class="muted">{{ requestLines(request) }}</span>
              <span class="value">{{ statusLabel(request.status) }}</span>
            </div>
          </section>

          <section class="card" aria-labelledby="judgement-heading">
            <h2 id="judgement-heading" class="card-title">Your Own Checks</h2>
            <p class="muted small">
              Not recorded in the system, so check these yourself before deciding: emergency access, equipment
              placement, crowd movement, and any known venue restrictions.
            </p>
          </section>

          <section v-if="review.history?.length" class="card" aria-labelledby="history-heading">
            <h2 id="history-heading" class="card-title">Earlier Safety Checks</h2>
            <div v-for="earlier in review.history" :key="earlier.id" class="history-row">
              <span class="status" :class="`review-${earlier.status}`">{{ reviewStatusLabel(earlier.status) }}</span>
              <span class="muted small">
                {{ when(earlier.reviewed_at || earlier.submitted_at) }}<template v-if="earlier.reviewed_by_name"> by {{ earlier.reviewed_by_name }}</template>
              </span>
              <p v-if="earlier.comment" class="small comment">“{{ earlier.comment }}”</p>
            </div>
          </section>

          <section class="decision" aria-labelledby="decision-heading">
            <h2 id="decision-heading">Decision</h2>

            <template v-if="!isPending">
              <p class="muted small">
                {{ reviewStatusLabel(review.status) }}<template v-if="review.reviewed_by_name"> by {{ review.reviewed_by_name }}</template>
                on {{ when(review.reviewed_at) }}.
              </p>
              <p v-if="review.comment" class="small comment">“{{ review.comment }}”</p>
            </template>

            <template v-else>
              <div class="buttons">
                <button type="button" class="btn approve" :aria-pressed="decision === 'approve'" :disabled="busy" @click="choose('approve')">
                  Approve
                </button>
                <button type="button" class="btn changes" :aria-pressed="decision === 'request_changes'" :disabled="busy"
                  @click="choose('request_changes')">
                  Request Changes
                </button>
                <button type="button" class="btn reject" :aria-pressed="decision === 'reject'" :disabled="busy" @click="choose('reject')">
                  Reject
                </button>
              </div>

              <form v-if="decision" class="panel" :class="`panel-${decision}`" @submit.prevent="submitDecision">
                <label for="safety-comment">
                  Comment<template v-if="!DECISIONS[decision].commentRequired"> (optional)</template>
                </label>
                <textarea id="safety-comment" v-model="comment" rows="3"
                  :placeholder="decision === 'approve'
                    ? 'Anything the coordinator should know.'
                    : 'Tell the coordinator what to fix before they resubmit.'" />
                <p v-if="decision !== 'approve'" class="muted small">
                  The session goes back to planning. The coordinator fixes it and submits it again.
                </p>
                <div class="panel-actions">
                  <button type="submit" class="btn small solid" :disabled="busy">
                    {{ busy ? 'Saving...' : `Confirm: ${DECISIONS[decision].label}` }}
                  </button>
                  <button type="button" class="btn small neutral" :disabled="busy" @click="choose(decision)">Cancel</button>
                </div>
              </form>
            </template>

            <p v-if="error" class="message error" role="alert">{{ error }}</p>
            <p v-if="success" class="message success" role="status">{{ success }}</p>
          </section>
        </template>
      </div>
    </main>
  </div>
</template>

<style scoped src="../../styles/event-form.css"></style>
<style scoped>
.detail-row { display: flex; justify-content: space-between; gap: 16px; padding: 8px 0; border-bottom: 1px solid #ececec; font-size: 13px; }
.detail-row:last-child { border-bottom: none; }
.muted { color: #6b6b6b; }
.small { font-size: 12px; margin: 4px 0 0; }
.value { color: #2a2a2a; font-weight: 600; text-align: right; }
.value-text { font-weight: 400; text-align: left; white-space: pre-line; overflow-wrap: anywhere; flex: 1; max-width: 75%; }
.comment { font-style: italic; color: #444; }
.venue + .venue { margin-top: 12px; padding-top: 12px; border-top: 1px solid #dcdcdc; }
.history-row { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; padding: 8px 0; border-bottom: 1px solid #ececec; }
.history-row:last-child { border-bottom: none; }
.history-row .comment { flex-basis: 100%; }

.status { font-size: 12px; font-weight: 600; border-radius: 10px; padding: 4px 12px; white-space: nowrap; background: #eee; color: #5a5a5a; align-self: flex-start; }
.review-pending { color: #3d4fa8; background: #e8ebfa; }
.review-approved, .review-confirmed { color: #2f6b3f; background: #eaf5ec; }
.review-changes_requested { color: #8a5a12; background: #f7efe1; }
.review-rejected { color: #a33f3f; background: #f5e6e6; }

.suitability-row { display: flex; align-items: flex-start; gap: 10px; padding: 8px 0; }
.suitability-icon {
  flex: 0 0 auto; width: 20px; height: 20px; border-radius: 50%; display: flex; align-items: center;
  justify-content: center; font-size: 12px; font-weight: 700;
}
.suitability-icon.ok { background: #eaf5ec; color: #2f6b3f; }
.suitability-icon.warn { background: #fdf6ec; color: #8a5a12; }
.suitability-label { font-size: 13px; font-weight: 600; color: #2a2a2a; }

.decision { display: flex; flex-direction: column; gap: 14px; }
.decision h2 { margin: 0; font-size: 15px; color: #222; }
.buttons { display: flex; flex-wrap: wrap; gap: 12px; }
.btn {
  min-height: 46px; padding: 0 22px; border-radius: 4px; font: inherit; font-size: 14px; font-weight: 700;
  cursor: pointer; background: #fff;
}
.btn:disabled { opacity: .6; cursor: not-allowed; }
.btn.small { min-height: 38px; padding: 0 16px; font-size: 13px; }
.approve { border: 1px solid #2f6b3f; color: #2f6b3f; }
.approve[aria-pressed='true'] { background: #2f6b3f; color: #fff; }
.changes { border: 1px solid #8a5a12; color: #8a5a12; }
.changes[aria-pressed='true'] { background: #8a5a12; color: #fff; }
.reject { border: 1px solid #a33f3f; color: #a33f3f; }
.reject[aria-pressed='true'] { background: #a33f3f; color: #fff; }
.solid { border: none; background: #2568e8; color: #fff; }
.neutral { border: 1px solid #b8b8b8; color: #444; }

.panel {
  display: flex; flex-direction: column; gap: 8px;
  border-radius: 6px; padding: 16px 18px; background: #f7f7f7; border: 1px solid #d0d0d0;
}
.panel-approve { background: #f1f8f2; border-color: #a9cdb1; }
.panel-request_changes { background: #fdf6ec; border-color: #e3b877; }
.panel-reject { background: #fbf1f1; border-color: #d9a3a3; }
.panel label { font-size: 12px; font-weight: 600; letter-spacing: .04em; text-transform: uppercase; color: #6a6a6a; }
.panel textarea {
  box-sizing: border-box; width: 100%; padding: 10px 12px; border: 1px solid #b8b8b8; border-radius: 4px;
  background: #fff; font: inherit; font-size: 14px; resize: vertical;
}
.panel-actions { display: flex; gap: 10px; margin-top: 4px; }
</style>
