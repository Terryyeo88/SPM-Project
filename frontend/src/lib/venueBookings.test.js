import { describe, expect, it } from 'vitest'
import { BOOKING_TABS, canCancelBooking, groupBookingsByTab, isBookingTab, validateBookingForm } from './venueBookings'

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

describe('cancelled bookings (IS-9)', () => {
  it('have a tab of their own', () => {
    expect(isBookingTab('cancelled')).toBe(true)
    expect(groupBookingsByTab([booking({ name: 'x', status: 'cancelled' })]).cancelled.map((b) => b.name)).toEqual(['x'])
  })
})

describe('canCancelBooking (IS-9)', () => {
  it.each(['pending', 'confirmed'])('allows cancelling a %s booking while the event is open', (status) => {
    expect(canCancelBooking({ status }, { status: 'planning' })).toBe(true)
  })

  it.each(['rejected', 'cancelled'])('does not offer to cancel a %s booking', (status) => {
    expect(canCancelBooking({ status }, { status: 'planning' })).toBe(false)
  })

  it.each(['completed', 'cancelled'])('does not offer to cancel once the event is %s', (status) => {
    expect(canCancelBooking({ status: 'confirmed' }, { status })).toBe(false)
  })
})
