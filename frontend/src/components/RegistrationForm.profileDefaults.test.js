/**
 * IS-68 regression guard for Justin's register form. Adding phone,
 * organisation, notify_email and notify_sms to GET /me deliberately
 * activates lib/registrations.js prefillFromProfile. The case that must
 * NOT change is the one every existing user is in: a profile whose four
 * new fields are all null must give exactly the form it gave before
 * GET /me returned them at all -- same fields shown, same defaults, same
 * request body. (RegistrationForm.vue itself is unchanged by IS-68.)
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiPost = vi.fn()
vi.mock('../lib/api', () => ({ apiPost: (...args) => apiPost(...args) }))
vi.mock('../lib/supabaseClient', () => ({ supabase: { auth: {} } }))

import RegistrationForm from './RegistrationForm.vue'
import { useAuthStore } from '../stores/auth'

// GET /me before IS-68.
const BEFORE = { id: 'u1', name: 'Ethan Koh', email: 'ethan@example.com', roles: ['attendee'] }
// GET /me after IS-68, for a profile that has never saved any of them.
const AFTER_NULLS = { ...BEFORE, phone: null, organisation: null, notify_email: null, notify_sms: null }

const SESSION = { id: 's1', name: 'Annual Tech Symposium', places_left: 10 }

function mountForm(profile) {
  const pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().profile = profile
  return mount(RegistrationForm, { props: { session: SESSION }, global: { plugins: [pinia] } })
}

/** Everything the attendee sees and can change, in one comparable object. */
function snapshot(wrapper) {
  const checkboxes = wrapper.findAll('input[type="checkbox"]').map((box) => box.element.checked)
  return {
    name: wrapper.find('#reg-name').element.value,
    email: wrapper.find('#reg-email').element.value,
    phone: wrapper.find('#reg-phone').element.value,
    organisationShown: wrapper.find('input[aria-label="Organisation"]').exists(),
    organisationText: wrapper.text().includes('No organisation on your profile.'),
    checkboxes,
    html: wrapper.html(),
  }
}

/** Types a phone, submits, and returns the one request this form sent. */
async function submitWithPhone(wrapper) {
  apiPost.mockClear()
  await wrapper.find('#reg-phone').setValue('9123 4567')
  await wrapper.find('form').trigger('submit')
  await flushPromises()
  expect(apiPost).toHaveBeenCalledTimes(1)
  return apiPost.mock.calls[0]
}

describe('RegistrationForm with a profile whose IS-68 fields are all null', () => {
  beforeEach(() => apiPost.mockReset().mockResolvedValue({ id: 'r1' }))

  it('renders exactly as it did before GET /me returned the fields', () => {
    expect(snapshot(mountForm(AFTER_NULLS))).toEqual(snapshot(mountForm(BEFORE)))
  })

  it('starts with phone blank, no organisation, email on and SMS off -- the pre-IS-68 defaults', () => {
    const form = snapshot(mountForm(AFTER_NULLS))
    expect(form.phone).toBe('')
    expect(form.organisationShown).toBe(false)
    expect(form.organisationText).toBe(true)
    // [Email notifications, SMS notifications]
    expect(form.checkboxes).toEqual([true, false])
  })

  it('sends the same registration body as before', async () => {
    const before = await submitWithPhone(mountForm(BEFORE))
    const after = await submitWithPhone(mountForm(AFTER_NULLS))

    expect(after).toEqual(before)
    expect(after).toEqual(['/registrations/s1', {
      email: 'ethan@example.com', phone: '9123 4567', notify_email: true, notify_sms: false,
      include_organisation: false, notes: undefined,
    }])
  })

  it('once the profile does have them, they prefill -- the activation IS-68 intends', () => {
    const form = snapshot(mountForm({
      ...BEFORE, phone: '+65 8000 0000', organisation: 'SMU', notify_email: false, notify_sms: true,
    }))
    expect(form.phone).toBe('+65 8000 0000')
    expect(form.organisationShown).toBe(true)
    // [Include my organisation, Email notifications, SMS notifications]
    expect(form.checkboxes).toEqual([true, false, true])
  })
})
