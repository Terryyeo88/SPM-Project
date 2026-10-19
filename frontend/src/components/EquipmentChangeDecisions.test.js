import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../lib/api', () => ({ apiGet: vi.fn(), apiPost: vi.fn() }))

import { apiGet, apiPost } from '../lib/api'
import EquipmentChangeDecisions from './EquipmentChangeDecisions.vue'

const OK = {
  id: 'chg-1', type: 'projector', old_quantity: 2, new_quantity: 3, status: 'pending',
  check: { current: 2, requested: 3, available: 3, accommodated: true, shortfall: 0 },
}
const SHORT = {
  id: 'chg-2', type: 'projector', old_quantity: 2, new_quantity: 5, status: 'pending',
  check: { current: 2, requested: 5, available: 3, accommodated: false, shortfall: 2 },
}

beforeEach(() => {
  apiGet.mockReset()
  apiPost.mockReset()
})

async function render(changes, props = {}) {
  apiGet.mockResolvedValue(changes)
  const wrapper = mount(EquipmentChangeDecisions, { props: { requestId: 'req-1', ...props } })
  await flushPromises()
  return wrapper
}

describe('EquipmentChangeDecisions', () => {
  it('renders nothing when there are no changes', async () => {
    const wrapper = await render([])
    expect(wrapper.find('section').exists()).toBe(false)
  })

  it('shows the recalculated availability and enables Accept when it can be accommodated', async () => {
    const wrapper = await render([OK])
    expect(wrapper.find('.change-head').text()).toContain('from 2 to 3')
    expect(wrapper.find('.change-check').text()).toContain('3 projector available')
    expect(wrapper.find('.change-check').text()).toContain('can be accommodated')
    expect(wrapper.find('.btn-accept-change').attributes('disabled')).toBeUndefined()
  })

  it('disables Accept, shows the shortfall and suggests rejecting when it cannot be accommodated', async () => {
    const wrapper = await render([SHORT])
    expect(wrapper.find('.change-check').text()).toContain('short by 2')
    expect(wrapper.find('.change-check').text()).toContain('We suggest rejecting')
    expect(wrapper.find('.btn-accept-change').attributes('disabled')).toBeDefined()
  })

  it('only allows rejecting once the event is no longer live', async () => {
    const wrapper = await render([OK], { eventLive: false })
    expect(wrapper.find('.btn-accept-change').attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('can only be rejected')
  })

  it('accepts, reloads and tells the page to reload', async () => {
    apiPost.mockResolvedValue({ status: 'accepted' })
    const wrapper = await render([OK])
    const loadsBefore = apiGet.mock.calls.length
    await wrapper.find('.btn-accept-change').trigger('click')
    await flushPromises()
    expect(apiPost).toHaveBeenCalledWith('/equipment/change-requests/chg-1/accept', {})
    expect(apiGet.mock.calls.length).toBeGreaterThan(loadsBefore)
    expect(wrapper.emitted('decided')).toHaveLength(1)
  })

  it('keeps Reject disabled until a reason is typed, then sends it trimmed', async () => {
    apiPost.mockResolvedValue({ status: 'rejected' })
    const wrapper = await render([SHORT])
    const button = wrapper.find('.btn-reject-change')
    expect(button.attributes('disabled')).toBeDefined()
    await wrapper.find('#change-reason-chg-2').setValue('   ')
    expect(button.attributes('disabled')).toBeDefined()
    await wrapper.find('#change-reason-chg-2').setValue('  Only 3 free  ')
    await button.trigger('click')
    await flushPromises()
    expect(apiPost).toHaveBeenCalledWith('/equipment/change-requests/chg-2/reject', { reason: 'Only 3 free' })
    expect(wrapper.emitted('decided')).toHaveLength(1)
  })

  it('shows the server error and does not tell the page it was decided', async () => {
    apiPost.mockRejectedValue(new Error('no longer pending'))
    const wrapper = await render([OK])
    await wrapper.find('.btn-accept-change').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('no longer pending')
    expect(wrapper.emitted('decided')).toBeUndefined()
  })

  it('lists decided changes with the rejection reason', async () => {
    const wrapper = await render([
      { id: 'a', type: 'projector', old_quantity: 1, new_quantity: 2, status: 'accepted' },
      { id: 'b', type: 'screen', old_quantity: 1, new_quantity: 4, status: 'rejected', rejection_reason: 'None free' },
    ])
    const text = wrapper.find('.history').text()
    expect(text).toContain('Accepted: projector: 1 → 2')
    expect(text).toContain('Rejected: screen: 1 → 4')
    expect(text).toContain('Reason: None free')
  })
})
