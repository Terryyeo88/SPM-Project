import { describe, expect, it } from 'vitest'
import {
  availabilityTag,
  emailError,
  filterSessions,
  notesError,
  notifyError,
  phoneError,
  placesLabel,
  prefillFromProfile,
  registrationPayload,
  registrationState,
  registrationStatusLabel,
  spotsFilled,
} from './registrations'

const NOW = new Date('2026-10-04T08:00:00Z')
const OPEN = { registration_start_datetime: '2026-10-03T00:00:00Z', registration_end_datetime: '2026-11-02T15:59:00Z' }

describe('registrationState', () => {
  it('is open inside the window', () => {
    expect(registrationState(OPEN, NOW)).toBe('open')
  })

  it('is upcoming before the window opens and closed after it closes', () => {
    expect(registrationState({ registration_start_datetime: '2026-10-04T10:00:00Z' }, NOW)).toBe('upcoming')
    expect(registrationState({ registration_end_datetime: '2026-10-03T08:00:00Z' }, NOW)).toBe('closed')
  })

  it('treats a session without a window as open', () => {
    expect(registrationState({}, NOW)).toBe('open')
  })
})

describe('availabilityTag (the search-result card tag)', () => {
  it('is Open, Almost Full or Waitlist Only by how full it is', () => {
    expect(availabilityTag({ ...OPEN, capacity: 10, confirmed_count: 2, places_left: 8 }, NOW).label).toBe('Open')
    expect(availabilityTag({ ...OPEN, capacity: 10, confirmed_count: 8, places_left: 2 }, NOW).label).toBe('Almost Full')
    expect(availabilityTag({ ...OPEN, capacity: 2, confirmed_count: 2, places_left: 0 }, NOW).label).toBe('Waitlist Only')
  })

  it('says when registration has not opened or has closed', () => {
    expect(availabilityTag({ registration_start_datetime: '2026-10-04T10:00:00Z' }, NOW).label).toBe('Opens Soon')
    expect(availabilityTag({ registration_end_datetime: '2026-10-03T00:00:00Z' }, NOW).label).toBe('Registration Closed')
  })
})

describe('spotsFilled / placesLabel', () => {
  it('reports spots filled out of capacity', () => {
    expect(spotsFilled({ capacity: 60, confirmed_count: 42 })).toEqual({ filled: 42, capacity: 60, percent: 70 })
    expect(spotsFilled({ capacity: null })).toBeNull()
  })

  it('counts spots left, and says a full session goes to the waiting list', () => {
    expect(placesLabel({ places_left: 18 })).toBe('18 spots left')
    expect(placesLabel({ places_left: 1 })).toBe('1 spot left')
    expect(placesLabel({ places_left: 0 })).toMatch('waiting list')
    expect(placesLabel({ places_left: null })).toBe('Spots available')
  })
})

describe('filterSessions', () => {
  const sessions = [
    { name: 'Tech Talk', preferred_start_date: '2026-11-03', preferred_end_date: '2026-11-03' },
    { name: 'Design Workshop', preferred_start_date: '2026-11-10', preferred_end_date: '2026-11-12' },
  ]

  it('matches the name case-insensitively', () => {
    expect(filterSessions(sessions, { query: 'tech' }).map((s) => s.name)).toEqual(['Tech Talk'])
  })

  it('matches a date inside a multi-day session', () => {
    expect(filterSessions(sessions, { date: '2026-11-11' }).map((s) => s.name)).toEqual(['Design Workshop'])
    expect(filterSessions(sessions, { date: '2026-11-04' })).toEqual([])
  })

  it('returns everything with no criteria', () => {
    expect(filterSessions(sessions, {})).toHaveLength(2)
  })
})

describe('prefillFromProfile', () => {
  it('prefills name and email; email notifications on by default', () => {
    expect(prefillFromProfile({ name: 'Ethan Koh', email: 'ethan@example.com' })).toEqual({
      name: 'Ethan Koh',
      email: 'ethan@example.com',
      phone: '',
      organisation: '',
      include_organisation: false,
      notify_email: true,
      notify_sms: false,
      notes: '',
    })
  })

  it('picks up phone, organisation and notification choices once profiles have them', () => {
    const form = prefillFromProfile({
      email: 'e@x.com', phone: '91234567', organisation: 'Acme', notify_email: false, notify_sms: true,
    })
    expect(form.phone).toBe('91234567')
    expect(form.organisation).toBe('Acme')
    expect(form.include_organisation).toBe(true)
    expect([form.notify_email, form.notify_sms]).toEqual([false, true])
  })

  it('copes with no profile', () => {
    expect(prefillFromProfile(null).email).toBe('')
  })
})

describe('registrationPayload', () => {
  it('sends only what the attendee may change, plus whether to include the organisation', () => {
    const payload = registrationPayload({
      name: 'Ethan', email: ' e@x.com ', phone: ' 91234567 ', organisation: 'Acme',
      include_organisation: true, notify_email: true, notify_sms: true, notes: '  ',
    })
    expect(payload).toEqual({
      email: 'e@x.com', phone: '91234567', notify_email: true, notify_sms: true,
      include_organisation: true, notes: undefined,
    })
  })

  it('never includes an organisation the profile does not have', () => {
    const payload = registrationPayload({ ...prefillFromProfile({ email: 'e@x.com' }), include_organisation: true })
    expect(payload.include_organisation).toBe(false)
  })
})

describe('field errors', () => {
  it('requires a valid email address', () => {
    expect(emailError('')).toMatch('required')
    expect(emailError('ethan@example')).toMatch('valid email')
    expect(emailError(' ethan@example.com ')).toBe('')
  })

  it('requires a phone number that looks like one', () => {
    expect(phoneError('')).toMatch('required')
    expect(phoneError('abc')).toMatch('valid phone')
    for (const phone of ['91234567', '9123 4567', '+65 9123 4567']) {
      expect(phoneError(phone)).toBe('')
    }
  })

  it('requires email or SMS notifications (or both)', () => {
    expect(notifyError({ notify_email: false, notify_sms: false })).toMatch('at least one')
    expect(notifyError({ notify_email: true, notify_sms: true })).toBe('')
  })

  it('caps notes at 500 characters', () => {
    expect(notesError('x'.repeat(501))).toMatch('at most 500')
  })
})

describe('registrationStatusLabel', () => {
  it('shows the waiting-list position', () => {
    expect(registrationStatusLabel({ status: 'confirmed' })).toBe('Confirmed')
    expect(registrationStatusLabel({ status: 'waitlisted', waitlist_position: 2 })).toBe('Waitlisted (#2)')
  })
})
