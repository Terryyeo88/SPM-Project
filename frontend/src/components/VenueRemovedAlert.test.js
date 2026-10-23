import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../lib/api', () => ({ apiGet: vi.fn() }))

import { apiGet } from '../lib/api'
import VenueRemovedAlert from './VenueRemovedAlert.vue'

const released = {
  id: 'booking-1',
  status: 'cancelled',
  released_by_venue_deletion: true,
  venues: { name: 'Grand Ballroom' },
  created_at: '2026-10-01T09:00:00+00:00',
  updated_at: '2026-10-20T09:00:00+00:00',
}

// Braces: a function returned from beforeEach is run as teardown.
beforeEach(() => {
  apiGet.mockReset()
})

async function render(bookings, status = 'planning') {
  apiGet.mockResolvedValue(bookings)
  const wrapper = mount(VenueRemovedAlert, {
    props: { event: { id: 'session-1', status } },
    global: { stubs: { RouterLink: RouterLinkStub } },
  })
  await flushPromises()
  return wrapper
}

describe('VenueRemovedAlert (IS-61 AC4)', () => {
  it("alerts the coordinator to book another venue when the session's venue was deleted", async () => {
    const wrapper = await render([released])

    expect(apiGet).toHaveBeenCalledWith('/events/session-1/venue-bookings')
    const alert = wrapper.find('[data-test="venue-removed-alert"]')
    expect(alert.attributes('role')).toBe('alert')
    expect(alert.text()).toContain('Book another venue')
    expect(alert.text()).toContain('Grand Ballroom was deleted from the venue catalogue')
    const link = wrapper.findComponent(RouterLinkStub)
    expect(link.props('to')).toEqual({ name: 'request-venue-booking', params: { eventId: 'session-1' } })
  })

  it('shows nothing when no booking was released by a venue deletion', async () => {
    const wrapper = await render([{ ...released, released_by_venue_deletion: false }])
    expect(wrapper.find('[data-test="venue-removed-alert"]').exists()).toBe(false)
  })

  it('goes away once the coordinator has booked another venue', async () => {
    const rebooked = { id: 'booking-2', status: 'pending', created_at: '2026-10-21T09:00:00+00:00' }
    const wrapper = await render([rebooked, released])
    expect(wrapper.find('[data-test="venue-removed-alert"]').exists()).toBe(false)
  })

  it('explains the wait instead of linking when the session is not in planning', async () => {
    const wrapper = await render([released], 'safety_review')
    expect(wrapper.find('[data-test="venue-removed-alert"]').text()).toContain('Once this session is back in planning')
    expect(wrapper.findComponent(RouterLinkStub).exists()).toBe(false)
  })

  it('stays quiet if the bookings cannot be loaded', async () => {
    apiGet.mockRejectedValue(new Error('offline'))
    const wrapper = mount(VenueRemovedAlert, {
      props: { event: { id: 'session-1', status: 'planning' } },
      global: { stubs: { RouterLink: RouterLinkStub } },
    })
    await flushPromises()
    expect(wrapper.html()).not.toContain('Book another venue')
  })
})
