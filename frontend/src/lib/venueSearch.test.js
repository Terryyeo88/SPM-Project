import { describe, expect, it } from 'vitest'
import { filterVenues, hasActiveCriteria } from './venueSearch'

const VENUES = [
  {
    id: 'v1',
    name: 'Grand Ballroom',
    location: 'Main Building, Level 3',
    capacity: 300,
    supported_layouts: ['theatre', 'banquet'],
    accessibility_features: ['wheelchair_access', 'lift_access'],
    facilities: ['microphone', 'projector'],
  },
  {
    id: 'v2',
    name: 'Innovation Hub',
    location: 'Tech Wing, Level 1',
    capacity: 80,
    supported_layouts: ['classroom', 'boardroom'],
    accessibility_features: ['wheelchair_access'],
    facilities: ['projector', 'wifi'],
  },
]

describe('filterVenues', () => {
  it('returns every venue when no criteria are set', () => {
    expect(filterVenues(VENUES, {})).toHaveLength(2)
  })

  it('filters by minimum capacity', () => {
    const result = filterVenues(VENUES, { minCapacity: 100 })
    expect(result.map((v) => v.id)).toEqual(['v1'])
  })

  it('filters by location, case-insensitively and by substring', () => {
    const result = filterVenues(VENUES, { location: 'tech wing' })
    expect(result.map((v) => v.id)).toEqual(['v2'])
  })

  it('filters by supported room layout', () => {
    const result = filterVenues(VENUES, { roomLayout: 'boardroom' })
    expect(result.map((v) => v.id)).toEqual(['v2'])
  })

  it('filters by accessibility features, requiring every one selected', () => {
    const result = filterVenues(VENUES, { accessibilityFeatures: ['wheelchair_access', 'lift_access'] })
    expect(result.map((v) => v.id)).toEqual(['v1'])
  })

  it('filters by facilities, requiring every one selected', () => {
    const result = filterVenues(VENUES, { facilities: ['projector', 'wifi'] })
    expect(result.map((v) => v.id)).toEqual(['v2'])
  })

  it('applies multiple criteria together (AND, not OR)', () => {
    // v1 has the capacity but not the layout; v2 has the layout but not
    // the capacity -- neither alone satisfies both, so AND (not OR)
    // must return nothing.
    const result = filterVenues(VENUES, { minCapacity: 200, roomLayout: 'classroom' })
    expect(result).toEqual([])
  })

  it('returns an explicit empty array, not an error, when nothing matches', () => {
    expect(filterVenues(VENUES, { minCapacity: 10000 })).toEqual([])
  })

  it('tolerates a missing venues array', () => {
    expect(filterVenues(undefined, { minCapacity: 10 })).toEqual([])
  })
})

describe('hasActiveCriteria', () => {
  it('is false for an empty or default criteria object', () => {
    expect(hasActiveCriteria({})).toBe(false)
    expect(hasActiveCriteria({ location: '  ', accessibilityFeatures: [] })).toBe(false)
  })

  it('is true when any single criterion is set', () => {
    expect(hasActiveCriteria({ minCapacity: 50 })).toBe(true)
    expect(hasActiveCriteria({ location: 'wing' })).toBe(true)
    expect(hasActiveCriteria({ roomLayout: 'theatre' })).toBe(true)
    expect(hasActiveCriteria({ accessibilityFeatures: ['wifi'] })).toBe(true)
    expect(hasActiveCriteria({ facilities: ['wifi'] })).toBe(true)
  })
})
