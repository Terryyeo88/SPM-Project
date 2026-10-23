import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const auth = { roles: ['venue_staff'] }
const route = { query: {} }

vi.mock('../../lib/api', () => ({ apiGet: vi.fn() }))
vi.mock('../../stores/auth', () => ({ useAuthStore: () => auth }))
vi.mock('vue-router', () => ({ useRoute: () => route }))
vi.mock('../../components/AppNavBar.vue', () => ({ default: { template: '<nav />' } }))

import { apiGet } from '../../lib/api'
import VenueCatalogueView from './VenueCatalogueView.vue'

const ACTIVE = [{ id: 'venue-1', name: 'Grand Ballroom', location: 'Main', capacity: 300, status: 'available' }]
const DELETED = [{ ...ACTIVE[0], id: 'venue-2', name: 'Old Hall', deleted_at: '2026-10-23T10:00:00+00:00' }]

beforeEach(() => {
  apiGet.mockReset()
  auth.roles = ['venue_staff']
  route.query = {}
  apiGet.mockImplementation((path) => Promise.resolve(path === '/venues/deleted' ? DELETED : ACTIVE))
})

async function render() {
  const wrapper = mount(VenueCatalogueView, { global: { stubs: { RouterLink: RouterLinkStub } } })
  await flushPromises()
  return wrapper
}

describe('VenueCatalogueView -- IS-61', () => {
  it('lets Venue Staff list deleted venues waiting to be permanently deleted', async () => {
    const wrapper = await render()

    await wrapper.find('[data-test="deleted-tab"]').trigger('click')
    await flushPromises()

    expect(apiGet).toHaveBeenLastCalledWith('/venues/deleted')
    expect(wrapper.text()).toContain('Old Hall')
    expect(wrapper.find('.status-deleted').exists()).toBe(true)
  })

  it('shows coordinators no Deleted tab and no Add venue', async () => {
    auth.roles = ['event_coordinator']
    const wrapper = await render()

    expect(wrapper.find('[data-test="deleted-tab"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Add venue')
  })

  it('shows what a delete did', async () => {
    route.query = { deleted: 'Old Hall was permanently deleted. Past bookings still show its name.' }
    const wrapper = await render()

    expect(wrapper.find('[role="status"]').text()).toContain('Old Hall was permanently deleted')
  })
})
