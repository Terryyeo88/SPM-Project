import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiGet = vi.fn()
vi.mock('../../lib/api', () => ({ apiGet: (...args) => apiGet(...args) }))
// AppNavBar pulls in the auth store and so the Supabase client, which needs
// real env vars at import time -- irrelevant to this screen, so replaced.
vi.mock('../../components/AppNavBar.vue', () => ({ default: { template: '<div />' } }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { requestId: 'req-1' } }) }))

import EquipmentRequestDetailView from './EquipmentRequestDetailView.vue'

const REQUEST = {
  id: 'req-1',
  status: 'pending',
  event_name: 'Product Launch',
  needed_start: '2026-12-01T09:00:00+08:00',
  needed_end: '2026-12-01T13:00:00+08:00',
  items: [
    { equipment_type_id: 't-prj', type: 'projector', quantity: 2, technical_requirements: 'Side-room unit too' },
    { equipment_type_id: 't-mic', type: 'microphone', quantity: 2, technical_requirements: null },
  ],
}

const CHECK = {
  all_sufficient: false,
  items: [
    {
      equipment_type_id: 't-prj',
      type: 'projector',
      requested: 2,
      total_units: 3,
      out_of_service: 1,
      reserved_by_others: 1,
      available: 1,
      sufficient: false,
      shortfall: 1,
      available_units: ['PRJ-002'],
      conflicts: [
        {
          asset_tag: 'PRJ-001',
          event_name: 'Gala Dinner',
          reserved_start: '2026-12-01T10:00:00+08:00',
          reserved_end: '2026-12-01T14:00:00+08:00',
        },
      ],
    },
    {
      equipment_type_id: 't-mic',
      type: 'microphone',
      requested: 2,
      total_units: 4,
      out_of_service: 0,
      reserved_by_others: 0,
      available: 4,
      sufficient: true,
      shortfall: 0,
      available_units: ['MIC-001', 'MIC-002', 'MIC-003', 'MIC-004'],
      conflicts: [],
    },
  ],
}

function mountView() {
  return mount(EquipmentRequestDetailView, {
    global: { stubs: { 'router-link': { template: '<a><slot /></a>' } } },
  })
}

describe('EquipmentRequestDetailView', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiGet.mockImplementation((path) =>
      Promise.resolve(path.endsWith('/availability') ? CHECK : REQUEST),
    )
  })

  it('loads the request and its availability check from the two endpoints', async () => {
    mountView()
    await flushPromises()
    expect(apiGet).toHaveBeenCalledWith('/equipment/requests/req-1')
    expect(apiGet).toHaveBeenCalledWith('/equipment/requests/req-1/availability')
  })

  it('shows the event, the required date and time, and the request status', async () => {
    const wrapper = mountView()
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('Product Launch')
    expect(text).toContain('01 Dec 2026, 09:00 – 13:00')
  })

  it('flags the short item and not the sufficient one', async () => {
    const wrapper = mountView()
    await flushPromises()
    const flags = wrapper.findAll('.flag')
    expect(flags).toHaveLength(2)
    expect(flags[0].text()).toContain('Short by 1')
    expect(flags[0].classes()).toContain('flag-insufficient')
    expect(flags[1].text()).toContain('Available')
    expect(flags[1].classes()).toContain('flag-sufficient')
    expect(wrapper.find('.banner').text()).toBe('1 item flagged: not enough equipment available.')
  })

  it('shows which unit is held, for which event and when, so the subtraction can be checked', async () => {
    const wrapper = mountView()
    await flushPromises()
    const conflict = wrapper.find('.conflicts').text()
    expect(conflict).toContain('PRJ-001')
    expect(conflict).toContain('Gala Dinner')
    expect(conflict).toContain('01 Dec 2026, 10:00 – 14:00')
  })

  it('shows the requested technical requirements and the free units', async () => {
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.text()).toContain('Technical requirements: Side-room unit too')
    expect(wrapper.text()).toContain('Free units: PRJ-002')
  })

  it('shows an error instead of a half-rendered page when the load fails', async () => {
    apiGet.mockRejectedValue(new Error('boom'))
    const wrapper = mountView()
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('boom')
    expect(wrapper.find('.flag').exists()).toBe(false)
  })
})
