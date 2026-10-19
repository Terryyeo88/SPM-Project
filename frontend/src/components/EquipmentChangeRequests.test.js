import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../lib/api', () => ({ apiGet: vi.fn(), apiPost: vi.fn() }))

import { apiGet, apiPost } from '../lib/api'
import EquipmentChangeRequests from './EquipmentChangeRequests.vue'

const REQUEST = {
  id: 'req-1',
  status: 'confirmed',
  items: [
    { id: 'item-1', type: 'projector', quantity: 2 },
    { id: 'item-2', type: 'microphone', quantity: 1 },
  ],
}

const PENDING = {
  id: 'chg-1', request_item_id: 'item-1', type: 'projector', old_quantity: 2, new_quantity: 3, status: 'pending',
}
const REJECTED = {
  id: 'chg-0', request_item_id: 'item-2', type: 'microphone', old_quantity: 1, new_quantity: 5,
  status: 'rejected', rejection_reason: 'Only 2 microphones free',
}

beforeEach(() => {
  apiGet.mockReset()
  apiPost.mockReset()
})

async function render(changes = [], props = {}) {
  apiGet.mockResolvedValue(changes)
  const wrapper = mount(EquipmentChangeRequests, { props: { request: REQUEST, ...props } })
  await flushPromises()
  return wrapper
}

describe('EquipmentChangeRequests', () => {
  it("loads the request's change history", async () => {
    await render()
    expect(apiGet).toHaveBeenCalledWith('/equipment/requests/req-1/change-requests')
  })

  it('offers a quantity box and button for each item', async () => {
    const wrapper = await render()
    expect(wrapper.findAll('.change-form')).toHaveLength(2)
    expect(wrapper.text()).toContain('projector × 2')
    expect(wrapper.text()).toContain('microphone × 1')
  })

  it('offers nothing to change once the event is no longer live, but still shows the history', async () => {
    const wrapper = await render([REJECTED], { canChange: false })
    expect(wrapper.find('.change-form').exists()).toBe(false)
    expect(wrapper.find('.change-history').text()).toContain('Reason: Only 2 microphones free')
  })

  it('sends the item and the new quantity, then reloads', async () => {
    apiPost.mockResolvedValue({ id: 'chg-1' })
    const wrapper = await render()
    const loadsBefore = apiGet.mock.calls.length

    await wrapper.find('#change-item-1').setValue('3')
    await wrapper.findAll('.change-form')[0].trigger('submit')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/equipment/requests/req-1/change-requests', { item_id: 'item-1', quantity: 3 })
    expect(apiGet.mock.calls.length).toBeGreaterThan(loadsBefore)
  })

  it.each([
    ['', 'Enter a whole number of at least 1.'],
    ['0', 'Enter a whole number of at least 1.'],
    ['2', 'The quantity is already 2.'],
  ])('blocks %j without calling the server', async (value, message) => {
    const wrapper = await render()
    await wrapper.find('#change-item-1').setValue(value)
    await wrapper.findAll('.change-form')[0].trigger('submit')
    await flushPromises()
    expect(apiPost).not.toHaveBeenCalled()
    expect(wrapper.find('[role="alert"]').text()).toBe(message)
  })

  it('shows the server error against the item', async () => {
    apiPost.mockRejectedValue(new Error('This item already has a change waiting for Technical Support.'))
    const wrapper = await render()
    await wrapper.find('#change-item-1').setValue('4')
    await wrapper.findAll('.change-form')[0].trigger('submit')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('already has a change waiting')
  })

  it('shows a waiting ask instead of a form for that item', async () => {
    const wrapper = await render([PENDING])
    expect(wrapper.find('.change-pending').text()).toContain('Waiting for Technical Support: 2 → 3')
    expect(wrapper.findAll('.change-form')).toHaveLength(1)
  })

  it('shows why an ask was rejected', async () => {
    const wrapper = await render([REJECTED])
    expect(wrapper.find('.change-rejected').text()).toContain('Rejected: microphone: 1 → 5')
    expect(wrapper.find('.change-rejected').text()).toContain('Reason: Only 2 microphones free')
  })

  it('says so if the history cannot be loaded', async () => {
    apiGet.mockRejectedValue(new Error('boom'))
    const wrapper = mount(EquipmentChangeRequests, { props: { request: REQUEST } })
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('boom')
  })
})
