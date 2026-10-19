import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../lib/api', () => ({ apiGet: vi.fn(), apiPost: vi.fn() }))

import { apiGet, apiPost } from '../lib/api'
import VenueBookingStatus from './VenueBookingStatus.vue'

const hall = { id: 'booking-hall', status: 'confirmed', venues: { name: 'Main Hall' } }
const room = { id: 'booking-room', status: 'pending', venues: { name: 'Breakout Room' } }
const old = { id: 'booking-old', status: 'rejected', venues: { name: 'Old Hall' }, rejection: { reason: 'Closed for repairs.' } }

// Braces: a function returned from beforeEach is run as teardown.
beforeEach(() => {
  apiGet.mockReset()
  apiPost.mockReset()
})

async function render(bookings, status = 'planning') {
  apiGet.mockResolvedValue(bookings)
  const wrapper = mount(VenueBookingStatus, {
    props: { event: { id: 'session-1', status } },
    global: { stubs: { RouterLink: RouterLinkStub } },
  })
  await flushPromises()
  return wrapper
}

function row(wrapper, id) {
  return wrapper.find(`[data-booking="${id}"]`)
}

function buttonIn(element, text) {
  return element.findAll('button').find((b) => b.text() === text)
}

async function cancelWithReason(wrapper, id, reason) {
  await buttonIn(row(wrapper, id), 'Cancel booking').trigger('click')
  if (reason !== undefined) await row(wrapper, id).find('textarea').setValue(reason)
  await row(wrapper, id).find('form').trigger('submit')
  await flushPromises()
}

describe('VenueBookingStatus', () => {
  it("lists every one of the session's venue bookings, not just the latest", async () => {
    const wrapper = await render([room, hall, old])

    expect(apiGet).toHaveBeenCalledWith('/events/session-1/venue-bookings')
    expect(wrapper.findAll('li.booking')).toHaveLength(3)
    expect(wrapper.text()).toContain('Main Hall')
    expect(wrapper.text()).toContain('Breakout Room')
    expect(wrapper.text()).toContain('Reason: Closed for repairs.')
  })

  it('says so when no venue has been requested', async () => {
    const wrapper = await render([])
    expect(wrapper.text()).toContain('No venue has been requested for this session yet.')
    expect(wrapper.findComponent(RouterLinkStub).text()).toBe('Request Venue Booking')
  })

  function requestLinks(wrapper) {
    return wrapper.findAllComponents(RouterLinkStub).map((link) => link.text()).filter((text) => text.startsWith('Request'))
  }

  it.each([
    ['confirmed', [hall]],
    ['pending', [room]],
    ['confirmed alongside rejected', [hall, old]],
  ])('offers no venue request while a booking is %s', async (_, bookings) => {
    const wrapper = await render(bookings)
    expect(requestLinks(wrapper)).toEqual([])
  })

  it('offers a different venue once every booking is rejected or cancelled', async () => {
    const wrapper = await render([old, { ...hall, status: 'cancelled' }])
    expect(requestLinks(wrapper)).toEqual(['Request a different venue'])
  })

  it('offers the request again after the only booked venue is cancelled', async () => {
    apiPost.mockResolvedValueOnce({ ...hall, status: 'cancelled' })
    const wrapper = await render([hall])
    expect(requestLinks(wrapper)).toEqual([])

    await cancelWithReason(wrapper, 'booking-hall', 'Venue closed.')

    expect(requestLinks(wrapper)).toEqual(['Request a different venue'])
  })

  it('offers no venue request outside planning', async () => {
    const wrapper = await render([], 'approved')
    expect(requestLinks(wrapper)).toEqual([])
  })

  it('offers to cancel only pending and confirmed bookings', async () => {
    const wrapper = await render([room, hall, old])
    expect(buttonIn(row(wrapper, 'booking-hall'), 'Cancel booking')).toBeDefined()
    expect(buttonIn(row(wrapper, 'booking-room'), 'Cancel booking')).toBeDefined()
    expect(buttonIn(row(wrapper, 'booking-old'), 'Cancel booking')).toBeUndefined()
  })

  it('offers no cancel once the event is completed', async () => {
    const wrapper = await render([hall], 'completed')
    expect(buttonIn(row(wrapper, 'booking-hall'), 'Cancel booking')).toBeUndefined()
  })

  it('asks for a reason before cancelling', async () => {
    const wrapper = await render([hall, room])

    await cancelWithReason(wrapper, 'booking-hall')

    expect(apiPost).not.toHaveBeenCalled()
    expect(row(wrapper, 'booking-hall').find('[role="alert"]').text()).toContain('reason')
  })

  it('cancels one booking and leaves the others exactly as they were', async () => {
    apiPost.mockResolvedValueOnce({ ...hall, status: 'cancelled' })
    const wrapper = await render([hall, room])

    await cancelWithReason(wrapper, 'booking-hall', 'Moved to the auditorium.')

    expect(apiPost).toHaveBeenCalledTimes(1)
    expect(apiPost).toHaveBeenCalledWith('/venues/bookings/booking-hall/cancel', { reason: 'Moved to the auditorium.' })
    expect(row(wrapper, 'booking-hall').find('.status').text()).toBe('Cancelled')
    expect(row(wrapper, 'booking-room').find('.status').text()).toBe('Pending')
    expect(buttonIn(row(wrapper, 'booking-room'), 'Cancel booking')).toBeDefined()
    expect(wrapper.find('[role="status"]').text()).toContain('other venue bookings for this session are unchanged')
  })

  it('shows why a booking was cancelled', async () => {
    const wrapper = await render([{ ...hall, status: 'cancelled', cancellation: { reason: 'Moved.' } }])
    expect(row(wrapper, 'booking-hall').text()).toContain('Cancelled: Moved.')
  })

  it('keeps the form open with the error if the cancel is refused', async () => {
    apiPost.mockRejectedValueOnce(new Error('This booking is already rejected, so it cannot be cancelled.'))
    const wrapper = await render([hall])

    await cancelWithReason(wrapper, 'booking-hall', 'x')

    expect(row(wrapper, 'booking-hall').find('form').exists()).toBe(true)
    expect(row(wrapper, 'booking-hall').find('[role="alert"]').text()).toContain('already rejected')
    expect(row(wrapper, 'booking-hall').find('.status').text()).toBe('Confirmed')
  })
})
