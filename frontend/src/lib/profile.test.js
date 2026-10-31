import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiPatch = vi.fn()
vi.mock('./api', () => ({ apiPatch: (...args) => apiPatch(...args) }))

import {
  ORGANISATION_MAX_LENGTH,
  hasSavedPreferences,
  organisationError,
  profileForm,
  profilePayload,
  profilePhoneError,
  saveProfile,
} from './profile'

// GET /me for a profile that has never been given any of the IS-68 fields.
const UNSET = { id: 'u1', name: 'Ethan Koh', email: 'ethan@example.com', roles: ['attendee'],
  phone: null, organisation: null, notify_email: null, notify_sms: null }

describe('profileForm', () => {
  it('starts blank, with the same preference defaults as the register form, when nothing is saved', () => {
    expect(profileForm(UNSET)).toEqual({ phone: '', organisation: '', notify_email: true, notify_sms: false })
  })

  it('starts from what the profile has saved', () => {
    expect(profileForm({ ...UNSET, phone: '9123 4567', organisation: 'SMU', notify_email: false, notify_sms: true }))
      .toEqual({ phone: '9123 4567', organisation: 'SMU', notify_email: false, notify_sms: true })
  })

  it('copes with a profile from before the fields existed, and with none', () => {
    expect(profileForm({ id: 'u1', name: 'E', email: 'e@x.com', roles: [] })).toEqual(profileForm(UNSET))
    expect(profileForm(null).phone).toBe('')
  })
})

describe('profilePayload', () => {
  it('sends all three once given', () => {
    const form = { phone: ' +65 9123 4567 ', organisation: ' SMU ', notify_email: false, notify_sms: true }
    expect(profilePayload(form, UNSET)).toEqual({
      phone: '+65 9123 4567', organisation: 'SMU', notify_email: false, notify_sms: true,
    })
  })

  it('sends blank optional fields as null, so clearing one works', () => {
    const saved = { ...UNSET, phone: '9123 4567', organisation: 'SMU', notify_email: true, notify_sms: false }
    expect(profilePayload({ phone: '  ', organisation: '', notify_email: true, notify_sms: false }, saved)).toEqual({
      phone: null, organisation: null, notify_email: true, notify_sms: false,
    })
  })

  it('leaves never-chosen preferences out when the user did not touch them', () => {
    expect(profilePayload(profileForm(UNSET), UNSET)).toEqual({ phone: null, organisation: null })
  })

  it('sends both preferences as soon as one is changed', () => {
    expect(profilePayload({ ...profileForm(UNSET), notify_sms: true }, UNSET)).toEqual({
      phone: null, organisation: null, notify_email: true, notify_sms: true,
    })
  })

  it('never sends id or email', () => {
    const payload = profilePayload({ ...profileForm(UNSET), notify_sms: true, id: 'x', email: 'x@y.z' }, UNSET)
    expect(Object.keys(payload).sort()).toEqual(['notify_email', 'notify_sms', 'organisation', 'phone'])
  })
})

describe('hasSavedPreferences', () => {
  it('is true once either preference is a boolean', () => {
    expect(hasSavedPreferences(UNSET)).toBe(false)
    expect(hasSavedPreferences({ ...UNSET, notify_sms: false })).toBe(true)
  })
})

describe('field errors', () => {
  it('phone is optional, but must look like a phone number when given', () => {
    expect(profilePhoneError('')).toBe('')
    expect(profilePhoneError('   ')).toBe('')
    expect(profilePhoneError('abc')).toMatch('valid phone')
    expect(profilePhoneError('+65 9123 4567')).toBe('')
  })

  it('caps the organisation at the backend limit', () => {
    expect(organisationError('')).toBe('')
    expect(organisationError('x'.repeat(ORGANISATION_MAX_LENGTH))).toBe('')
    expect(organisationError('x'.repeat(ORGANISATION_MAX_LENGTH + 1))).toMatch('at most 200')
  })
})

describe('saveProfile', () => {
  beforeEach(() => apiPatch.mockReset().mockResolvedValue({ phone: null }))

  it('PATCHes the caller own profile, with no id in the path', async () => {
    await saveProfile({ phone: null, organisation: null })
    expect(apiPatch).toHaveBeenCalledWith('/me/profile', { phone: null, organisation: null })
  })
})
