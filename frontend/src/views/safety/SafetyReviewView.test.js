import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiGet = vi.fn()
const apiPost = vi.fn()
vi.mock('../../lib/api', () => ({ apiGet: (...args) => apiGet(...args), apiPost: (...args) => apiPost(...args) }))
// AppNavBar pulls in the auth store and the Supabase client -- irrelevant here.
vi.mock('../../components/AppNavBar.vue', () => ({ default: { template: '<div />' } }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { reviewId: 'review-1' } }) }))

import SafetyReviewView from './SafetyReviewView.vue'

const REVIEW = {
  id: 'review-1',
  status: 'pending',
  event_id: 'session-1',
  submitted_at: '2026-10-18T02:00:00Z',
  submitted_by_name: 'Alice Tan',
  event: {
    id: 'session-1',
    name: 'Tech Summit 2027',
    expected_attendance: 150,
    room_layout: 'theatre',
    accessibility_needs: [{ item: 'wheelchair_access' }],
    equipment_needed: { equipment: [{ item: 'microphone', quantity: 2 }] },
    preferred_start_date: '2027-02-22',
  },
  venue_bookings: [
    { id: 'b-1', venues: { name: 'Auditorium A', capacity: 120, supported_layouts: ['theatre'], accessibility_features: [] } },
  ],
  equipment_requests: [],
  history: [],
}

beforeEach(() => {
  apiGet.mockReset()
  apiPost.mockReset()
})

async function render(review = REVIEW) {
  apiGet.mockResolvedValue(review)
  const wrapper = mount(SafetyReviewView, {
    global: { stubs: { 'router-link': { template: '<a><slot /></a>' } } },
  })
  await flushPromises()
  return wrapper
}

const button = (wrapper, text) => wrapper.findAll('button').find((b) => b.text().trim() === text)

describe('SafetyReviewView', () => {
  it('shows what to check, including a capacity warning against the confirmed venue', async () => {
    const wrapper = await render()
    expect(apiGet).toHaveBeenCalledWith('/safety-reviews/review-1')
    expect(wrapper.text()).toContain('Tech Summit 2027')
    expect(wrapper.text()).toContain('Auditorium A')
    expect(wrapper.text()).toContain('Venue holds only 120, but the event expects 150.')
    expect(wrapper.text()).toContain('Venue is missing: wheelchair_access.')
    expect(wrapper.text()).toContain('Microphones × 2')
  })

  it('approves without a comment', async () => {
    const wrapper = await render()
    apiPost.mockResolvedValue({ id: 'review-1', status: 'approved' })

    await button(wrapper, 'Approve').trigger('click')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/safety-reviews/review-1/approve', { comment: null })
    expect(wrapper.text()).toContain('The coordinator can now confirm this session.')
  })

  it('will not request changes without a comment', async () => {
    const wrapper = await render()
    await button(wrapper, 'Request Changes').trigger('click')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(apiPost).not.toHaveBeenCalled()
    expect(wrapper.find('[role="alert"]').text()).toContain('what needs to change')
  })

  it('rejects with a comment, sending it to the reject route', async () => {
    const wrapper = await render()
    apiPost.mockResolvedValue({ id: 'review-1', status: 'rejected', comment: 'Over capacity.' })

    await button(wrapper, 'Reject').trigger('click')
    await wrapper.find('textarea').setValue('  Over capacity.  ')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/safety-reviews/review-1/reject', { comment: 'Over capacity.' })
    expect(wrapper.text()).toContain('Sent back to the coordinator.')
  })

  it('shows a decided review read-only, with its comment', async () => {
    const wrapper = await render({
      ...REVIEW,
      status: 'changes_requested',
      comment: 'Move the stage away from exit B.',
      reviewed_by_name: 'Hannah Lee',
      reviewed_at: '2026-10-18T05:00:00Z',
    })
    expect(button(wrapper, 'Approve')).toBeUndefined()
    expect(wrapper.text()).toContain('Move the stage away from exit B.')
    expect(wrapper.text()).toContain('Hannah Lee')
  })
})
