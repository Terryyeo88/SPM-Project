import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const apiGet = vi.fn()
vi.mock('../../lib/api', () => ({ apiGet: (...args) => apiGet(...args) }))
// AppNavBar pulls in the auth store and so the Supabase client, which needs
// real env vars at import time -- irrelevant to this screen, so replaced.
vi.mock('../../components/AppNavBar.vue', () => ({ default: { template: '<div />' } }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { equipmentId: 'unit-1' } }) }))

import EquipmentCalendarView from './EquipmentCalendarView.vue'
import { rangeFor, rangeQuery, widenRange } from '../../lib/calendar'

// What the view should ask for when showing the month containing `day`:
// the month widened by a day each side (see widenRange for why).
const queryFor = (day) => `/equipment/unit-1/calendar?${rangeQuery(widenRange(rangeFor('month', day)))}`

// Local-time instants, like the calendar itself (it groups by the browser's day).
const at = (month, d, h) => new Date(2026, month - 1, d, h).toISOString()

const CALENDAR = {
  equipment: { id: 'unit-1', asset_tag: 'PRJ-001', type: 'projector', notes: 'HDMI and USB-C', status: 'maintenance' },
  range: { start: '2026-11-01', end: '2026-11-30' },
  entries: [
    { type: 'reservation', state: 'reserved', start: at(11, 9, 18), end: at(11, 11, 12), event_id: 'e1', event_name: 'Annual Tech Symposium' },
    { type: 'reservation', state: 'reserved', start: at(11, 15, 13), end: at(11, 15, 17), event_id: 'e2', event_name: null },
  ],
}

function mountView() {
  return mount(EquipmentCalendarView, {
    global: { stubs: { 'router-link': { props: ['to'], template: '<a class="router-link"><slot /></a>' } } },
  })
}

describe('EquipmentCalendarView', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date(2026, 10, 16, 10))
    apiGet.mockReset()
    apiGet.mockResolvedValue(CALENDAR)
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it("asks for the current month's calendar for this unit", async () => {
    mountView()
    await flushPromises()

    expect(apiGet).toHaveBeenCalledWith(queryFor(new Date(2026, 10, 1)))
  })

  it('shows the asset tag, type, status pill and the profile (AC2)', async () => {
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('.title').text()).toBe('PRJ-001')
    expect(wrapper.find('.subtitle').text()).toBe('projector')
    expect(wrapper.find('.status').text()).toBe('Under maintenance')
    expect(wrapper.find('.status').classes()).toContain('status-maintenance')
    const profile = wrapper.find('.details').text()
    expect(profile).toContain('PRJ-001')
    expect(profile).toContain('HDMI and USB-C')
  })

  it('marks every day of a multi-day reservation with the event name (AC4, AC5)', async () => {
    const wrapper = mountView()
    await flushPromises()

    const marked = wrapper
      .findAll('.day-cell')
      .filter((cell) => cell.text().includes('Annual Tech Symposium'))
      .map((cell) => cell.find('.day-number').text())
    expect(marked).toEqual(['9', '10', '11'])
  })

  it('labels a reservation with no event name "Reserved"', async () => {
    const wrapper = mountView()
    await flushPromises()

    const day15 = wrapper.findAll('.day-cell').find((cell) => cell.find('.day-number').exists() && cell.find('.day-number').text() === '15')
    expect(day15.find('.entry-pill').text()).toBe('Reserved')
  })

  it('shows one month, and previous/next fetch the neighbouring months (AC3)', async () => {
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.find('.range-label').text()).toBe(new Date(2026, 10, 1).toLocaleDateString(undefined, { month: 'long', year: 'numeric' }))
    expect(wrapper.findAll('.tab')).toHaveLength(0)

    await wrapper.find('[aria-label="Next month"]').trigger('click')
    await flushPromises()
    expect(apiGet).toHaveBeenLastCalledWith(queryFor(new Date(2026, 11, 1)))

    await wrapper.find('[aria-label="Previous month"]').trigger('click')
    await wrapper.find('[aria-label="Previous month"]').trigger('click')
    await flushPromises()
    expect(apiGet).toHaveBeenLastCalledWith(queryFor(new Date(2026, 9, 1)))
  })

  it('asks for a range that covers the whole local month, last day included', async () => {
    mountView()
    await flushPromises()
    const query = new URLSearchParams(apiGet.mock.calls[0][0].split('?')[1])
    // The backend compares UTC wall-clock times against these whole days.
    // Local November runs from 2026-10-31T16:00Z to 2026-11-30T16:00Z.
    expect(query.get('start') <= new Date(2026, 10, 1).toISOString().slice(0, 10)).toBe(true)
    expect(query.get('end') >= new Date(2026, 11, 1).toISOString().slice(0, 10)).toBe(true)
  })

  it('a reservation on the last day of the month is marked (AC4)', async () => {
    apiGet.mockResolvedValue({
      ...CALENDAR,
      entries: [{ type: 'reservation', state: 'reserved', start: at(11, 30, 10), end: at(11, 30, 12), event_id: 'e3', event_name: 'Month End Review' }],
    })
    const wrapper = mountView()
    await flushPromises()

    const marked = wrapper.findAll('.day-cell').filter((cell) => cell.text().includes('Month End Review'))
    expect(marked.map((cell) => cell.find('.day-number').text())).toEqual(['30'])
  })

  it('shows the error when the unit cannot be loaded (e.g. a 404)', async () => {
    apiGet.mockRejectedValue(new Error('Resource not found.'))
    const wrapper = mountView()
    await flushPromises()

    expect(wrapper.find('[role="alert"]').text()).toContain('Resource not found.')
    expect(wrapper.find('.month-grid').exists()).toBe(false)
  })
})
