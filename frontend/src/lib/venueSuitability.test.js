import { describe, expect, it } from 'vitest'
import { checkSuitability, checkSuitabilityForEvent, isSuitableOverall } from './venueSuitability'

function byLabel(checks, label) {
  return checks.find((c) => c.label === label)
}

describe('checkSuitability', () => {
  it('passes capacity when the venue holds at least as many as expected', () => {
    const checks = checkSuitability({ expected_attendance: 100 }, { capacity: 150 })
    expect(byLabel(checks, 'Capacity').ok).toBe(true)
  })

  it('fails capacity when the venue holds fewer than expected', () => {
    const checks = checkSuitability({ expected_attendance: 200 }, { capacity: 150 })
    expect(byLabel(checks, 'Capacity').ok).toBe(false)
    expect(byLabel(checks, 'Capacity').detail).toContain('150')
  })

  it('treats an exact match as passing (boundary)', () => {
    const checks = checkSuitability({ expected_attendance: 150 }, { capacity: 150 })
    expect(byLabel(checks, 'Capacity').ok).toBe(true)
  })

  it('skips the capacity check when the event records no expected attendance', () => {
    const checks = checkSuitability({ expected_attendance: null }, { capacity: 150 })
    expect(byLabel(checks, 'Capacity')).toBeUndefined()
  })

  it('passes room layout when the venue supports it', () => {
    const checks = checkSuitability({ room_layout: 'theatre' }, { supported_layouts: ['theatre', 'banquet'] })
    expect(byLabel(checks, 'Room layout').ok).toBe(true)
  })

  it('fails room layout when the venue does not list it', () => {
    const checks = checkSuitability({ room_layout: 'theatre' }, { supported_layouts: ['banquet'] })
    expect(byLabel(checks, 'Room layout').ok).toBe(false)
  })

  it('skips room layout when the event has none requested', () => {
    const checks = checkSuitability({ room_layout: '' }, { supported_layouts: ['banquet'] })
    expect(byLabel(checks, 'Room layout')).toBeUndefined()
  })

  it('passes accessibility when the venue provides every needed item', () => {
    const checks = checkSuitability(
      { accessibility_needs: [{ item: 'wheelchair_access' }, { item: 'lift_access' }] },
      { accessibility_features: ['wheelchair_access', 'lift_access', 'wifi'] },
    )
    expect(byLabel(checks, 'Accessibility').ok).toBe(true)
  })

  it('fails accessibility and names exactly what is missing', () => {
    const checks = checkSuitability(
      { accessibility_needs: [{ item: 'wheelchair_access' }, { item: 'lift_access' }] },
      { accessibility_features: ['wheelchair_access'] },
    )
    const result = byLabel(checks, 'Accessibility')
    expect(result.ok).toBe(false)
    expect(result.detail).toContain('lift_access')
    expect(result.detail).not.toContain('wheelchair_access')
  })

  it('skips accessibility when the event records no needs', () => {
    const checks = checkSuitability({ accessibility_needs: [] }, { accessibility_features: [] })
    expect(byLabel(checks, 'Accessibility')).toBeUndefined()
  })

  it('tolerates missing event/venue objects entirely without throwing', () => {
    expect(() => checkSuitability(undefined, undefined)).not.toThrow()
    expect(checkSuitability(undefined, undefined)).toEqual([])
  })

  it('runs all three checks together when every field is present', () => {
    const checks = checkSuitability(
      { expected_attendance: 50, room_layout: 'boardroom', accessibility_needs: [{ item: 'lift_access' }] },
      { capacity: 60, supported_layouts: ['boardroom'], accessibility_features: ['lift_access'] },
    )
    expect(checks.map((c) => c.label)).toEqual(['Capacity', 'Room layout', 'Accessibility'])
    expect(checks.every((c) => c.ok)).toBe(true)
  })
})

