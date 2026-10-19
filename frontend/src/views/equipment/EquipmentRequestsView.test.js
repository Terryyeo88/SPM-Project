import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiGet = vi.fn()
vi.mock('../../lib/api', () => ({ apiGet: (...args) => apiGet(...args) }))
vi.mock('../../components/AppNavBar.vue', () => ({ default: { template: '<div />' } }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ replace: vi.fn() }),
}))

import EquipmentRequestsView from './EquipmentRequestsView.vue'

const REQUEST = {
  id: 'req-1', status: 'confirmed', event_name: 'Gala', items: [{ type: 'projector', quantity: 2 }],
  needed_start: '2026-12-01T09:00:00+08:00', needed_end: '2026-12-01T13:00:00+08:00',
}
const CHANGE = {
  id: 'chg-1', request_id: 'req-1', event_name: 'Gala', type: 'projector', old_quantity: 2, new_quantity: 3,
  status: 'pending',
}

beforeEach(() => {
  apiGet.mockReset()
})

function mountView() {
  return mount(EquipmentRequestsView, { global: { stubs: { RouterLink: RouterLinkStub } } })
}

describe('EquipmentRequestsView quantity changes (IS-43)', () => {
  it('lists the changes waiting for a decision and links to their request', async () => {
    apiGet.mockImplementation((path) => Promise.resolve(path === '/equipment/change-requests' ? [CHANGE] : [REQUEST]))
    const wrapper = mountView()
    await flushPromises()
    const section = wrapper.find('.changes')
    expect(section.text()).toContain('Quantity changes waiting (1)')
    expect(section.text()).toContain('Gala')
    expect(section.text()).toContain('projector: 2 → 3')
    expect(section.findComponent(RouterLinkStub).props('to')).toEqual({
      name: 'equipment-request-details',
      params: { requestId: 'req-1' },
    })
  })

  it('shows no section when nothing is waiting', async () => {
    apiGet.mockImplementation((path) => Promise.resolve(path === '/equipment/change-requests' ? [] : [REQUEST]))
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.find('.changes').exists()).toBe(false)
  })

  it('still shows the queue if the changes cannot be loaded', async () => {
    apiGet.mockImplementation((path) =>
      path === '/equipment/change-requests' ? Promise.reject(new Error('boom')) : Promise.resolve([REQUEST]),
    )
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.find('.changes').exists()).toBe(false)
    expect(wrapper.text()).toContain('Equipment Requests')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })
})
