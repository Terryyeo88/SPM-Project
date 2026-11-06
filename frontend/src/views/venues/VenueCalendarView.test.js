// IS-74: the venue calendar at the real edges of a Singapore day, where a
// booking's stored UTC date differs from its local one. The timezone is pinned
// to UTC+8 below, so these mean the same on a UTC CI runner as on a laptop in
// Singapore.
//
// `apiGet` stands in for the backend's window, so a wrong query really does lose
// the booking: rows overlapping start..end as whole Singapore days come back.
// That window is proven on the real code by
// backend/tests/test_calendar_singapore_window.py, with these same instants.
import { flushPromises, mount } from '@vue/test-utils'
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'

const apiGet = vi.fn()
vi.mock('../../lib/api', () => ({ apiGet: (...args) => apiGet(...args) }))
// AppNavBar pulls in the auth store and so the Supabase client, which needs
// real env vars at import time -- irrelevant to this screen, so replaced.
vi.mock('../../components/AppNavBar.vue', () => ({ default: { template: '<div />' } }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { venueId: 'venue-1' } }) }))

import VenueCalendarView from './VenueCalendarView.vue'

const VENUE = { id: 'venue-1', name: 'Grand Ballroom', operating_hours_start: null, operating_hours_end: null }

// Stored as PostgREST returns them: in UTC.
const booking = (event_name, startUtc, endUtc) => ({
  type: 'booking',
  state: 'confirmed',
  start: `${startUtc}:00+00:00`,
  end: `${endUtc}:00+00:00`,
  event_id: event_name,
  event_name,
})
const LAST_OF_OCTOBER_2300 = booking('31 Oct 23:00', '2026-10-31T15:00', '2026-10-31T15:30')
const FIRST_OF_NOVEMBER_0030 = booking('1 Nov 00:30', '2026-10-31T16:30', '2026-10-31T17:30')
const FIRST_OF_NOVEMBER_2300 = booking('1 Nov 23:00', '2026-11-01T15:00', '2026-11-01T15:30')
const SECOND_OF_NOVEMBER_0030 = booking('2 Nov 00:30', '2026-11-01T16:30', '2026-11-01T17:30')
const LAST_OF_NOVEMBER_2300 = booking('30 Nov 23:00', '2026-11-30T15:00', '2026-11-30T15:30')
const ALL = [
  LAST_OF_OCTOBER_2300,
  FIRST_OF_NOVEMBER_0030,
  FIRST_OF_NOVEMBER_2300,
  SECOND_OF_NOVEMBER_0030,
  LAST_OF_NOVEMBER_2300,
]

function backendWindow(path) {
  const query = new URLSearchParams(path.split('?')[1])
  const from = new Date(`${query.get('start')}T00:00:00+08:00`).getTime()
  const to = new Date(`${query.get('end')}T00:00:00+08:00`).getTime() + 86400000
  return {
    venue: VENUE,
    range: { start: query.get('start'), end: query.get('end') },
    entries: ALL.filter((row) => new Date(row.start).getTime() < to && from < new Date(row.end).getTime()),
  }
}

function queryOf(call) {
  return call[0].split('?')[1]
}

async function mountView() {
  const wrapper = mount(VenueCalendarView, {
    global: { stubs: { 'router-link': { template: '<a><slot /></a>' } } },
  })
  await flushPromises()
  return wrapper
}

function cellDaysWith(wrapper, eventName) {
  return wrapper
    .findAll('.day-cell')
    .filter((cell) => cell.text().includes(eventName))
    .map((cell) => cell.find('.day-number').text())
}

async function openDayView(wrapper) {
  await wrapper.findAll('.tab').find((tab) => tab.text() === 'day').trigger('click')
  await flushPromises()
}

const listed = (wrapper) => wrapper.findAll('.list-main').map((row) => row.text())

