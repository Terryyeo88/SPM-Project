import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../lib/api', () => ({ apiGet: vi.fn(), apiPost: vi.fn() }))
vi.mock('../../stores/auth', () => ({ useAuthStore: () => ({ roles: ['venue_staff'] }) }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { bookingId: 'booking-1' } }) }))
vi.mock('../../components/AppNavBar.vue', () => ({ default: { template: '<nav />' } }))

import { apiGet, apiPost } from '../../lib/api'
import VenueBookingReviewView from './VenueBookingReviewView.vue'

const booking = {
  id: 'booking-1',
  event_id: 'session-1',
  venue_id: 'venue-1',
  status: 'pending',
  conflict: false,
  booking_start: '2026-11-10T08:30:00+08:00',
  booking_end: '2026-11-10T17:30:00+08:00',
  // GET /venues/bookings/<id> embeds the session's details: Venue Staff
  // can't open GET /events/<id> themselves.
  event: {
    id: 'session-1',
    name: 'Annual Tech Symposium',
    description: 'A symposium.',
    purpose: 'Learning.',
    preferred_start_date: '2026-11-10',
    preferred_start_time: '09:00:00',
    preferred_end_time: '17:00:00',
    expected_attendance: 150,
    room_layout: 'theatre',
    accessibility_needs: [],
  },
}
const venue = { id: 'venue-1', name: 'Grand Ballroom', capacity: 100, supported_layouts: ['theatre'], accessibility_features: [] }

beforeEach(() => {
  apiGet.mockReset()
  apiPost.mockReset()
  apiGet.mockImplementation((path) => Promise.resolve(path.startsWith('/venues/bookings/') ? booking : venue))
})

async function render() {
  const wrapper = mount(VenueBookingReviewView, { global: { stubs: { RouterLink: RouterLinkStub } } })
  await flushPromises()
  return wrapper
}

describe('VenueBookingReviewView (Venue Staff)', () => {
  it('never asks for the event itself, which Venue Staff may not open', async () => {
    await render()
    expect(apiGet).toHaveBeenCalledWith('/venues/bookings/booking-1')
    expect(apiGet).toHaveBeenCalledWith('/venues/venue-1')
    expect(apiGet.mock.calls.map(([path]) => path).some((path) => path.startsWith('/events/'))).toBe(false)
  })

  it('shows the event details embedded in the booking', async () => {
    const wrapper = await render()
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.find('h1').text()).toBe('Annual Tech Symposium')
    expect(wrapper.text()).toContain('A symposium.')
    expect(wrapper.text()).toContain('Learning.')
  })

  it('checks suitability against the embedded event details', async () => {
    const wrapper = await render()
    expect(wrapper.text()).toContain('Venue holds only 100, but the event expects 150.')
  })

  it('keeps the event details after a decision returns the bare booking row', async () => {
    const { event, ...bare } = booking
    apiPost.mockResolvedValueOnce({ ...bare, status: 'confirmed' })
    const wrapper = await render()

    await wrapper.findAll('button').find((b) => b.text().includes('Approve')).trigger('click')
    await flushPromises()

    expect(wrapper.find('h1').text()).toBe('Annual Tech Symposium')
  })
})

describe('VenueBookingReviewView -- IS-61: a permanently deleted venue', () => {
  it("shows the venue's kept name and doesn't try to load the venue", async () => {
    const gone = { ...booking, venue_id: null, venue_name: 'Old Hall', status: 'confirmed' }
    apiGet.mockImplementation((path) => Promise.resolve(path.startsWith('/venues/bookings/') ? gone : venue))

    const wrapper = await render()

    expect(apiGet).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Old Hall (permanently deleted)')
  })
})
