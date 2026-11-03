import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const apiGet = vi.fn()
const apiPost = vi.fn()
vi.mock('../lib/api', () => ({
  apiGet: (...args) => apiGet(...args),
  apiPost: (...args) => apiPost(...args),
}))
vi.mock('../lib/supabaseClient', () => ({ supabase: { auth: {} } }))

import AppNavBar from './AppNavBar.vue'
import { ROLES } from '../lib/roles'
import { useAuthStore } from '../stores/auth'
import { useNotificationStore } from '../stores/notifications'

const stub = { template: '<div />' }

async function mountNav({ roles = [ROLES.EVENT_COORDINATOR], loggedIn = true } = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const auth = useAuthStore()
  if (loggedIn) {
    auth.session = { access_token: 'tok' }
    auth.profile = { id: 'u1', name: 'Ann', email: 'a@b.com', roles }
  }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'dashboard', component: stub },
      { path: '/profile', name: 'profile', component: stub },
      { path: '/notifications', name: 'notifications', component: stub },
      { path: '/events', name: 'events', component: stub },
      { path: '/venues', name: 'venues', component: stub },
      { path: '/venues/bookings', name: 'venue-booking-queue', component: stub },
      { path: '/room-layouts', name: 'room-layouts', component: stub },
      { path: '/equipment', name: 'equipment', component: stub },
      { path: '/equipment/requests', name: 'equipment-requests', component: stub },
    ],
  })
  router.push('/')
  await router.isReady()
  const wrapper = mount(AppNavBar, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return wrapper
}

const bell = (wrapper) => wrapper.find('[data-test="notification-bell"]')

describe('AppNavBar notifications bell (IS-69)', () => {
  beforeEach(() => {
    apiGet.mockReset().mockResolvedValue({ unread_count: 3 })
    apiPost.mockReset()
  })
  afterEach(() => vi.restoreAllMocks())

  it('shows the unread count from GET /notifications/unread-count, linking to the notifications page', async () => {
    const wrapper = await mountNav()

    expect(apiGet).toHaveBeenCalledWith('/notifications/unread-count')
    expect(bell(wrapper).find('[data-test="unread-count"]').text()).toBe('3')
    expect(bell(wrapper).attributes('href')).toBe('/notifications')
    expect(bell(wrapper).attributes('aria-label')).toBe('Notifications (3 unread)')
  })

  it.each(Object.values(ROLES))('is there for %s', async (role) => {
    const wrapper = await mountNav({ roles: [role] })

    expect(bell(wrapper).exists()).toBe(true)
  })

  it('shows no count when nothing is unread', async () => {
    apiGet.mockResolvedValue({ unread_count: 0 })
    const wrapper = await mountNav()

    expect(bell(wrapper).exists()).toBe(true)
    expect(bell(wrapper).find('[data-test="unread-count"]').exists()).toBe(false)
    expect(bell(wrapper).attributes('aria-label')).toBe('Notifications')
  })

  it('caps a large count at 99+', async () => {
    apiGet.mockResolvedValue({ unread_count: 140 })
    const wrapper = await mountNav()

    expect(bell(wrapper).find('[data-test="unread-count"]').text()).toBe('99+')
  })

  it('follows the shared count when the notifications page updates it', async () => {
    const wrapper = await mountNav()

    useNotificationStore().setUnreadCount(1)
    await flushPromises()

    expect(bell(wrapper).find('[data-test="unread-count"]').text()).toBe('1')
  })

  it('a failed fetch leaves the bell without a count rather than breaking the nav', async () => {
    apiGet.mockRejectedValue(new Error('Network down'))
    const wrapper = await mountNav()

    expect(bell(wrapper).exists()).toBe(true)
    expect(bell(wrapper).find('[data-test="unread-count"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('ConnectSphere')
  })

  it('is not shown, and nothing is fetched, when signed out', async () => {
    const wrapper = await mountNav({ loggedIn: false })

    expect(bell(wrapper).exists()).toBe(false)
    expect(apiGet).not.toHaveBeenCalled()
  })
})
