import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../lib/api', () => ({ apiGet: vi.fn(), apiPost: vi.fn() }))

import { apiGet, apiPost } from '../lib/api'
import SafetyCheckStatus from './SafetyCheckStatus.vue'

beforeEach(() => {
  apiGet.mockReset()
  apiPost.mockReset()
})

async function render(event, reviews = []) {
  apiGet.mockResolvedValue(reviews)
  const wrapper = mount(SafetyCheckStatus, { props: { event } })
  await flushPromises()
  return wrapper
}

const button = (wrapper, text) => wrapper.findAll('button').find((b) => b.text().includes(text))

describe('SafetyCheckStatus', () => {
  it('loads the session safety history', async () => {
    await render({ id: 'session-1', status: 'planning' })
    expect(apiGet).toHaveBeenCalledWith('/events/session-1/safety-reviews')
  })

  it('submits a planning session and passes the updated session up', async () => {
    const wrapper = await render({ id: 'session-1', status: 'planning' })
    apiPost.mockResolvedValue({ event: { id: 'session-1', status: 'safety_review' }, review: { id: 'r-1' } })

    await button(wrapper, 'Submit for Safety Check').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/events/session-1/safety-review', {})
    expect(wrapper.emitted('updated')[0][0].status).toBe('safety_review')
  })

  it("shows the backend's reason when the session isn't ready", async () => {
    const wrapper = await render({ id: 'session-1', status: 'planning' })
    apiPost.mockRejectedValue(new Error("This session isn't ready for a safety check. No venue booking has been confirmed."))

    await button(wrapper, 'Submit for Safety Check').trigger('click')
    await flushPromises()

    expect(wrapper.find('[role="alert"]').text()).toContain('No venue booking has been confirmed')
    expect(wrapper.emitted('updated')).toBeUndefined()
  })

  it("shows the officer's comment and offers a resubmission after changes were requested", async () => {
    const wrapper = await render({ id: 'session-1', status: 'planning' }, [
      { id: 'r-1', status: 'changes_requested', comment: 'Move the stage away from exit B.', reviewed_at: '2026-10-18T02:00:00Z' },
    ])
    expect(wrapper.text()).toContain('Move the stage away from exit B.')
    expect(button(wrapper, 'Resubmit for Safety Check')).toBeTruthy()
  })

  it('offers nothing to click while the Safety Officer is checking', async () => {
    const wrapper = await render({ id: 'session-1', status: 'safety_review' }, [{ id: 'r-1', status: 'pending' }])
    expect(wrapper.text()).toContain('Waiting for the Safety Officer')
    expect(wrapper.findAll('button')).toHaveLength(0)
  })

  it('confirms an approved session', async () => {
    const wrapper = await render({ id: 'session-1', status: 'safety_review' }, [{ id: 'r-1', status: 'approved' }])
    apiPost.mockResolvedValue({ id: 'session-1', status: 'confirmed' })

    await button(wrapper, 'Confirm Event').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/events/session-1/confirm', {})
    expect(wrapper.emitted('updated')[0][0].status).toBe('confirmed')
  })

  it('offers no submit before planning', async () => {
    const wrapper = await render({ id: 'session-1', status: 'approved' })
    expect(wrapper.findAll('button')).toHaveLength(0)
  })
})
