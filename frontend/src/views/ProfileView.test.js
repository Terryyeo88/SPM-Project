import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiPatch = vi.fn()
vi.mock('../lib/api', () => ({ apiPatch: (...args) => apiPatch(...args) }))
vi.mock('../lib/supabaseClient', () => ({ supabase: { auth: {} } }))
vi.mock('../components/AppNavBar.vue', () => ({ default: { template: '<nav />' } }))

import ProfileView from './ProfileView.vue'
import { useAuthStore } from '../stores/auth'
import { AT_LEAST_ONE_MESSAGE, PHONE_FORMAT_MESSAGE, SMS_NEEDS_PHONE_MESSAGE } from '../lib/profile'

// GET /me for a never-edited profile: the column defaults.
const DEFAULTS = {
  id: 'u1', name: 'Ethan Koh', email: 'ethan@example.com', roles: ['attendee'],
  phone: null, organisation: null, notify_email: true, notify_sms: false,
}

async function mountView(profile = DEFAULTS) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  auth.session = { access_token: 'tok' }
  auth.profile = profile
  const stub = { template: '<div />' }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'dashboard', component: stub },
      { path: '/login', name: 'login', component: stub },
      { path: '/profile', name: 'profile', component: ProfileView },
    ],
  })
  router.push('/profile')
  await router.isReady()
  const wrapper = mount(ProfileView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return { wrapper, auth }
}

const phone = (wrapper) => wrapper.find('#profile-phone')
const email = (wrapper) => wrapper.find('#profile-notify-email')
const sms = (wrapper) => wrapper.find('#profile-notify-sms')
const fieldErrors = (wrapper) => wrapper.findAll('.field-error').map((error) => error.text())

async function save(wrapper) {
  await wrapper.find('form.contact').trigger('submit')
  await flushPromises()
}

