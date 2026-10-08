import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../lib/api', () => ({ apiGet: vi.fn(), apiPost: vi.fn() }))

import { apiGet, apiPost } from '../lib/api'
import EventChangeRequests from './EventChangeRequests.vue'

function session(overrides = {}) {
  return {
    id: 'session-1',
    status: 'confirmed',
    name: 'Community Conference',
    description: 'A community conference.',
    purpose: 'Knowledge sharing.',
    preferred_start_date: '2099-11-10',
    preferred_start_time: '09:00:00',
    preferred_end_date: '2099-11-10',
    preferred_end_time: '17:00:00',
    expected_attendance: 100,
    accessibility_needs: [],
    room_layout: 'theatre',
    equipment_needed: { equipment: [] },
    registration_needs: false,
    registration_start_datetime: null,
    registration_end_datetime: null,
    special_requests: null,
    ...overrides,
  }
}

const pending = {
  event_change_req_id: 'change-1',
  event_id: 'session-1',
  status: 'pending',
  created_at: '2026-10-08T01:00:00Z',
  requested_changes: { room_layout: 'banquet' },
  previous_values: { room_layout: 'theatre' },
  reason: 'Dinner added.',
}

async function mountAs(role, { changes = [], event = session() } = {}) {
  apiGet.mockResolvedValue(changes)
  const wrapper = mount(EventChangeRequests, { props: { event, sessions: [event], role } })
  await flushPromises()
  return wrapper
}

function button(wrapper, text) {
  return wrapper.findAll('button').find((b) => b.text() === text)
}

beforeEach(() => {
  apiGet.mockReset()
  apiPost.mockReset()
})

describe('EventChangeRequests -- organiser', () => {
  it('loads the change history and shows each change as current -> requested', async () => {
    const wrapper = await mountAs('organiser', { changes: [pending] })

    expect(apiGet).toHaveBeenCalledWith('/events/session-1/change-requests')
    const row = wrapper.find('.diff tbody tr')
    expect(row.text()).toContain('Room layout')
    expect(row.text()).toContain('Theatre')
    expect(row.text()).toContain('Banquet')
    expect(wrapper.text()).toContain('Awaiting review')
  })

  it('sends only the edited detail, and leaves the event alone', async () => {
    apiPost.mockResolvedValue({ ...pending, requested_changes: { name: 'Community Summit' } })
    const wrapper = await mountAs('organiser')

    await button(wrapper, 'Request a Change').trigger('click')
    await wrapper.find('.request-form input[type="text"]').setValue('Community Summit')
    await wrapper.find('.request-form').trigger('submit')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/events/session-1/change-requests', {
      changes: { name: 'Community Summit' },
      reason: undefined,
    })
    expect(wrapper.emitted('applied')).toBeUndefined()
    expect(wrapper.text()).toContain('Change request sent')
  })

  it('refuses to send a request that changes nothing', async () => {
    const wrapper = await mountAs('organiser')

    await button(wrapper, 'Request a Change').trigger('click')
    await wrapper.find('.request-form').trigger('submit')

    expect(apiPost).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Change at least one detail')
  })

  it('explains instead of offering a second request while one is pending', async () => {
    const wrapper = await mountAs('organiser', { changes: [pending] })

    await button(wrapper, 'Request a Change').trigger('click')

    expect(wrapper.text()).toContain('already has a change waiting for review')
    expect(button(wrapper, 'Send Change Request')).toBeUndefined()
  })

  it('offers no request button once the event is completed', async () => {
    const wrapper = await mountAs('organiser', { event: session({ status: 'completed' }) })
    expect(button(wrapper, 'Request a Change')).toBeUndefined()
  })

  it('never shows the coordinator review buttons', async () => {
    const wrapper = await mountAs('organiser', { changes: [pending] })
    expect(button(wrapper, 'Approve Change')).toBeUndefined()
  })
})

describe('EventChangeRequests -- coordinator', () => {
  it('approves through the change request route and passes the updated event up', async () => {
    const updated = session({ room_layout: 'banquet' })
    apiPost.mockResolvedValue({ change_request: { ...pending, status: 'approved' }, event: updated })
    const wrapper = await mountAs('coordinator', { changes: [pending] })

    await button(wrapper, 'Approve Change').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/events/session-1/change-requests/change-1/approve', {
      acknowledge_impacts: [],
    })
    expect(wrapper.emitted('applied')).toEqual([[updated]])
  })

  it('needs a reason to reject', async () => {
    apiPost.mockResolvedValue({ ...pending, status: 'rejected' })
    const wrapper = await mountAs('coordinator', { changes: [pending] })

    await button(wrapper, 'Reject Change').trigger('click')
    await wrapper.find('.reject-form').trigger('submit')
    expect(apiPost).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('reason for rejecting')

    await wrapper.find('.reject-form textarea').setValue('The venue is booked as theatre.')
    await wrapper.find('.reject-form').trigger('submit')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/events/session-1/change-requests/change-1/reject', {
      reason: 'The venue is booked as theatre.',
    })
    expect(wrapper.emitted('applied')).toBeUndefined()
  })

  it('has no Request a Change button', async () => {
    const wrapper = await mountAs('coordinator')
    expect(button(wrapper, 'Request a Change')).toBeUndefined()
  })
})

