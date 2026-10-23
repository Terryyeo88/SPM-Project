import { describe, expect, it, vi } from 'vitest'

// api.js builds the Supabase client on import, which needs the frontend .env
// (absent in CI); these pure helpers never call it.
vi.mock('./api', () => ({ apiDelete: vi.fn(), apiPost: vi.fn() }))

import { apiDelete } from './api'

import {
  changedFields,
  deleteOutcomeMessage,
  emptyVenueForm,
  formatOperatingHours,
  layoutOptions,
  newVenuePayload,
  permanentlyDeleteVenue,
  validateVenueForm,
  venuePayload,
  venueToForm,
} from './venueCatalogue'

const venue = {
  id: 'venue-1',
  name: 'Grand Ballroom',
  location: 'Main Building, Level 3',
  capacity: 300,
  facilities: ['microphone', 'wifi'],
  accessibility_features: ['lift_access'],
  supported_layouts: ['theatre'],
  status: 'available',
  setup_minutes: 30,
  turnaround_minutes: 30,
  operating_hours_start: '07:00:00',
  operating_hours_end: '23:59:00',
}

function validForm(overrides = {}) {
  return {
    ...emptyVenueForm(),
    name: 'Annex',
    location: 'East Campus',
    capacity: '40',
    supported_layouts: ['theatre'],
    ...overrides,
  }
}

describe('venuePayload', () => {
  it('trims text, sends numbers as numbers, and never sends operating hours or status', () => {
    expect(venuePayload(validForm({ name: '  Annex ', setup_minutes: '0' }))).toEqual({
      name: 'Annex',
      location: 'East Campus',
      capacity: 40,
      facilities: [],
      accessibility_features: [],
      supported_layouts: ['theatre'],
      setup_minutes: 0,
      turnaround_minutes: 30,
    })
  })
})

describe('newVenuePayload', () => {
  it('adds a new venue as available', () => {
    expect(newVenuePayload(validForm())).toMatchObject({ name: 'Annex', status: 'available' })
  })
})

describe('venueToForm', () => {
  it('leaves operating hours and status out of the form', () => {
    expect(venueToForm(venue)).not.toHaveProperty('operating_hours_start')
    expect(venueToForm(venue)).not.toHaveProperty('status')
  })

  it('copies the lists so editing the form never changes the venue', () => {
    const form = venueToForm(venue)
    form.facilities.push('projector')
    expect(venue.facilities).toEqual(['microphone', 'wifi'])
  })
})

describe('validateVenueForm (IS-61 AC1/AC2)', () => {
  it('accepts a complete form', () => {
    expect(validateVenueForm(validForm())).toEqual({})
  })

  it('requires a name, location, a capacity of at least 1 and a room layout', () => {
    const errors = validateVenueForm(validForm({ name: ' ', location: '', capacity: '0', supported_layouts: [] }))
    expect(Object.keys(errors).sort()).toEqual(['capacity', 'location', 'name', 'supported_layouts'])
    expect(errors.supported_layouts).toBe('Choose at least one supported room layout.')
  })

  it('refuses a fractional capacity or negative buffer', () => {
    expect(validateVenueForm(validForm({ capacity: '2.5' })).capacity).toBeTruthy()
    expect(validateVenueForm(validForm({ turnaround_minutes: '-1' })).turnaround_minutes).toBeTruthy()
  })

  it('needs setup and turnaround times of at least 5 minutes', () => {
    expect(validateVenueForm(validForm({ setup_minutes: '4' })).setup_minutes).toBe(
      'Setup time must be a whole number of at least 5 minutes.',
    )
    expect(validateVenueForm(validForm({ turnaround_minutes: '' })).turnaround_minutes).toBe(
      'Turnaround time must be a whole number of at least 5 minutes.',
    )
    expect(validateVenueForm(validForm({ setup_minutes: '5', turnaround_minutes: '5' }))).toEqual({})
  })

})

describe('formatOperatingHours', () => {
  it("shows a venue's existing hours, or that it has none", () => {
    expect(formatOperatingHours('07:00:00', '23:59:00')).toBe('07:00 - 23:59 daily')
    expect(formatOperatingHours(null, null)).toBe('No set hours')
  })
})

describe('changedFields (IS-61 AC2)', () => {
  it('is empty when nothing was edited', () => {
    expect(changedFields(venue, venueToForm(venue))).toEqual({})
  })

  it('lists only what changed', () => {
    const form = { ...venueToForm(venue), capacity: '250', facilities: ['wifi'] }
    expect(changedFields(venue, form)).toEqual({ capacity: 250, facilities: ['wifi'] })
  })

  it("never sends status, so a venue in maintenance stays in maintenance", () => {
    const inMaintenance = { ...venue, status: 'maintenance' }
    const form = { ...venueToForm(inMaintenance), capacity: '250' }
    expect(changedFields(inMaintenance, form)).toEqual({ capacity: 250 })
  })
})

describe('layoutOptions', () => {
  it('keeps a layout the venue lists that is no longer offered', () => {
    expect(layoutOptions(['theatre'], ['theatre', 'lecture'])).toEqual([
      { value: 'theatre', label: 'theatre' },
      { value: 'lecture', label: 'lecture (no longer offered)' },
    ])
  })
})

describe('deleteOutcomeMessage (IS-61 AC3/AC4)', () => {
  it('says nobody was affected when no ongoing event had booked it', () => {
    expect(deleteOutcomeMessage({ venue, released_bookings: [], returned_to_planning: [] })).toBe(
      'Grand Ballroom was deleted. No ongoing events had booked it.',
    )
  })

  it('counts released bookings and sessions sent back to planning', () => {
    const message = deleteOutcomeMessage({ venue, released_bookings: [{}, {}], returned_to_planning: ['e-1'] })
    expect(message).toContain('2 bookings for ongoing events were released')
    expect(message).toContain('asked to book another venue')
    expect(message).toContain('1 session went back to planning')
  })
})

describe('permanentlyDeleteVenue', () => {
  it('calls the permanent delete route', async () => {
    apiDelete.mockResolvedValue(null)
    await permanentlyDeleteVenue('venue-1')
    expect(apiDelete).toHaveBeenCalledWith('/venues/venue-1/permanent')
  })
})
