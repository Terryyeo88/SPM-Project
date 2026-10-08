import { describe, expect, it } from 'vitest'
import {
  CHANGE_REQUEST_STATUSES,
  buildChanges,
  describeChange,
  describeLogEntry,
  describeValue,
  eventFields,
  impactAreas,
  impactsOf,
  isChangeable,
  pendingChangeFor,
  touchesSharedDetails,
} from './changeRequests'
import { sessionFromEvent } from './eventSessions'

function row(overrides = {}) {
  return {
    id: 'session-1',
    status: 'confirmed',
    name: 'Community Conference',
    description: 'A community conference.',
    purpose: 'Knowledge sharing.',
    preferred_start_date: '2026-11-10',
    preferred_start_time: '09:00:00',
    preferred_end_date: '2026-11-10',
    preferred_end_time: '17:00:00',
    expected_attendance: 100,
    accessibility_needs: [{ item: 'wheelchair_access' }],
    room_layout: 'theatre',
    equipment_needed: { equipment: [{ item: 'projector', quantity: 1 }] },
    registration_needs: false,
    registration_start_datetime: null,
    registration_end_datetime: null,
    special_requests: null,
    ...overrides,
  }
}

function formFor(event) {
  return { name: event.name, description: event.description, purpose: event.purpose, session: sessionFromEvent(event) }
}

describe('isChangeable', () => {
  it('allows every status from submitted up to confirmed', () => {
    for (const status of CHANGE_REQUEST_STATUSES) expect(isChangeable(status)).toBe(true)
  })

  it('refuses drafts, rejected requests and finished events', () => {
    for (const status of ['draft', 'rejected', 'completed', 'cancelled', undefined]) {
      expect(isChangeable(status)).toBe(false)
    }
  })
})

describe('buildChanges', () => {
  it('is empty when nothing was edited, despite database time formats', () => {
    expect(buildChanges(row(), formFor(row()))).toEqual({})
  })

  it('keeps only the edited fields, in the API field names', () => {
    const form = formFor(row())
    form.name = 'Community Summit'
    form.session.expected_attendance = 150
    form.session.equipment.push({ item: 'microphone', quantity: 2 })

    expect(buildChanges(row(), form)).toEqual({
      name: 'Community Summit',
      expected_attendance: 150,
      equipment: [
        { item: 'projector', quantity: 1 },
        { item: 'microphone', quantity: 2 },
      ],
    })
  })

  it('splits an edited start back into its date and time fields', () => {
    const form = formFor(row())
    form.session.preferred_start_datetime = '2026-11-10T10:30'

    expect(buildChanges(row(), form)).toEqual({ preferred_start_time: '10:30' })
  })

  it('treats a blank and an unset value as the same', () => {
    const form = formFor(row({ special_requests: null }))
    form.session.special_requests = ''
    expect(buildChanges(row(), form)).toEqual({})
  })

  it('reports a cleared value', () => {
    const form = formFor(row({ special_requests: 'Near the lift.' }))
    form.session.special_requests = ''
    expect(buildChanges(row({ special_requests: 'Near the lift.' }), form)).toEqual({ special_requests: '' })
  })
})

describe('eventFields', () => {
  it('maps equipment_needed to the API equipment field and drops the id', () => {
    const fields = eventFields(row())
    expect(fields.equipment).toEqual([{ item: 'projector', quantity: 1 }])
    expect(fields).not.toHaveProperty('id')
    expect(fields).not.toHaveProperty('equipment_needed')
  })
})

describe('pendingChangeFor', () => {
  const changes = [
    { id: 'a', event_id: 'session-1', status: 'rejected' },
    { id: 'b', event_id: 'session-2', status: 'pending' },
    { id: 'c', event_id: 'session-1', status: 'pending' },
  ]

  it('finds the pending change for that session only', () => {
    expect(pendingChangeFor(changes, 'session-1').id).toBe('c')
    expect(pendingChangeFor(changes, 'session-3')).toBeNull()
    expect(pendingChangeFor(undefined, 'session-1')).toBeNull()
  })
})

describe('describeChange', () => {
  it('lists each requested field as from -> to, in form order', () => {
    const change = {
      requested_changes: { room_layout: 'banquet', name: 'Summit', registration_needs: true },
      previous_values: { room_layout: 'theatre', name: 'Conference', registration_needs: false },
    }

    expect(describeChange(change)).toEqual([
      { field: 'name', label: 'Event name', from: 'Conference', to: 'Summit' },
      { field: 'room_layout', label: 'Room layout', from: 'Theatre', to: 'Banquet' },
      { field: 'registration_needs', label: 'Registration needed', from: 'No', to: 'Yes' },
    ])
  })

  it('copes with a missing change', () => {
    expect(describeChange(undefined)).toEqual([])
  })
})

describe('describeValue', () => {
  it('formats items, times and blanks for a reader', () => {
    expect(describeValue('equipment', [{ item: 'microphone', quantity: 2 }, { item: 'wifi', quantity: 1 }]))
      .toBe('Microphones × 2, WiFi')
    expect(describeValue('accessibility_needs', [])).toBe('None')
    expect(describeValue('preferred_start_time', '09:00:00')).toBe('09:00')
    expect(describeValue('special_requests', null)).toBe('Not set')
    expect(describeValue('expected_attendance', 150)).toBe('150')
  })
})

describe('touchesSharedDetails', () => {
  it('is true only when name, description or purpose change', () => {
    expect(touchesSharedDetails({ requested_changes: { purpose: 'x' } })).toBe(true)
    expect(touchesSharedDetails({ requested_changes: { room_layout: 'banquet' } })).toBe(false)
  })
})

describe('impactsOf / impactAreas', () => {
  const venue = { area: 'venue', severity: 'conflict', title: 'Venue booking', issues: ['x'] }
  const venue2 = { ...venue, title: 'Second booking' }
  const equipment = { area: 'equipment', severity: 'check', title: 'Equipment', issues: ['y'] }

  it('returns the impacts of a pending change and its distinct areas', () => {
    const change = { status: 'pending', impact: [venue, venue2, equipment] }
    expect(impactsOf(change)).toHaveLength(3)
    expect(impactAreas(change)).toEqual(['venue', 'equipment'])
  })

  it('ignores decided changes and missing impact data', () => {
    expect(impactsOf({ status: 'approved', impact: [venue] })).toEqual([])
    expect(impactsOf({ status: 'pending' })).toEqual([])
    expect(impactAreas(undefined)).toEqual([])
  })
})

describe('describeLogEntry', () => {
  it('lists what changed as from -> to, in form order', () => {
    const entry = {
      changes: {
        room_layout: { from: 'theatre', to: 'banquet' },
        expected_attendance: { from: 100, to: 150 },
      },
    }
    expect(describeLogEntry(entry)).toEqual([
      { field: 'expected_attendance', label: 'Expected attendance', from: '100', to: '150' },
      { field: 'room_layout', label: 'Room layout', from: 'Theatre', to: 'Banquet' },
    ])
  })

  it('copes with a missing entry', () => {
    expect(describeLogEntry(undefined)).toEqual([])
  })
})
