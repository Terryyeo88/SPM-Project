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
// AppNavBar pulls in the auth store and the Supabase client -- irrelevant here.
vi.mock('../components/AppNavBar.vue', () => ({ default: { template: '<div />' } }))
vi.mock('../lib/supabaseClient', () => ({ supabase: { auth: {} } }))

import NotificationsView from './NotificationsView.vue'
import { useAuthStore } from '../stores/auth'
import { useNotificationStore } from '../stores/notifications'

const READ_AT = '2026-10-29T02:00:00Z'
const NOTIFICATIONS = [
  { id: 'n-3', message: 'You were assigned Annual Tech Symposium', read_at: null, created_at: '2026-10-29T03:00:00Z', entity_type: 'event', entity_id: 'e-1' },
  { id: 'n-2', message: 'Your venue booking was released', read_at: null, created_at: '2026-10-29T02:00:00Z', entity_type: 'venue_booking', entity_id: 'b-1' },
  { id: 'n-1', message: 'An older one', read_at: '2026-10-28T01:00:00Z', created_at: '2026-10-28T00:00:00Z', entity_type: null, entity_id: null },
]

let pinia

async function mountView({ notifications = NOTIFICATIONS, unread = 2, roles = ['event_coordinator'], failWith = null } = {}) {
  if (failWith) apiGet.mockRejectedValue(failWith)
  else apiGet.mockResolvedValue({ notifications, unread_count: unread })
  pinia = createPinia()
  setActivePinia(pinia)
  useAuthStore().profile = { id: 'u1', name: 'Ann', email: 'a@b.com', roles }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', name: 'dashboard', component: { template: '<div />' } },
      { path: '/notifications', name: 'notifications', component: NotificationsView },
      { path: '/events/:eventId', name: 'event-details', component: { template: '<div />' } },
      { path: '/safety-reviews/:reviewId', name: 'safety-review', component: { template: '<div />' } },
    ],
  })
  router.push('/notifications')
  await router.isReady()
  const wrapper = mount(NotificationsView, { global: { plugins: [pinia, router] } })
  await flushPromises()
  return wrapper
}

const rows = (wrapper) => wrapper.findAll('[data-test="notification"]')
const summary = (wrapper) => wrapper.find('[data-test="unread-summary"]').text()

describe('NotificationsView', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
  })
  afterEach(() => vi.restoreAllMocks())

  it('lists the notifications in the order the backend sent them (newest first), unread ones marked', async () => {
    const wrapper = await mountView()

    expect(apiGet).toHaveBeenCalledWith('/notifications')
    expect(rows(wrapper).map((row) => row.find('[data-test="message"]').text())).toEqual(NOTIFICATIONS.map((n) => n.message))
    expect(rows(wrapper).map((row) => row.classes('unread'))).toEqual([true, true, false])
  })

  it('renders the unread count from the response', async () => {
    const wrapper = await mountView()

    expect(summary(wrapper)).toBe('2 unread')
    expect(useNotificationStore().unreadCount).toBe(2)
  })

  it('clicking an unread one marks it read and takes the count from the response, without refetching', async () => {
    apiPost.mockResolvedValue({ notification: { ...NOTIFICATIONS[1], read_at: READ_AT }, unread_count: 1 })
    const wrapper = await mountView()

    await rows(wrapper)[1].find('[data-test="message"]').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/notifications/n-2/read', {})
    expect(apiGet).toHaveBeenCalledTimes(1)
    expect(rows(wrapper)[1].classes('unread')).toBe(false)
    expect(summary(wrapper)).toBe('1 unread')
    expect(useNotificationStore().unreadCount).toBe(1)
  })

  it('a read one is plain text and clicking it sends nothing', async () => {
    const wrapper = await mountView()

    const message = rows(wrapper)[2].find('[data-test="message"]')
    expect(message.element.tagName).toBe('P')
    await message.trigger('click')
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('"Mark all as read" marks every one read and takes the count from the response', async () => {
    apiPost.mockResolvedValue({ marked_read: 2, unread_count: 0 })
    const wrapper = await mountView()

    await wrapper.find('[data-test="mark-all"]').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/notifications/read-all', {})
    expect(apiGet).toHaveBeenCalledTimes(1)
    expect(rows(wrapper).some((row) => row.classes('unread'))).toBe(false)
    expect(summary(wrapper)).toBe('0 unread')
    expect(wrapper.find('[data-test="mark-all"]').attributes('disabled')).toBeDefined()
  })

  it('shows an empty state when there are none', async () => {
    const wrapper = await mountView({ notifications: [], unread: 0 })

    expect(wrapper.find('[data-test="empty"]').text()).toBe('You have no notifications yet.')
    expect(rows(wrapper)).toHaveLength(0)
    expect(wrapper.find('[data-test="mark-all"]').exists()).toBe(false)
  })

  it('links a notification to its event when that page exists', async () => {
    const wrapper = await mountView()

    const link = rows(wrapper)[0].find('[data-test="entity-link"]')
    expect(link.attributes('href')).toBe('/events/e-1')
    expect(link.text()).toBe('View event')
  })

  it('a notification whose entity has no page is plain text, not a dead link', async () => {
    const wrapper = await mountView()

    const row = rows(wrapper)[1]
    expect(row.text()).toContain('Your venue booking was released')
    expect(row.find('a').exists()).toBe(false)
  })

  it('no link when the caller cannot reach the page', async () => {
    const wrapper = await mountView({ roles: ['attendee'] })

    expect(rows(wrapper)[0].find('a').exists()).toBe(false)
  })

  it('following a link marks the notification read too', async () => {
    apiPost.mockResolvedValue({ notification: { ...NOTIFICATIONS[0], read_at: READ_AT }, unread_count: 1 })
    const wrapper = await mountView()

    await rows(wrapper)[0].find('[data-test="entity-link"]').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/notifications/n-3/read', {})
    expect(useNotificationStore().unreadCount).toBe(1)
  })

  it('says so when the list cannot load', async () => {
    const wrapper = await mountView({ failWith: new Error('Network down') })

    expect(wrapper.find('[role="alert"]').text()).toContain('Network down')
  })

  it('keeps the item unread and says so when marking it read fails', async () => {
    apiPost.mockRejectedValue(new Error('Not found'))
    const wrapper = await mountView()

    await rows(wrapper)[1].find('[data-test="message"]').trigger('click')
    await flushPromises()

    expect(rows(wrapper)[1].classes('unread')).toBe(true)
    expect(summary(wrapper)).toBe('2 unread')
    expect(wrapper.find('[role="alert"]').text()).toContain('Not found')
  })
})
