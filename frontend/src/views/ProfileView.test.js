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

const UNSET = {
  id: 'u1', name: 'Ethan Koh', email: 'ethan@example.com', roles: ['attendee'],
  phone: null, organisation: null, notify_email: null, notify_sms: null,
}

async function mountView(profile = UNSET) {
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
const organisation = (wrapper) => wrapper.find('#profile-organisation')
const email = (wrapper) => wrapper.find('#profile-notify-email')
const sms = (wrapper) => wrapper.find('#profile-notify-sms')

async function save(wrapper) {
  await wrapper.find('form.contact').trigger('submit')
  await flushPromises()
}

describe('ProfileView contact details and preferences (IS-68)', () => {
  beforeEach(() => {
    // Like PATCH /me/profile: the four fields as saved, nothing else.
    apiPatch.mockReset().mockImplementation((path, body) => Promise.resolve({
      phone: null, organisation: null, notify_email: null, notify_sms: null, ...body,
    }))
  })

  it('shows the three fields from the wireframe, with name, email and roles still read-only', async () => {
    const { wrapper } = await mountView()

    expect(wrapper.find('label[for="profile-phone"]').text()).toBe('Phone Number')
    expect(wrapper.find('label[for="profile-organisation"]').text()).toBe('Organisation (optional)')
    expect(wrapper.find('legend').text()).toBe('Communication Preferences')
    expect(wrapper.text()).toContain('Email notifications')
    expect(wrapper.text()).toContain('SMS notifications')
    expect(wrapper.find('dl').text()).toContain('Ethan Koh')
    expect(wrapper.find('dl').text()).toContain('ethan@example.com')
    expect(wrapper.find('input#profile-name').exists()).toBe(false)
  })

  it('starts blank, with the register form defaults, when nothing is saved', async () => {
    const { wrapper } = await mountView()

    expect(phone(wrapper).element.value).toBe('')
    expect(organisation(wrapper).element.value).toBe('')
    expect([email(wrapper).element.checked, sms(wrapper).element.checked]).toEqual([true, false])
  })

  it('starts from what the profile has saved', async () => {
    const { wrapper } = await mountView({
      ...UNSET, phone: '9123 4567', organisation: 'SMU', notify_email: false, notify_sms: true,
    })

    expect(phone(wrapper).element.value).toBe('9123 4567')
    expect(organisation(wrapper).element.value).toBe('SMU')
    expect([email(wrapper).element.checked, sms(wrapper).element.checked]).toEqual([false, true])
  })

  it('saves all three to PATCH /me/profile and keeps the store in step', async () => {
    const { wrapper, auth } = await mountView()

    await phone(wrapper).setValue('+65 9123 4567')
    await organisation(wrapper).setValue('Singapore Management University')
    await email(wrapper).setValue(false)
    await sms(wrapper).setValue(true)
    await save(wrapper)

    expect(apiPatch).toHaveBeenCalledWith('/me/profile', {
      phone: '+65 9123 4567', organisation: 'Singapore Management University', notify_email: false, notify_sms: true,
    })
    expect(wrapper.find('[role="status"]').text()).toBe('Saved.')
    expect(auth.profile).toMatchObject({
      id: 'u1', name: 'Ethan Koh', phone: '+65 9123 4567', organisation: 'Singapore Management University',
      notify_email: false, notify_sms: true,
    })
  })

  it('saves with the optional ones blank', async () => {
    const { wrapper } = await mountView()

    await save(wrapper)

    // Nothing typed and no preference touched: phone and organisation go
    // as null, and never-chosen preferences stay unsent (still null).
    expect(apiPatch).toHaveBeenCalledWith('/me/profile', { phone: null, organisation: null })
    expect(wrapper.find('[role="status"]').text()).toBe('Saved.')
  })

  it('clearing saved values sends them as null', async () => {
    const { wrapper, auth } = await mountView({
      ...UNSET, phone: '9123 4567', organisation: 'SMU', notify_email: true, notify_sms: false,
    })

    await phone(wrapper).setValue('   ')
    await organisation(wrapper).setValue('')
    await save(wrapper)

    expect(apiPatch).toHaveBeenCalledWith('/me/profile', {
      phone: null, organisation: null, notify_email: true, notify_sms: false,
    })
    expect(auth.profile.phone).toBeNull()
    expect(auth.profile.organisation).toBeNull()
  })

  it('a phone that is not a phone number is shown as an error and not saved', async () => {
    const { wrapper } = await mountView()

    await phone(wrapper).setValue('call me')
    await save(wrapper)

    expect(apiPatch).not.toHaveBeenCalled()
    expect(wrapper.find('.field-error').text()).toMatch('valid phone number')
  })

  it('never sends id or email', async () => {
    const { wrapper } = await mountView()

    await phone(wrapper).setValue('9123 4567')
    await sms(wrapper).setValue(true)
    await save(wrapper)

    const body = apiPatch.mock.calls[0][1]
    expect(body).not.toHaveProperty('id')
    expect(body).not.toHaveProperty('email')
  })

  it('shows the error when saving fails, and keeps what was typed', async () => {
    apiPatch.mockRejectedValue(new Error('Enter a valid phone number, e.g. 9123 4567 or +65 9123 4567.'))
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

    auth.profile = { ...UNSET, phone: '8000 0000' }
    await flushPromises()

    expect(phone(wrapper).element.value).toBe('8000 0000')
  })
})
