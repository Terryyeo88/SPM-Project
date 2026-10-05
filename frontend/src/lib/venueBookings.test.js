import { describe, expect, it } from 'vitest'
import { BOOKING_TABS, groupBookingsByTab, isBookingTab, validateBookingForm } from './venueBookings'

function booking(overrides) {
  return { id: overrides.name, ...overrides }
}

describe('groupBookingsByTab', () => {
  it('puts each status in the tab of the same name', () => {
    const bookings = [
      booking({ name: 'a', status: 'pending' }),
      booking({ name: 'b', status: 'confirmed' }),
      booking({ name: 'c', status: 'rejected' }),
    ]
    const groups = groupBookingsByTab(bookings)
    const names = (key) => groups[key].map((b) => b.name)
    expect(names('pending')).toEqual(['a'])
    expect(names('confirmed')).toEqual(['b'])
    expect(names('rejected')).toEqual(['c'])
  })

  it('returns every tab key, empty, for no bookings', () => {
    const keys = BOOKING_TABS.map((t) => t.key)
    expect(Object.keys(groupBookingsByTab(undefined))).toEqual(keys)
    expect(Object.values(groupBookingsByTab([])).flat()).toEqual([])
  })

  it('maps every status to at most one tab', () => {
    const all = BOOKING_TABS.flatMap((t) => t.statuses)
    expect(new Set(all).size).toBe(all.length)
  })

  it('ignores a booking with an unrecognised status rather than throwing', () => {
    expect(() => groupBookingsByTab([booking({ name: 'x', status: 'archived' })])).not.toThrow()
    expect(Object.values(groupBookingsByTab([booking({ name: 'x', status: 'archived' })])).flat()).toEqual([])
  })
})

describe('isBookingTab', () => {
  it('accepts a real tab key', () => {
    expect(isBookingTab('pending')).toBe(true)
  })

  it('rejects an unknown key, including undefined', () => {
    expect(isBookingTab('nonsense')).toBe(false)
    expect(isBookingTab(undefined)).toBe(false)
  })
})

describe('validateBookingForm', () => {
  it('passes when venue_id is set', () => {
    expect(validateBookingForm({ venue_id: 'venue-1' })).toBe(true)
  })

  it('fails when venue_id is missing, blank, or the form itself is missing', () => {
    expect(validateBookingForm({ venue_id: '' })).toBe(false)
    expect(validateBookingForm({})).toBe(false)
    expect(validateBookingForm(undefined)).toBe(false)
  })
})
