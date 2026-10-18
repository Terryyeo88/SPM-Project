/**
 * Pure helpers for the Operational Feasibility Check (Week 7 change #6),
 * kept out of the components so they can be unit-tested without mounting:
 *
 *   - the Safety Officer dashboard's two tabs (Check Safety / Checked) and
 *     how its reviews become rows for the coordinator-style request cards;
 *   - the coordinator's Safety Check section on the event page: what it
 *     can do next (submit, wait, confirm, resubmit).
 *
 * A review is one SUBMISSION of one event session (backend:
 * public.safety_reviews). The dashboard's list (GET /safety-reviews)
 * embeds the session as `review.event`.
 */
import { statusLabel } from './coordinatorDashboard'

export const SAFETY_TABS = Object.freeze([
  Object.freeze({ key: 'checkSafety', label: 'Check Safety', statuses: Object.freeze(['pending']) }),
  Object.freeze({
    key: 'checked',
    label: 'Checked',
    statuses: Object.freeze(['approved', 'rejected', 'changes_requested']),
  }),
])

export const REVIEW_STATUS_LABELS = Object.freeze({
  pending: 'Awaiting check',
  approved: 'Approved',
  rejected: 'Rejected',
  changes_requested: 'Changes requested',
})

export function reviewStatusLabel(status) {
  return REVIEW_STATUS_LABELS[status] ?? statusLabel(status)
}

/** true if `key` names one of SAFETY_TABS (validates the ?tab= query param). */
export function isSafetyTab(key) {
  return SAFETY_TABS.some((tab) => tab.key === key)
}

/**
 * Splits reviews into { checkSafety: [], checked: [] }. Check Safety is
 * oldest first (first come, first served); Checked is most recently
 * decided first.
 */
export function groupReviewsByTab(reviews) {
  const groups = Object.fromEntries(SAFETY_TABS.map((tab) => [tab.key, []]))
  for (const review of reviews ?? []) {
    const tab = SAFETY_TABS.find((t) => t.statuses.includes(review.status))
    if (tab) groups[tab.key].push(review)
  }
  groups.checkSafety.sort((a, b) => (a.submitted_at ?? '').localeCompare(b.submitted_at ?? ''))
  groups.checked.sort((a, b) => (b.reviewed_at ?? '').localeCompare(a.reviewed_at ?? ''))
  return groups
}

/**
 * One row per review, shaped like an event session (so lib/eventSessions'
 * groupIntoRequests can make one card per request), carrying the review.
 * The same session can appear twice in Checked (sent back, then resubmitted),
 * so rows are keyed by `reviewId`, not the session id.
 */
export function reviewRows(reviews) {
  return (reviews ?? []).map((review) => ({ ...(review.event ?? {}), id: review.event_id, reviewId: review.id, review }))
}

/** Case-insensitive match on the session's event name. */
export function filterReviews(reviews, query) {
  const needle = (query ?? '').trim().toLowerCase()
  if (!needle) return reviews
  return reviews.filter((review) => (review.event?.name ?? '').toLowerCase().includes(needle))
}

// -- the three decisions ---------------------------------------------------------

export const DECISIONS = Object.freeze({
  approve: Object.freeze({ path: 'approve', label: 'Approve', commentRequired: false }),
  request_changes: Object.freeze({ path: 'request-changes', label: 'Request Changes', commentRequired: true }),
  reject: Object.freeze({ path: 'reject', label: 'Reject', commentRequired: true }),
})

/** An error message for the comment box, or '' if the decision can be sent. */
export function decisionCommentError(decisionKey, comment) {
  const decision = DECISIONS[decisionKey]
  if (!decision) return 'Choose a decision.'
  if (decision.commentRequired && !(comment ?? '').trim()) {
    return decisionKey === 'reject'
      ? 'Tell the coordinator why the safety arrangement is rejected.'
      : 'Tell the coordinator what needs to change.'
  }
  return ''
}

// -- the coordinator's Safety Check section ----------------------------------------

/**
 * What the coordinator's Safety Check section shows for one session, from
 * the session and its reviews (GET /events/<id>/safety-reviews, newest first):
 *
 *   state        'not_ready'   before planning (nothing to do yet)
 *                'can_submit'  in planning, never submitted
 *                'resubmit'    in planning after the officer sent it back
 *                'waiting'     in safety_review, awaiting the officer
 *                'approved'    in safety_review, approved: confirm it
 *                'done'        confirmed or later
 *                'closed'      cancelled / rejected request
 *   latest       the most recent review (or null)
 *
 * Whether the arrangements are actually ready to submit (a confirmed venue,
 * nothing pending) is checked by the backend, which explains a refusal.
 */
export function safetyCheckState(event, reviews) {
  const latest = (reviews ?? [])[0] ?? null
  const status = event?.status
  let state
  if (status === 'planning') state = latest && latest.status !== 'pending' ? 'resubmit' : 'can_submit'
  else if (status === 'safety_review') state = latest?.status === 'approved' ? 'approved' : 'waiting'
  else if (status === 'confirmed' || status === 'completed') state = 'done'
  else if (status === 'cancelled' || status === 'rejected') state = 'closed'
  else state = 'not_ready'
  return { state, latest }
}