describe('ProfileView contact details and preferences (IS-68)', () => {
  beforeEach(() => {
    // Like PATCH /me/profile: the four fields as saved, nothing else.
    apiPatch.mockReset().mockImplementation((path, body) => Promise.resolve({
      phone: null, organisation: null, notify_email: true, notify_sms: false, ...body,
    }))
  })

  it('shows phone and preferences as editable; name, email, organisation and roles read-only', async () => {
    const { wrapper } = await mountView({ ...DEFAULTS, organisation: 'SMU' })

    expect(wrapper.find('label[for="profile-phone"]').text()).toBe('Phone Number (optional)')
    expect(wrapper.find('.prefix').text()).toBe('+65')
    expect(wrapper.find('legend').text()).toBe('Communication Preferences')
    expect(wrapper.text()).toContain('Email notifications')
    expect(wrapper.text()).toContain('SMS notifications')
    const readOnly = wrapper.find('dl').text()
    expect(readOnly).toContain('Ethan Koh')
    expect(readOnly).toContain('ethan@example.com')
    expect(readOnly).toContain('SMU')
    expect(wrapper.find('form.contact').findAll('input').map((input) => input.attributes('id')))
      .toEqual(['profile-phone', 'profile-notify-email', 'profile-notify-sms'])
  })

  it('shows "None" when there is no organisation', async () => {
    const { wrapper } = await mountView()

    expect(wrapper.find('dl').text()).toContain('OrganisationNone')
  })

  it('starts blank with email on, SMS off and locked, for a never-edited profile', async () => {
    const { wrapper } = await mountView()

    expect(phone(wrapper).element.value).toBe('')
    expect([email(wrapper).element.checked, sms(wrapper).element.checked]).toEqual([true, false])
    expect(sms(wrapper).element.disabled).toBe(true)
    expect(wrapper.text()).toContain('Add a phone number to choose SMS.')
  })

  it('starts from what the profile has saved, showing the 8 digits after +65', async () => {
    const { wrapper } = await mountView({ ...DEFAULTS, phone: '+6591234567', notify_email: false, notify_sms: true })

    expect(phone(wrapper).element.value).toBe('9123 4567')
    expect([email(wrapper).element.checked, sms(wrapper).element.checked]).toEqual([false, true])
    expect(sms(wrapper).element.disabled).toBe(false)
  })

  it('unlocks SMS once a phone is typed', async () => {
    const { wrapper } = await mountView()

    await phone(wrapper).setValue('9123 4567')

    expect(sms(wrapper).element.disabled).toBe(false)
    expect(wrapper.text()).not.toContain('Add a phone number to choose SMS.')
  })

  it('saves phone and preferences to PATCH /me/profile and keeps the store in step', async () => {
    const { wrapper, auth } = await mountView()

    await phone(wrapper).setValue('9123 4567')
    await email(wrapper).setValue(false)
    await sms(wrapper).setValue(true)
    await save(wrapper)

    expect(apiPatch).toHaveBeenCalledWith('/me/profile', { phone: '+6591234567', notify_email: false, notify_sms: true })
    expect(wrapper.find('[role="status"]').text()).toBe('Saved.')
    expect(auth.profile).toMatchObject({ id: 'u1', name: 'Ethan Koh', phone: '+6591234567', notify_sms: true })
  })

  it('saves with the phone left blank', async () => {
    const { wrapper } = await mountView()

    await save(wrapper)

    expect(apiPatch).toHaveBeenCalledWith('/me/profile', { phone: null, notify_email: true, notify_sms: false })
  })

  it('clearing a saved phone sends null', async () => {
    const { wrapper, auth } = await mountView({ ...DEFAULTS, phone: '+6591234567' })

    await phone(wrapper).setValue('   ')
    await save(wrapper)

    expect(apiPatch).toHaveBeenCalledWith('/me/profile', { phone: null, notify_email: true, notify_sms: false })
    expect(auth.profile.phone).toBeNull()
  })

  it.each(['9123 456', 'call me'])('a phone of "%s" is shown as an error and not saved', async (typed) => {
    const { wrapper } = await mountView()

    await phone(wrapper).setValue(typed)
    await save(wrapper)

    expect(apiPatch).not.toHaveBeenCalled()
    expect(fieldErrors(wrapper)).toContain(PHONE_FORMAT_MESSAGE)
  })

  it('unticking both preferences is shown as an error and not saved', async () => {
    const { wrapper } = await mountView()

    await email(wrapper).setValue(false)
    await save(wrapper)

    expect(apiPatch).not.toHaveBeenCalled()
    expect(fieldErrors(wrapper)).toContain(AT_LEAST_ONE_MESSAGE)
  })

  it('clearing the phone while SMS is on is an error until SMS is unticked', async () => {
    const { wrapper } = await mountView({ ...DEFAULTS, phone: '+6591234567', notify_sms: true })

    await phone(wrapper).setValue('')
    expect(sms(wrapper).element.disabled).toBe(false)
    await save(wrapper)
    expect(apiPatch).not.toHaveBeenCalled()
    expect(fieldErrors(wrapper)).toContain(SMS_NEEDS_PHONE_MESSAGE)

    await sms(wrapper).setValue(false)
    await save(wrapper)
    expect(apiPatch).toHaveBeenCalledWith('/me/profile', { phone: null, notify_email: true, notify_sms: false })
  })

  it('never sends id, email or organisation', async () => {
    const { wrapper } = await mountView({ ...DEFAULTS, organisation: 'SMU' })

    await phone(wrapper).setValue('9123 4567')
    await sms(wrapper).setValue(true)
    await save(wrapper)

    expect(Object.keys(apiPatch.mock.calls[0][1]).sort()).toEqual(['notify_email', 'notify_sms', 'phone'])
  })

  it('shows the error when saving fails, and keeps what was typed', async () => {
    apiPatch.mockRejectedValue(new Error('Add a phone number to turn on SMS notifications.'))
    const { wrapper, auth } = await mountView()

    await phone(wrapper).setValue('9123 4567')
    await save(wrapper)

    expect(wrapper.find('[role="alert"]').text()).toContain("Couldn't save")
    expect(phone(wrapper).element.value).toBe('9123 4567')
    expect(auth.profile.phone).toBeNull()
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
  })

  it('picks the fields up when the profile loads after the page', async () => {
    const { wrapper, auth } = await mountView(null)
    expect(wrapper.find('form.contact').exists()).toBe(false)

    auth.profile = { ...DEFAULTS, phone: '+6580000000' }
    await flushPromises()

    expect(phone(wrapper).element.value).toBe('8000 0000')
  })
})
