import { describe, expect, it } from 'vitest'
import {
  BOOKING_TABS,
  canCancelBooking,
  groupBookingsByTab,
  isBookingTab,
  unreplacedVenueReleases,
  validateBookingForm,
} from './venueBookings'

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

describe('unreplacedVenueReleases (IS-61 AC4)', () => {
  const released = {
    id: 'released',
    status: 'cancelled',
    released_by_venue_deletion: true,
    created_at: '2026-10-01T09:00:00+00:00',
    updated_at: '2026-10-20T09:00:00+00:00',
  }

  it('lists a booking released because its venue was deleted', () => {
    expect(unreplacedVenueReleases([released], { status: 'planning' })).toEqual([released])
  })

  it('ignores a booking the coordinator cancelled themselves', () => {
    const own = { ...released, released_by_venue_deletion: false }
    expect(unreplacedVenueReleases([own], { status: 'planning' })).toEqual([])
  })

  it('stops once a booking is made after the release', () => {
    const rebooked = { id: 'new', status: 'pending', created_at: '2026-10-21T09:00:00+00:00' }
    expect(unreplacedVenueReleases([rebooked, released], { status: 'planning' })).toEqual([])
  })

  it('still lists it when the only other booking predates the release', () => {
    const older = { id: 'older', status: 'confirmed', created_at: '2026-10-02T09:00:00+00:00' }
    expect(unreplacedVenueReleases([older, released], { status: 'planning' })).toEqual([released])
  })

  it('uses released_at, which a later permanent delete does not move, over updated_at', () => {
    const rebooked = { id: 'new', status: 'pending', created_at: '2026-10-21T09:00:00+00:00' }
    // The permanent delete rewrote updated_at to after the rebooking.
    const releasedThenVenueRemoved = {
      ...released,
      released_at: '2026-10-20T09:00:00+00:00',
      updated_at: '2026-10-22T09:00:00+00:00',
    }
    expect(unreplacedVenueReleases([rebooked, releasedThenVenueRemoved], { status: 'planning' })).toEqual([])
  })

  it('treats a response that is not a list as no bookings', () => {
    expect(unreplacedVenueReleases(undefined, { status: 'planning' })).toEqual([])
    expect(unreplacedVenueReleases({ id: 'not-a-list' }, { status: 'planning' })).toEqual([])
  })

  it('lists nothing for a completed or cancelled event', () => {
    expect(unreplacedVenueReleases([released], { status: 'completed' })).toEqual([])
    expect(unreplacedVenueReleases([released], { status: 'cancelled' })).toEqual([])
  })
})
