import { describe, expect, it } from 'vitest'
import {
  arrangementsOfPreview,
  describePreviewChanges,
  isNoChange,
  needsReview,
  previewImpactAreas,
  savedMessage,
} from './eventUpdates'

function preview(overrides = {}) {
  return {
    changes: { name: { from: 'Old', to: 'New' } },
    significance: 'ordinary',
    significant_fields: [],
    impacts: [],
    reverts_to_planning: false,
    ...overrides,
  }
}

describe('needsReview (IS-9: present arrangements before a significant change is committed)', () => {
  it('saves an ordinary change that touches nothing straight away', () => {
    expect(needsReview(preview())).toBe(false)
  })

  it('reviews a significant change, even with nothing arranged yet', () => {
    expect(needsReview(preview({ significance: 'significant', significant_fields: ['expected_attendance'] }))).toBe(true)
  })

  it('saves a significant change straight away before planning, when impacts are not checked', () => {
    const early = preview({ significance: 'significant', significant_fields: ['expected_attendance'], impacts_checked: false })
    expect(needsReview(early)).toBe(false)
  })

  it('reviews any change that touches an arrangement', () => {
    expect(needsReview(preview({ impacts: [{ area: 'registration', issues: [] }] }))).toBe(true)
  })

  it('reviews any change to a confirmed event, which goes back to planning', () => {
    expect(needsReview(preview({ reverts_to_planning: true }))).toBe(true)
  })

  it('has nothing to review when nothing changed', () => {
    const unchanged = preview({ changes: {}, significance: null })
    expect(isNoChange(unchanged)).toBe(true)
    expect(needsReview(unchanged)).toBe(false)
  })
})

describe('previewImpactAreas', () => {
  it('names each affected area once -- what the save must acknowledge', () => {
    const impacts = [
      { area: 'venue', booking_id: 'a' },
      { area: 'venue', booking_id: 'b' },
      { area: 'technical_support' },
    ]
    expect(previewImpactAreas(preview({ impacts }))).toEqual(['venue', 'technical_support'])
  })
})

describe('describePreviewChanges', () => {
  it('lists each change readably, marking the significant ones', () => {
    const rows = describePreviewChanges(preview({
      changes: {
        expected_attendance: { from: 100, to: 150 },
        name: { from: 'Old', to: 'New' },
        preferred_start_time: { from: '09:00:00', to: '10:00:00' },
      },
      significant_fields: ['expected_attendance', 'preferred_start_time'],
    }))

    expect(rows).toEqual([
      { field: 'name', label: 'Event name', from: 'Old', to: 'New', significant: false },
      { field: 'preferred_start_time', label: 'Start time', from: '09:00', to: '10:00', significant: true },
      { field: 'expected_attendance', label: 'Expected attendance', from: '100', to: '150', significant: true },
    ])
  })
})

describe('savedMessage', () => {
  it('says when a confirmed event went back to planning', () => {
    expect(savedMessage('confirmed', { status: 'planning' })).toContain('back In Planning')
  })

  it('is plain otherwise', () => {
    expect(savedMessage('planning', { status: 'planning' })).toBe('Event details updated.')
  })
})

describe('arrangementsOfPreview (IS-9: which already-made arrangements a change touches)', () => {
  const venue = { area: 'venue', id: 'booking-1', title: 'Venue booking: Hall A', status: 'confirmed', fields: ['preferred_end_time'] }
  const other = { area: 'venue', id: 'booking-2', title: 'Venue booking: Room B', status: 'pending', fields: ['preferred_end_time'] }
  const registration = { area: 'registration', id: null, title: 'Attendee registrations (3 confirmed)', status: null, fields: ['expected_attendance', 'preferred_end_time'] }

  it('is empty when the preview has none', () => {
    expect(arrangementsOfPreview(preview())).toEqual([])
    expect(arrangementsOfPreview(undefined)).toEqual([])
  })

  it('labels each arrangement and the details it depends on', () => {
    const [entry] = arrangementsOfPreview(preview({ arrangements: [registration] }))
    expect(entry).toEqual({
      key: 'registration:',
      area: 'registration',
      areaLabel: 'Registration',
      title: 'Attendee registrations (3 confirmed)',
      status: null,
      fields: 'Expected attendance, End time',
      conflict: false,
    })
  })

  it('marks only the venue booking an impact names as conflicting', () => {
    const entries = arrangementsOfPreview(preview({
      arrangements: [venue, other],
      impacts: [{ area: 'venue', booking_id: 'booking-2', severity: 'conflict', issues: [] }],
    }))
    expect(entries.map((entry) => [entry.key, entry.conflict])).toEqual([['venue:booking-1', false], ['venue:booking-2', true]])
  })

  it('marks an area-wide impact against every arrangement in that area', () => {
    const entries = arrangementsOfPreview(preview({
      arrangements: [registration, venue],
      impacts: [{ area: 'registration', severity: 'conflict', issues: [] }],
    }))
    expect(entries.map((entry) => entry.conflict)).toEqual([true, false])
  })

  it('makes a touched arrangement worth reviewing even with no conflict', () => {
    expect(needsReview(preview({ arrangements: [venue] }))).toBe(true)
  })
})