describe('checkSuitabilityForEvent (IS-13, Coordinator-facing)', () => {
  it('always returns exactly four checks, in a fixed order', () => {
    const checks = checkSuitabilityForEvent({}, {})
    expect(checks.map((c) => c.label)).toEqual(['Capacity', 'Room layout', 'Accessibility', 'Facilities'])
  })

  it('flags capacity as unsuitable, naming the shortfall', () => {
    const checks = checkSuitabilityForEvent({ expected_attendance: 200 }, { capacity: 150 })
    const capacity = checks.find((c) => c.label === 'Capacity')
    expect(capacity.status).toBe('unsuitable')
    expect(capacity.detail).toContain('150')
    expect(capacity.detail).toContain('200')
  })

  it('reports capacity as suitable at or above the expected attendance', () => {
    const checks = checkSuitabilityForEvent({ expected_attendance: 150 }, { capacity: 150 })
    expect(checks.find((c) => c.label === 'Capacity').status).toBe('suitable')
  })

  it('reports capacity as not_assessed when the event records none', () => {
    const checks = checkSuitabilityForEvent({ expected_attendance: null }, { capacity: 150 })
    expect(checks.find((c) => c.label === 'Capacity').status).toBe('not_assessed')
  })

  it('flags room layout as unsuitable when the venue does not support it', () => {
    const checks = checkSuitabilityForEvent({ room_layout: 'theatre' }, { supported_layouts: ['banquet'] })
    expect(checks.find((c) => c.label === 'Room layout').status).toBe('unsuitable')
  })

  it('reports room layout as not_assessed when the event has none requested', () => {
    const checks = checkSuitabilityForEvent({ room_layout: '' }, { supported_layouts: ['banquet'] })
    expect(checks.find((c) => c.label === 'Room layout').status).toBe('not_assessed')
  })

  it('flags accessibility as unsuitable and names exactly what is missing', () => {
    const checks = checkSuitabilityForEvent(
      { accessibility_needs: [{ item: 'wheelchair_access' }, { item: 'lift_access' }] },
      { accessibility_features: ['wheelchair_access'] },
    )
    const accessibility = checks.find((c) => c.label === 'Accessibility')
    expect(accessibility.status).toBe('unsuitable')
    expect(accessibility.detail).toContain('lift_access')
    expect(accessibility.detail).not.toContain('wheelchair_access')
  })

  it('reports accessibility as not_assessed when the event records no needs', () => {
    const checks = checkSuitabilityForEvent({ accessibility_needs: [] }, { accessibility_features: [] })
    expect(checks.find((c) => c.label === 'Accessibility').status).toBe('not_assessed')
  })

  it('always reports facilities as not_assessed -- no story records required facilities yet', () => {
    const checks = checkSuitabilityForEvent(
      { expected_attendance: 10, room_layout: 'boardroom', accessibility_needs: [{ item: 'lift_access' }] },
      { capacity: 20, supported_layouts: ['boardroom'], accessibility_features: ['lift_access'] },
    )
    expect(checks.find((c) => c.label === 'Facilities').status).toBe('not_assessed')
  })

  it('tolerates missing event/venue objects without throwing', () => {
    expect(() => checkSuitabilityForEvent(undefined, undefined)).not.toThrow()
  })
})

describe('isSuitableOverall', () => {
  it('is true when every assessed check passes', () => {
    const checks = [
      { label: 'Capacity', status: 'suitable' },
      { label: 'Room layout', status: 'not_assessed' },
    ]
    expect(isSuitableOverall(checks)).toBe(true)
  })

  it('is false when any check is unsuitable', () => {
    const checks = [
      { label: 'Capacity', status: 'suitable' },
      { label: 'Accessibility', status: 'unsuitable' },
    ]
    expect(isSuitableOverall(checks)).toBe(false)
  })

  it('is true (vacuously) when nothing has been assessed at all', () => {
    const checks = [{ label: 'Capacity', status: 'not_assessed' }]
    expect(isSuitableOverall(checks)).toBe(true)
  })
})
