// IS-12 Search Venues by Event Requirements, on the coordinator's Request
// Venue Booking page. The filtering rules themselves are unit-tested in
// lib/venueSearch.test.js; these cover what the page shows (AC3) and that
// criteria can be changed or cleared without re-entering the rest (AC5).
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../lib/api', () => ({ apiGet: vi.fn(), apiPost: vi.fn() }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { eventId: 'event-1' } }), useRouter: () => ({ push: vi.fn() }) }))
vi.mock('../../components/AppNavBar.vue', () => ({ default: { template: '<nav />' } }))

import { apiGet } from '../../lib/api'
import RequestVenueBookingView from './RequestVenueBookingView.vue'

const EVENT = {
  id: 'event-1',
  name: 'Annual Tech Symposium',
  status: 'planning',
  expected_attendance: 80,
  room_layout: 'theatre',
  accessibility_needs: [],
  preferred_start_date: '2099-03-01',
  preferred_end_date: '2099-03-01',
  preferred_start_time: '10:00:00',
  preferred_end_time: '12:00:00',
}

const VENUES = [
  { id: 'v1', name: 'Grand Ballroom', location: 'Main Building, Level 3', capacity: 300, status: 'available',
    supported_layouts: ['theatre', 'banquet'], accessibility_features: ['wheelchair_access'], facilities: ['stage'] },
  { id: 'v2', name: 'Seminar Room', location: 'Annex, Level 1', capacity: 40, status: 'available',
    supported_layouts: ['classroom'], accessibility_features: [], facilities: ['projector_screen'] },
  { id: 'v3', name: 'Riverside Pavilion', location: 'Riverside', capacity: 150, status: 'available',
    supported_layouts: ['theatre'], accessibility_features: [], facilities: [] },
]

async function render() {
  apiGet.mockImplementation(async (path) => (path === '/venues' ? VENUES : EVENT))
  const wrapper = mount(RequestVenueBookingView, { global: { stubs: { RouterLink: RouterLinkStub } } })
  await flushPromises()
  return wrapper
}

const shown = (wrapper) => wrapper.findAll('button.venue-card .venue-name').map((n) => n.text())
const capacity = (wrapper) => wrapper.find('input[type="number"][placeholder="Any"]')
const location = (wrapper) => wrapper.find('input[placeholder="e.g. Level 3"]')

beforeEach(() => {
  apiGet.mockReset()
})

describe('RequestVenueBookingView -- venue search results (IS-12 AC3)', () => {
  it("shows each venue's capacity, location, supported layouts, accessibility features and facilities", async () => {
    const wrapper = await render()
    const card = wrapper.findAll('button.venue-card').find((c) => c.text().includes('Grand Ballroom'))
    const text = card.text()
    expect(text).toContain('Main Building, Level 3')
    expect(text).toContain('capacity 300')
    expect(text).toContain('theatre')
    expect(text).toContain('banquet')
    expect(text).toContain('wheelchair access')
    expect(text).toContain('stage')
  })
})

describe('RequestVenueBookingView -- changing and clearing criteria (IS-12 AC5)', () => {
  it('changing one criterion keeps the others applied', async () => {
    const wrapper = await render()
    await capacity(wrapper).setValue(100)
    await location(wrapper).setValue('Level 3')
    expect(shown(wrapper)).toEqual(['Grand Ballroom'])

    // Change only the location: the capacity of 100 still applies, so the
    // 40-seat Seminar Room stays out without re-entering it.
    await location(wrapper).setValue('River')
    expect(shown(wrapper)).toEqual(['Riverside Pavilion'])
    expect(capacity(wrapper).element.value).toBe('100')
  })

  it('"Clear criteria" removes every criterion and shows every venue again', async () => {
    const wrapper = await render()
    await capacity(wrapper).setValue(100)
    await location(wrapper).setValue('zzz')
    expect(wrapper.text()).toContain('No venues match your search criteria.')

    await wrapper.findAll('button').find((b) => b.text() === 'Clear criteria').trigger('click')
    expect(shown(wrapper).sort()).toEqual(['Grand Ballroom', 'Riverside Pavilion', 'Seminar Room'])
    expect(capacity(wrapper).element.value).toBe('')
    expect(location(wrapper).element.value).toBe('')
  })
})