describe('EventChangeRequests -- impact on existing arrangements', () => {
  const impacted = {
    ...pending,
    requested_changes: { preferred_end_time: '19:00' },
    previous_values: { preferred_end_time: '17:00:00' },
    impact: [
      { area: 'venue', severity: 'conflict', title: 'Venue booking: Hall A (confirmed)', issues: ['The booking will not move automatically.'] },
      { area: 'technical_support', severity: 'check', title: 'Technical support', issues: ['Let the Technical Support Staff know.'] },
    ],
  }

  it('shows the coordinator each affected arrangement and keeps Approve disabled until acknowledged', async () => {
    apiPost.mockResolvedValue({ change_request: { ...impacted, status: 'approved' }, event: session() })
    const wrapper = await mountAs('coordinator', { changes: [impacted] })

    expect(wrapper.find('.impact').text()).toContain('Venue booking: Hall A (confirmed)')
    expect(wrapper.find('.impact').text()).toContain('The booking will not move automatically.')
    expect(wrapper.find('.impact').text()).toContain('Check manually')
    expect(button(wrapper, 'Approve Change').attributes('disabled')).toBeDefined()

    await wrapper.find('.impact input[type="checkbox"]').setValue(true)
    expect(button(wrapper, 'Approve Change').attributes('disabled')).toBeUndefined()
    await button(wrapper, 'Approve Change').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/events/session-1/change-requests/change-1/approve', {
      acknowledge_impacts: ['venue', 'technical_support'],
    })
  })

  it('reloads the impacts when the backend finds a new one', async () => {
    const error = Object.assign(new Error('This change affects arrangements already made (registration).'), {
      code: 'change_impact_unacknowledged',
    })
    apiPost.mockRejectedValue(error)
    const wrapper = await mountAs('coordinator', { changes: [impacted] })
    await wrapper.find('.impact input[type="checkbox"]').setValue(true)

    await button(wrapper, 'Approve Change').trigger('click')
    await flushPromises()

    expect(apiGet).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('registration')
    expect(wrapper.emitted('applied')).toBeUndefined()
    expect(button(wrapper, 'Approve Change').attributes('disabled')).toBeDefined()
  })

  it('lets the organiser see the impacts but not acknowledge them', async () => {
    const wrapper = await mountAs('organiser', { changes: [impacted] })
    expect(wrapper.find('.impact').text()).toContain('The coordinator will need to review')
    expect(wrapper.find('.impact input[type="checkbox"]').exists()).toBe(false)
  })

  it('needs no acknowledgement for a change without impacts', async () => {
    const wrapper = await mountAs('coordinator', { changes: [pending] })
    expect(wrapper.find('.impact').exists()).toBe(false)
    expect(button(wrapper, 'Approve Change').attributes('disabled')).toBeUndefined()
  })
})

describe('EventChangeRequests -- a current detail that is no longer valid', () => {
  it('flags a start date that has passed as soon as the form opens, and says why Send is disabled', async () => {
    const wrapper = await mountAs('organiser', {
      event: session({ preferred_start_date: '2020-01-01', preferred_end_date: '2020-01-01' }),
    })

    await button(wrapper, 'Request a Change').trigger('click')
    await wrapper.find('.request-form input[type="text"]').setValue('Community Summit')

    expect(wrapper.text()).toContain('Preferred start date must be after today.')
    expect(button(wrapper, 'Send Change Request').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('Fix the highlighted details above')
  })

  it('shows no such hint when the current details are valid', async () => {
    const wrapper = await mountAs('organiser')
    await button(wrapper, 'Request a Change').trigger('click')

    expect(button(wrapper, 'Send Change Request').attributes('disabled')).toBeUndefined()
    expect(wrapper.text()).not.toContain('Fix the highlighted details above')
  })
})

describe('EventChangeRequests -- form layout', () => {
  const second = session({ id: 'session-2', preferred_start_date: '2099-12-01', preferred_end_date: '2099-12-01' })

  async function openWithTwoSessions() {
    apiGet.mockResolvedValue([])
    const wrapper = mount(EventChangeRequests, {
      props: { event: session(), sessions: [session(), second], role: 'organiser' },
    })
    await flushPromises()
    await button(wrapper, 'Request a Change').trigger('click')
    return wrapper
  }

  it('puts the event name, description and purpose before the session picker', async () => {
    const wrapper = await openWithTwoSessions()
    const labels = wrapper.findAll('.request-form > label .field-label').map((label) => label.text())

    expect(labels.slice(0, 4)).toEqual(['Event Name', 'Description', 'Purpose of the Event', 'Session to change'])
  })

  it('keeps an edited name when the organiser switches session', async () => {
    apiPost.mockResolvedValue({})
    const wrapper = await openWithTwoSessions()

    await wrapper.find('.request-form input[type="text"]').setValue('Community Summit')
    await wrapper.find('.request-form select').setValue('session-2')

    expect(wrapper.find('.request-form input[type="text"]').element.value).toBe('Community Summit')
    await wrapper.find('.request-form').trigger('submit')
    await flushPromises()
    expect(apiPost).toHaveBeenCalledWith('/events/session-2/change-requests', {
      changes: { name: 'Community Summit' },
      reason: undefined,
    })
  })
})
