import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiGet = vi.fn()
const apiPost = vi.fn()
const push = vi.fn()
vi.mock('../../lib/api', () => ({
  apiGet: (...args) => apiGet(...args),
  apiPost: (...args) => apiPost(...args),
}))
// AppNavBar pulls in the auth store and so the Supabase client, which needs
// real env vars at import time -- irrelevant to this screen, so replaced.
vi.mock('../../components/AppNavBar.vue', () => ({ default: { template: '<div />' } }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { eventId: 'event-1' } }),
  useRouter: () => ({ push }),
}))

import RequestEquipmentView from './RequestEquipmentView.vue'

const EVENT = {
  id: 'event-1',
  name: 'Annual Tech Symposium',
  status: 'planning',
  preferred_start_date: '2026-11-10',
  preferred_start_time: '10:00',
  preferred_end_time: '14:00',
}
const TYPES = [
  { id: 't-mic', name: 'microphone' },
  { id: 't-prj', name: 'projector' },
]

beforeEach(() => {
  apiGet.mockReset()
  apiPost.mockReset()
  push.mockReset()
  apiGet.mockImplementation(async (path) => {
    if (path === '/events/event-1') return EVENT
    if (path === '/equipment/types') return TYPES
    throw new Error(`unexpected GET ${path}`)
  })
})

async function render() {
  const wrapper = mount(RequestEquipmentView, { global: { stubs: { RouterLink: RouterLinkStub } } })
  await flushPromises()
  return wrapper
}

async function fillLine(wrapper, index, { type, quantity, requirements }) {
  if (type !== undefined) await wrapper.findAll('select')[index].setValue(type)
  if (quantity !== undefined) await wrapper.findAll('input[type="number"]')[index].setValue(quantity)
  if (requirements !== undefined) await wrapper.findAll('textarea')[index].setValue(requirements)
}

describe('RequestEquipmentView', () => {
  it('loads the event and the equipment types', async () => {
    const wrapper = await render()
    expect(apiGet).toHaveBeenCalledWith('/events/event-1')
    expect(apiGet).toHaveBeenCalledWith('/equipment/types')
    expect(wrapper.text()).toContain('Annual Tech Symposium')
    expect(wrapper.findAll('option').map((o) => o.text())).toEqual(['Select a type', 'Microphone', 'Projector'])
  })

  it('shows the needed date and time as the session\'s own, not an input', async () => {
    const wrapper = await render()
    expect(wrapper.text()).toContain('2026-11-10')
    expect(wrapper.text()).toContain('10:00 to 14:00')
    expect(wrapper.find('input[type="date"]').exists()).toBe(false)
  })

  it('refuses to show the form unless the event is in planning', async () => {
    apiGet.mockImplementation(async (path) => (path === '/events/event-1' ? { ...EVENT, status: 'approved' } : TYPES))
    const wrapper = await render()
    expect(wrapper.find('form').exists()).toBe(false)
    expect(wrapper.text()).toContain('only be requested while the event is in planning')
  })

  it('shows a load error', async () => {
    apiGet.mockRejectedValue(new Error('Network down'))
    const wrapper = await render()
    expect(wrapper.find('[role="alert"]').text()).toContain('Network down')
  })

  it('blocks submit and shows the error when quantity is missing or zero', async () => {
    const wrapper = await render()
    await fillLine(wrapper, 0, { type: 't-prj' })
    await wrapper.find('form').trigger('submit')
    expect(apiPost).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Enter a whole number of at least 1.')

    await fillLine(wrapper, 0, { quantity: '0' })
    await wrapper.find('form').trigger('submit')
    expect(apiPost).not.toHaveBeenCalled()
  })

  it('blocks submit when no type is chosen', async () => {
    const wrapper = await render()
    await fillLine(wrapper, 0, { quantity: '2' })
    await wrapper.find('form').trigger('submit')
    expect(apiPost).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Choose an equipment type.')
  })

  it('submits every line and returns to the event page', async () => {
    apiPost.mockResolvedValue({ id: 'req-1' })
    const wrapper = await render()
    await fillLine(wrapper, 0, { type: 't-prj', quantity: '2', requirements: ' HDMI ' })
    await wrapper.find('.add').trigger('click')
    await fillLine(wrapper, 1, { type: 't-mic', quantity: '1' })
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/events/event-1/equipment-requests', {
      items: [
        { equipment_type_id: 't-prj', quantity: 2, technical_requirements: 'HDMI' },
        { equipment_type_id: 't-mic', quantity: 1, technical_requirements: null },
      ],
    })
    expect(push).toHaveBeenCalledWith({ name: 'event-details', params: { eventId: 'event-1' } })
  })

  it('does not offer a type already chosen on another line', async () => {
    const wrapper = await render()
    await fillLine(wrapper, 0, { type: 't-prj' })
    await wrapper.find('.add').trigger('click')
    const second = wrapper.findAll('select')[1].findAll('option')
    expect(second.filter((o) => o.text() === 'Projector')[0].attributes('disabled')).toBeDefined()
    expect(second.filter((o) => o.text() === 'Microphone')[0].attributes('disabled')).toBeUndefined()
  })

  it('can remove an added line but never the last one', async () => {
    const wrapper = await render()
    expect(wrapper.text()).not.toContain('Remove item')
    await wrapper.find('.add').trigger('click')
    expect(wrapper.findAll('fieldset')).toHaveLength(2)
    await wrapper.findAll('.link-btn').find((b) => b.text().startsWith('Remove')).trigger('click')
    expect(wrapper.findAll('fieldset')).toHaveLength(1)
    expect(wrapper.text()).not.toContain('Remove item')
  })

  it('stays on the page and shows the server error if the submit fails', async () => {
    apiPost.mockRejectedValue(new Error('Event is not in planning'))
    const wrapper = await render()
    await fillLine(wrapper, 0, { type: 't-prj', quantity: '1' })
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(push).not.toHaveBeenCalled()
    expect(wrapper.find('.message.error').text()).toContain('Event is not in planning')
  })
})
