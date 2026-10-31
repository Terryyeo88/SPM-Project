import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiPatch = vi.fn()
vi.mock('./api', () => ({ apiPatch: (...args) => apiPatch(...args) }))

import {
  AT_LEAST_ONE_MESSAGE,
  PHONE_FORMAT_MESSAGE,
  SMS_NEEDS_PHONE_MESSAGE,
  hasPhone,
  localPart,
  preferencesError,
  profileForm,
  profilePayload,
  profilePhoneError,
  saveProfile,
  smsDisabled,
} from './profile'

// GET /me for a profile that has never been edited: the column defaults.
const DEFAULTS = { id: 'u1', name: 'Ethan Koh', email: 'ethan@example.com', roles: ['attendee'],
  phone: null, organisation: null, notify_email: true, notify_sms: false }

describe('profileForm', () => {
  it('starts blank with email on and SMS off for a never-edited profile', () => {
    expect(profileForm(DEFAULTS)).toEqual({ phone: '', notify_email: true, notify_sms: false })
  })

  it('starts from what the profile has saved, showing the 8 digits after +65', () => {
    expect(profileForm({ ...DEFAULTS, phone: '+6591234567', notify_email: false, notify_sms: true }))
      .toEqual({ phone: '9123 4567', notify_email: false, notify_sms: true })
  })

  it('falls back to the defaults for a missing or null preference, and copes with no profile', () => {
    expect(profileForm({ id: 'u1', name: 'E', email: 'e@x.com', roles: [] })).toEqual(profileForm(DEFAULTS))
    expect(profileForm({ ...DEFAULTS, notify_email: null, notify_sms: null })).toEqual(profileForm(DEFAULTS))
    expect(profileForm(null)).toEqual(profileForm(DEFAULTS))
  })

  it('never carries organisation, which is read-only', () => {
    expect(profileForm({ ...DEFAULTS, organisation: 'SMU' })).not.toHaveProperty('organisation')
  })
})

describe('localPart', () => {
  it('drops +65 and spaces the 8 digits', () => {
    expect(localPart('+6591234567')).toBe('9123 4567')
    expect(localPart('+65 9123 4567')).toBe('9123 4567')
  })

  it('leaves anything else as it is, and blank as blank', () => {
    expect(localPart('123')).toBe('123')
    expect(localPart(null)).toBe('')
  })
})

describe('profilePayload', () => {
  it('sends the phone with +65 in front and no spaces', () => {
    expect(profilePayload({ phone: ' 9123 4567 ', notify_email: false, notify_sms: true })).toEqual({
      phone: '+6591234567', notify_email: false, notify_sms: true,
    })
    expect(profilePayload({ phone: '9123-4567', notify_email: true, notify_sms: false }).phone).toBe('+6591234567')
  })

  it('sends a blank phone as null, so clearing it works', () => {
    expect(profilePayload({ phone: '  ', notify_email: true, notify_sms: false })).toEqual({
      phone: null, notify_email: true, notify_sms: false,
    })
  })

  it('only ever sends phone and the two preferences', () => {
    const payload = profilePayload({ ...profileForm(DEFAULTS), id: 'x', email: 'x@y.z', organisation: 'SMU' })
    expect(Object.keys(payload).sort()).toEqual(['notify_email', 'notify_sms', 'phone'])
  })
})

describe('profilePhoneError', () => {
  it('is optional', () => {
    expect(profilePhoneError('')).toBe('')
    expect(profilePhoneError('   ')).toBe('')
    expect(profilePhoneError(null)).toBe('')
  })

  it('accepts exactly 8 digits, with or without a space or hyphen', () => {
    expect(profilePhoneError('91234567')).toBe('')
    expect(profilePhoneError('9123 4567')).toBe('')
    expect(profilePhoneError('9123-4567')).toBe('')
  })

  it.each(['9123 456', '9123 45678', 'abcdefgh', '+6591234567'])('refuses %s', (phone) => {
    expect(profilePhoneError(phone)).toBe(PHONE_FORMAT_MESSAGE)
  })
})

describe('preferencesError', () => {
  it('needs at least one', () => {
    expect(preferencesError({ phone: '91234567', notify_email: false, notify_sms: false })).toBe(AT_LEAST_ONE_MESSAGE)
  })

  it('needs a phone for SMS', () => {
    expect(preferencesError({ phone: '', notify_email: true, notify_sms: true })).toBe(SMS_NEEDS_PHONE_MESSAGE)
  })

  it('is fine otherwise', () => {
    expect(preferencesError({ phone: '', notify_email: true, notify_sms: false })).toBe('')
    expect(preferencesError({ phone: '91234567', notify_email: false, notify_sms: true })).toBe('')
    expect(preferencesError({ phone: '91234567', notify_email: true, notify_sms: true })).toBe('')
  })
})

describe('smsDisabled / hasPhone', () => {
  it('disables an unticked SMS box while there is no phone', () => {
    expect(smsDisabled({ phone: '', notify_sms: false })).toBe(true)
    expect(smsDisabled({ phone: '9123 4567', notify_sms: false })).toBe(false)
  })

  it('keeps a ticked SMS box usable after the phone is cleared, so it can be unticked', () => {
    expect(smsDisabled({ phone: '', notify_sms: true })).toBe(false)
  })

  it('treats spaces as no phone', () => {
    expect(hasPhone({ phone: '   ' })).toBe(false)
  })
})

describe('saveProfile', () => {
  beforeEach(() => apiPatch.mockReset().mockResolvedValue({ phone: null }))

  it('PATCHes the caller own profile, with no id in the path', async () => {
    await saveProfile({ phone: null, notify_email: true, notify_sms: false })
    expect(apiPatch).toHaveBeenCalledWith('/me/profile', { phone: null, notify_email: true, notify_sms: false })
  })
})
