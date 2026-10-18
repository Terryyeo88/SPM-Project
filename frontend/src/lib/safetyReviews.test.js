import { describe, expect, it } from 'vitest'
import {
  DECISIONS,
  decisionCommentError,
  filterReviews,
  groupReviewsByTab,
  isSafetyTab,
  reviewRows,
  reviewStatusLabel,
  safetyCheckState,
} from './safetyReviews'

const review = (id, status, extra = {}) => ({
  id,
  status,
  event_id: `session-${id}`,
  event: { id: `session-${id}`, name: `Event ${id}`, shared_event_id: 'req-1', preferred_start_date: '2026-11-10' },
  ...extra,
})

describe('groupReviewsByTab', () => {
  it('puts pending reviews under Check Safety and decided ones under Checked', () => {
    const groups = groupReviewsByTab([
      review('a', 'pending'),
      review('b', 'approved'),
      review('c', 'rejected'),
      review('d', 'changes_requested'),
    ])
    expect(groups.checkSafety.map((r) => r.id)).toEqual(['a'])
    expect(groups.checked.map((r) => r.id).sort()).toEqual(['b', 'c', 'd'])
  })

  it('orders Check Safety oldest submission first and Checked most recent decision first', () => {
    const groups = groupReviewsByTab([
      review('new', 'pending', { submitted_at: '2026-10-18T02:00:00Z' }),
      review('old', 'pending', { submitted_at: '2026-10-17T02:00:00Z' }),
      review('earlier', 'approved', { reviewed_at: '2026-10-16T02:00:00Z' }),
      review('later', 'rejected', { reviewed_at: '2026-10-18T05:00:00Z' }),
    ])
    expect(groups.checkSafety.map((r) => r.id)).toEqual(['old', 'new'])
    expect(groups.checked.map((r) => r.id)).toEqual(['later', 'earlier'])
  })

  it('copes with no reviews', () => {
    expect(groupReviewsByTab(undefined)).toEqual({ checkSafety: [], checked: [] })
  })
})

describe('reviewRows', () => {
  it('turns each review into a session-shaped row carrying the review, keyed by review id', () => {
    const [row] = reviewRows([review('a', 'pending')])
    expect(row.id).toBe('session-a')
    expect(row.shared_event_id).toBe('req-1')
    expect(row.reviewId).toBe('a')
    expect(row.review.status).toBe('pending')
  })

  it('keeps a session that was checked twice as two rows', () => {
    const rows = reviewRows([
      review('first', 'changes_requested', { event_id: 's-1', event: { id: 's-1' } }),
      review('second', 'approved', { event_id: 's-1', event: { id: 's-1' } }),
    ])
    expect(rows.map((r) => r.reviewId)).toEqual(['first', 'second'])
    expect(new Set(rows.map((r) => r.id))).toEqual(new Set(['s-1']))
  })
})

describe('filterReviews', () => {
  it('matches the event name, ignoring case and surrounding spaces', () => {
    const reviews = [review('a', 'pending'), review('b', 'pending', { event: { name: 'Gala Dinner' } })]
    expect(filterReviews(reviews, '  gala ').map((r) => r.id)).toEqual(['b'])
    expect(filterReviews(reviews, '')).toBe(reviews)
  })
})

describe('labels and tabs', () => {
  it('names each review status for people', () => {
    expect(reviewStatusLabel('pending')).toBe('Awaiting check')
    expect(reviewStatusLabel('changes_requested')).toBe('Changes requested')
  })

  it('recognises only its own tab keys', () => {
    expect(isSafetyTab('checked')).toBe(true)
    expect(isSafetyTab('needsReview')).toBe(false)
  })
})

describe('decisionCommentError', () => {
  it('lets an approval go without a comment', () => {
    expect(decisionCommentError('approve', '')).toBe('')
  })

  it.each(['reject', 'request_changes'])('needs a comment to %s', (key) => {
    expect(decisionCommentError(key, '   ')).not.toBe('')
    expect(decisionCommentError(key, 'Exit B is blocked.')).toBe('')
  })

  it('needs a decision', () => {
    expect(decisionCommentError(null, 'x')).toBe('Choose a decision.')
  })

  it('posts each decision to its own route', () => {
    expect(Object.values(DECISIONS).map((d) => d.path).sort()).toEqual(['approve', 'reject', 'request-changes'])
  })
})

describe('safetyCheckState', () => {
  const event = (status) => ({ id: 'session-1', status })

  it('offers a first submission in planning', () => {
    expect(safetyCheckState(event('planning'), []).state).toBe('can_submit')
  })

  it('offers a resubmission once the officer has sent it back', () => {
    const { state, latest } = safetyCheckState(event('planning'), [{ status: 'changes_requested', comment: 'Fix exits' }])
    expect(state).toBe('resubmit')
    expect(latest.comment).toBe('Fix exits')
  })

  it('waits while the review is pending, and offers Confirm once it is approved', () => {
    expect(safetyCheckState(event('safety_review'), [{ status: 'pending' }]).state).toBe('waiting')
    expect(safetyCheckState(event('safety_review'), [{ status: 'approved' }, { status: 'rejected' }]).state).toBe('approved')
  })

  it.each([
    ['approved', 'not_ready'],
    ['under_review', 'not_ready'],
    ['confirmed', 'done'],
    ['completed', 'done'],
    ['cancelled', 'closed'],
  ])('a session that is %s is %s', (status, expected) => {
    expect(safetyCheckState(event(status), []).state).toBe(expected)
  })
})
