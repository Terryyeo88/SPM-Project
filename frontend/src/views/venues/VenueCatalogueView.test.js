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

beforeEach(() => {
  apiGet.mockReset()
  auth.roles = ['venue_staff']
  route.query = {}
  apiGet.mockResolvedValue(ACTIVE)
})

async function render() {
  const wrapper = mount(VenueCatalogueView, { global: { stubs: { RouterLink: RouterLinkStub } } })
  await flushPromises()
  return wrapper
}

describe('VenueCatalogueView -- IS-61', () => {
  it('lists the catalogue, with no separate list of deleted venues (a delete removes the record)', async () => {
    const wrapper = await render()

    expect(apiGet).toHaveBeenCalledWith('/venues')
    expect(wrapper.text()).toContain('Grand Ballroom')
    expect(wrapper.text()).not.toContain('Deleted')
  })

  it('offers Venue Staff Add venue, and coordinators not', async () => {
    expect((await render()).text()).toContain('Add venue')

    auth.roles = ['event_coordinator']
    expect((await render()).text()).not.toContain('Add venue')
  })

  it('shows what a delete did', async () => {
    route.query = { deleted: 'Old Hall was deleted. No ongoing events had booked it.' }
    const wrapper = await render()

    expect(wrapper.find('[role="status"]').text()).toContain('Old Hall was deleted')
  })
})
