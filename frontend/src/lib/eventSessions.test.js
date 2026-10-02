import { describe, expect, it } from 'vitest'
import {
  emptySession,
  isoToLocalInput,
  localInputToIso,
  sessionFromEvent,
  sessionHasInvalidInput,
  sessionIsComplete,
  sessionPayload,
  validateDateRange,
  validateRegistrationWindow,
  validateSession,
} from './eventSessions'

const MIN = '2026-11-01'

function completeSession(overrides = {}) {
  return {
    ...emptySession(),
    preferred_start_datetime: '2026-11-10T09:00',
    preferred_end_datetime: '2026-11-10T17:00',
    expected_attendance: 50,
    room_layout: 'theatre',
    ...overrides,
  }
}

describe('sessionIsComplete', () => {
  it('accepts a complete session without registration', () => {
    expect(sessionIsComplete(completeSession(), MIN)).toBe(true)
  })

  it('requires the registration window when registration is needed', () => {
    const session = completeSession({ registration_needs: true, registration_start_datetime: '2026-11-01T09:00' })
    expect(sessionIsComplete(session, MIN)).toBe(false)
    session.registration_end_datetime = '2026-11-09T18:00'
    expect(sessionIsComplete(session, MIN)).toBe(true)
  })

  it('allows an overnight session whose end time is earlier on a later date', () => {
    const session = completeSession({ preferred_start_datetime: '2026-11-10T22:00', preferred_end_datetime: '2026-11-11T06:00' })
    expect(sessionIsComplete(session, MIN)).toBe(true)
  })
})

describe('sessionHasInvalidInput', () => {
  it('ignores empty fields -- a half-filled draft is not invalid', () => {
    expect(sessionHasInvalidInput(emptySession(), MIN)).toBe(false)
  })

  it('flags registration closing after the session starts', () => {
    const session = completeSession({
      registration_needs: true,
      registration_start_datetime: '2026-11-01T09:00',
      registration_end_datetime: '2026-11-10T09:01',
    })
    expect(sessionHasInvalidInput(session, MIN)).toBe(true)
  })

  it('ignores a leftover window once registration is unticked', () => {
    const session = completeSession({ registration_start_datetime: '2026-11-05T09:00', registration_end_datetime: '2026-11-04T09:00' })
    expect(sessionHasInvalidInput(session, MIN)).toBe(false)
  })
})

describe('reactive validation', () => {
  it('flags a registration window that closes before it opens as it is typed', () => {
    const session = completeSession({
      registration_needs: true,
      registration_start_datetime: '2026-11-05T09:00',
      registration_end_datetime: '2026-11-04T09:00',
    })
    validateRegistrationWindow(session, MIN)
    expect(session.errors.registration_end_datetime).toMatch(/close after it opens/)
  })

  it('re-checks the registration close when the session start moves earlier', () => {
    const session = completeSession({
      registration_needs: true,
      registration_start_datetime: '2026-11-02T09:00',
      registration_end_datetime: '2026-11-08T09:00',
    })
    validateDateRange(session, MIN)
    expect(session.errors.registration_end_datetime).toBeUndefined()

    session.preferred_start_datetime = '2026-11-07T09:00'
    validateDateRange(session, MIN)
    expect(session.errors.registration_end_datetime).toMatch(/on or before the session starts/)
  })

  it('does not flag a still-empty end date while typing, only at submit', () => {
    const session = completeSession({ preferred_end_datetime: '' })
    validateDateRange(session, MIN)
    expect(session.errors.preferred_end_datetime).toBeUndefined()
    expect(validateSession(session, MIN)).toBe(false)
    expect(session.errors.preferred_end_datetime).toMatch(/required/)
  })
})

describe('payload round trip', () => {
  it('splits datetimes, converts the registration window to ISO and keeps the id', () => {
    const session = completeSession({
      id: 'event-1',
      registration_needs: true,
      registration_start_datetime: '2026-11-01T09:00',
      registration_end_datetime: '2026-11-09T18:00',
    })
    const payload = sessionPayload(session)
    expect(payload).toMatchObject({
      id: 'event-1',
      preferred_start_date: '2026-11-10',
      preferred_start_time: '09:00',
      registration_start_datetime: localInputToIso('2026-11-01T09:00'),
    })
    expect(payload).not.toHaveProperty('errors')
    expect(payload).not.toHaveProperty('key')
  })

  it('drops the window when registration is not needed', () => {
    const payload = sessionPayload(completeSession({ registration_start_datetime: '2026-11-01T09:00' }))
    expect(payload.registration_start_datetime).toBeNull()
  })

  it('shows a stored timestamptz back in local time', () => {
    const iso = localInputToIso('2026-11-01T09:30')
    expect(isoToLocalInput(iso)).toBe('2026-11-01T09:30')
    const session = sessionFromEvent({ id: 'e', status: 'draft', registration_needs: true, registration_start_datetime: iso })
    expect(session.registration_start_datetime).toBe('2026-11-01T09:30')
  })

})