describe('VenueCalendarView at UTC+8 day boundaries (IS-74)', () => {
  const originalTz = process.env.TZ

  beforeAll(() => {
    process.env.TZ = 'Asia/Singapore'
  })

  afterAll(() => {
    if (originalTz === undefined) delete process.env.TZ
    else process.env.TZ = originalTz
  })

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-01T10:00:00+08:00'))
    apiGet.mockReset()
    apiGet.mockImplementation(async (path) => backendWindow(path))
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('really is running in UTC+8', () => {
    // Guards every test below: if the pin stopped working they would be
    // testing the host's timezone instead.
    expect(new Date(2026, 10, 1).getTimezoneOffset()).toBe(-480)
    expect(new Date(2026, 10, 1).toISOString()).toBe('2026-10-31T16:00:00.000Z')
  })

  it('asks for exactly the local month', async () => {
    await mountView()
    expect(queryOf(apiGet.mock.calls[0])).toBe('start=2026-11-01&end=2026-11-30')
  })

  it('shows a 23:00 booking on the last day of the month, on that day', async () => {
    const wrapper = await mountView()
    expect(cellDaysWith(wrapper, '30 Nov 23:00')).toEqual(['30'])
  })

  it('shows a 00:30 booking on the first day of the month, on that day', async () => {
    const wrapper = await mountView()
    expect(cellDaysWith(wrapper, '1 Nov 00:30')).toEqual(['1'])
  })

  it('does not show that 00:30 booking in the previous month', async () => {
    const wrapper = await mountView()
    await wrapper.find('[aria-label="Previous"]').trigger('click')
    await flushPromises()

    expect(queryOf(apiGet.mock.lastCall)).toBe('start=2026-10-01&end=2026-10-31')
    expect(cellDaysWith(wrapper, '1 Nov 00:30')).toEqual([])
    expect(cellDaysWith(wrapper, '31 Oct 23:00')).toEqual(['31'])
  })

  it("day view shows that day's entries only, nothing from either side", async () => {
    const wrapper = await mountView()
    await openDayView(wrapper)

    expect(queryOf(apiGet.mock.lastCall)).toBe('start=2026-11-01&end=2026-11-01')
    expect(listed(wrapper)).toEqual(['1 Nov 00:30', '1 Nov 23:00'])
  })

  it('stepping the day view back shows the previous day only', async () => {
    const wrapper = await mountView()
    await openDayView(wrapper)
    await wrapper.find('[aria-label="Previous"]').trigger('click')
    await flushPromises()

    expect(queryOf(apiGet.mock.lastCall)).toBe('start=2026-10-31&end=2026-10-31')
    expect(listed(wrapper)).toEqual(['31 Oct 23:00'])
  })
})

describe('VenueCalendarView operating hours (IS-11 AC5)', () => {
  const originalTz = process.env.TZ
  const HOURS = { ...VENUE, operating_hours_start: '08:00:00', operating_hours_end: '20:00:00' }
  // 1 Nov 09:00-10:00 Singapore time, stored in UTC.
  const MORNING = booking('Morning talk', '2026-11-01T01:00', '2026-11-01T02:00')

  beforeAll(() => {
    process.env.TZ = 'Asia/Singapore'
  })

  afterAll(() => {
    if (originalTz === undefined) delete process.env.TZ
    else process.env.TZ = originalTz
  })

  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['Date'] })
    vi.setSystemTime(new Date('2026-11-01T10:00:00+08:00'))
    apiGet.mockReset()
    apiGet.mockResolvedValue({ venue: HOURS, range: {}, entries: [MORNING] })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('day view lists the closed periods around the bookings, in time order', async () => {
    const wrapper = await mountView()
    await openDayView(wrapper)

    expect(wrapper.findAll('.list-main').map((row) => row.text())).toEqual([
      'Closed until 08:00',
      'Morning talk',
      'Closed from 20:00',
    ])
    expect(wrapper.text()).toContain('Outside operating hours')
  })

  it('the month grid marks every day as closed outside the hours', async () => {
    const wrapper = await mountView()

    expect(cellDaysWith(wrapper, 'Open 08:00–20:00 only')).toHaveLength(30)
    expect(wrapper.find('.hours-note').text()).toContain('08:00 - 20:00 daily')
  })

  it('marks nothing for a venue with no set hours', async () => {
    apiGet.mockResolvedValue({ venue: VENUE, range: {}, entries: [MORNING] })
    const wrapper = await mountView()
    await openDayView(wrapper)

    expect(wrapper.findAll('.list-main').map((row) => row.text())).toEqual(['Morning talk'])
    expect(wrapper.find('.hours-note').exists()).toBe(false)
  })
})
