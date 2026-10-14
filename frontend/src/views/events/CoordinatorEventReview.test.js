import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../lib/api', () => ({ apiGet: vi.fn(), apiPost: vi.fn() }))
vi.mock('../../stores/auth', () => ({ useAuthStore: () => ({ profile: { id: 'coord-1' } }) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))
// The session edit form pulls in room layouts over the API; not under test here.
vi.mock('../../components/EventSessionFields.vue', () => ({ default: { template: '<div />' } }))

import { apiPost } from '../../lib/api'
import CoordinatorEventReview from './CoordinatorEventReview.vue'

function event(status) {
  return {
    id: 'session-1',
    name: 'Annual Tech Symposium',
    status,
    coordinator_id: 'coord-1',
    preferred_start_date: '2099-11-10',
    preferred_end_date: '2099-11-10',
  }
}

function mountWith(status) {
  return mount(CoordinatorEventReview, {
    props: { event: event(status), sessions: [] },
    global: { stubs: { RouterLink: RouterLinkStub } },
  })
}

function cancelButton(wrapper) {
  return wrapper.findAll('button').find((b) => b.text() === 'Cancel Event')
}

// Braces: a function returned from beforeEach is run as teardown.
beforeEach(() => {
  apiPost.mockReset()
})

describe('CoordinatorEventReview -- Cancel Event', () => {
  it.each(['approved', 'planning', 'confirmed'])('offers Cancel Event when the session is %s', (status) => {
    expect(cancelButton(mountWith(status))).toBeTruthy()
  })

  it.each(['under_review', 'completed', 'cancelled', 'rejected'])('does not offer it when %s', (status) => {
    expect(cancelButton(mountWith(status))).toBeUndefined()
  })

  it('asks for a reason before cancelling', async () => {
    const wrapper = mountWith('planning')
    await cancelButton(wrapper).trigger('click')
    await wrapper.find('form').trigger('submit')

    expect(apiPost).not.toHaveBeenCalled()
    expect(wrapper.find('[role="alert"]').text()).toContain('reason for cancelling')
  })

  it('cancels with the reason, reports released equipment and passes the update up', async () => {
    const updated = { ...event('cancelled'), released_equipment_units: 3 }
    apiPost.mockResolvedValue(updated)
    const wrapper = mountWith('planning')

    await cancelButton(wrapper).trigger('click')
    await wrapper.find('#cancel-reason').setValue('  No suitable venue  ')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/events/session-1/cancel', { reason: 'No suitable venue' })
    expect(wrapper.find('[role="status"]').text()).toBe(
      'Session cancelled. 3 reserved equipment units released for other events.',
    )
    expect(wrapper.emitted('updated')[0]).toEqual([updated])
  })

  it('says only that the session was cancelled when no equipment was held', async () => {
    apiPost.mockResolvedValue({ ...event('cancelled'), released_equipment_units: 0 })
    const wrapper = mountWith('approved')

    await cancelButton(wrapper).trigger('click')
    await wrapper.find('#cancel-reason').setValue('Organiser withdrew')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[role="status"]').text()).toBe('Session cancelled.')
  })

  it('shows the error and keeps the panel open if the cancel is refused', async () => {
    apiPost.mockRejectedValue(new Error('This event is no longer Planning'))
    const wrapper = mountWith('planning')

    await cancelButton(wrapper).trigger('click')
    await wrapper.find('#cancel-reason').setValue('No venue')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[role="alert"]').text()).toContain('no longer Planning')
    expect(wrapper.find('#cancel-reason').exists()).toBe(true)
    expect(wrapper.emitted('updated')).toBeUndefined()
  })
})

describe('CoordinatorEventReview -- no Reassign (Week 9: only the Lead reassigns)', () => {
  it.each(['under_review', 'approved', 'planning', 'confirmed'])('offers no Reassign Coordinator when %s', (status) => {
    const wrapper = mountWith(status)
    expect(wrapper.findAll('button').some((b) => /reassign/i.test(b.text()))).toBe(false)
    expect(wrapper.find('#reassign-to').exists()).toBe(false)
  })
})
