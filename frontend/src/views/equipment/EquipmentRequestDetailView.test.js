import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiGet = vi.fn()
const apiPost = vi.fn()
vi.mock('../../lib/api', () => ({
  apiGet: (...args) => apiGet(...args),
  apiPost: (...args) => apiPost(...args),
}))
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
    apiPost.mockReset()
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

  // Accept an equipment request and reserve stock (IS-19)
  describe('accepting the request', () => {
    const ENOUGH = { ...CHECK, all_sufficient: true, items: CHECK.items.map((item) => ({ ...item, sufficient: true, shortfall: 0, available: item.requested })) }
    const PENDING = { ...REQUEST, status: 'pending', event_status: 'planning' }

    function serve(request, check) {
      apiGet.mockImplementation((path) => Promise.resolve(path.endsWith('/availability') ? check : request))
    }

    it('offers an enabled Accept button for a pending request that can be covered', async () => {
      serve(PENDING, ENOUGH)
      const wrapper = mountView()
      await flushPromises()
      const button = wrapper.find('.btn-accept')
      expect(button.exists()).toBe(true)
      expect(button.attributes('disabled')).toBeUndefined()
    })

    it('disables Accept and says why when there is not enough equipment', async () => {
      serve(PENDING, CHECK)
      const wrapper = mountView()
      await flushPromises()
      expect(wrapper.find('.btn-accept').attributes('disabled')).toBeDefined()
      expect(wrapper.text()).toContain('We suggest rejecting this request')
    })

    it.each([
      ['an already confirmed request', { ...PENDING, status: 'confirmed' }],
      ['a rejected request', { ...PENDING, status: 'rejected' }],
    ])('offers no decision for %s', async (_label, request) => {
      serve(request, ENOUGH)
      const wrapper = mountView()
      await flushPromises()
      expect(wrapper.find('.btn-accept').exists()).toBe(false)
      expect(wrapper.find('.btn-reject').exists()).toBe(false)
    })

    it('offers only Reject (Accept disabled) for a pending request on a cancelled event', async () => {
      serve({ ...PENDING, event_status: 'cancelled' }, ENOUGH)
      const wrapper = mountView()
      await flushPromises()
      expect(wrapper.find('.btn-accept').attributes('disabled')).toBeDefined()
      expect(wrapper.find('#reject-reason').exists()).toBe(true)
    })

    it('accepts, lists the reserved units and reloads the request', async () => {
      serve(PENDING, ENOUGH)
      apiPost.mockResolvedValue({
        id: 'req-1',
        status: 'confirmed',
        allocated: [
          { equipment_type_id: 't-prj', type: 'projector', quantity: 2, units: [{ id: 'u1', asset_tag: 'PRJ-001' }, { id: 'u2', asset_tag: 'PRJ-002' }] },
        ],
      })
      const wrapper = mountView()
      await flushPromises()
      const loadsBefore = apiGet.mock.calls.length

      await wrapper.find('.btn-accept').trigger('click')
      await flushPromises()

      expect(apiPost).toHaveBeenCalledWith('/equipment/requests/req-1/accept', {})
      expect(wrapper.find('.reserved').text()).toContain('projector × 2: PRJ-001, PRJ-002')
      expect(apiGet.mock.calls.length).toBeGreaterThan(loadsBefore)
    })

    it('shows the server error and keeps the button when accepting fails', async () => {
      serve(PENDING, ENOUGH)
      apiPost.mockRejectedValue(new Error('Some of that equipment was just reserved for another event'))
      const wrapper = mountView()
      await flushPromises()
      await wrapper.find('.btn-accept').trigger('click')
      await flushPromises()
      expect(wrapper.find('[role="alert"]').text()).toContain('just reserved for another event')
      expect(wrapper.find('.btn-accept').exists()).toBe(true)
      expect(wrapper.find('.reserved').exists()).toBe(false)
    })
  })
  // Get warned and reject when requested quantity exceeds availability (IS-41)
  describe('rejecting the request', () => {
    const PENDING = { ...REQUEST, status: 'pending', event_status: 'planning' }

    function serve(request, check) {
      apiGet.mockImplementation((path) => Promise.resolve(path.endsWith('/availability') ? check : request))
    }

    it('suggests rejecting and shows the available quantity when stock is short', async () => {
      serve(PENDING, CHECK)
      const wrapper = mountView()
      await flushPromises()
      expect(wrapper.find('.suggest').text()).toContain('We suggest rejecting this request')
      expect(wrapper.text()).toContain('Requested 2')
      expect(wrapper.text()).toContain('available 1')
    })

    it('does not suggest rejecting when everything is covered', async () => {
      serve(PENDING, { ...CHECK, all_sufficient: true })
      const wrapper = mountView()
      await flushPromises()
      expect(wrapper.find('.suggest').exists()).toBe(false)
    })

    it('keeps Reject disabled until a reason is typed', async () => {
      serve(PENDING, CHECK)
      const wrapper = mountView()
      await flushPromises()
      const button = wrapper.find('.btn-reject')
      expect(button.attributes('disabled')).toBeDefined()
      await wrapper.find('#reject-reason').setValue('   ')
      expect(button.attributes('disabled')).toBeDefined()
      await wrapper.find('#reject-reason').setValue('Only 1 projector free')
      expect(button.attributes('disabled')).toBeUndefined()
    })

    it('posts the trimmed reason and reloads the request', async () => {
      serve(PENDING, CHECK)
      apiPost.mockResolvedValue({ id: 'req-1', status: 'rejected' })
      const wrapper = mountView()
      await flushPromises()
      const loadsBefore = apiGet.mock.calls.length

      await wrapper.find('#reject-reason').setValue('  Only 1 projector free  ')
      await wrapper.find('.btn-reject').trigger('click')
      await flushPromises()

      expect(apiPost).toHaveBeenCalledWith('/equipment/requests/req-1/reject', { reason: 'Only 1 projector free' })
      expect(apiGet.mock.calls.length).toBeGreaterThan(loadsBefore)
    })

    it('shows the server error and keeps the form when rejecting fails', async () => {
      serve(PENDING, CHECK)
      apiPost.mockRejectedValue(new Error('This request is no longer pending'))
      const wrapper = mountView()
      await flushPromises()
      await wrapper.find('#reject-reason').setValue('Not enough stock')
      await wrapper.find('.btn-reject').trigger('click')
      await flushPromises()
      expect(wrapper.find('[role="alert"]').text()).toContain('no longer pending')
      expect(wrapper.find('.btn-reject').exists()).toBe(true)
    })

    it('shows the recorded reason on a rejected request and no decision controls', async () => {
      serve({ ...PENDING, status: 'rejected', rejection_reason: 'Only 1 projector free' }, CHECK)
      const wrapper = mountView()
      await flushPromises()
      expect(wrapper.find('.rejection-reason').text()).toBe('Only 1 projector free')
      expect(wrapper.find('.btn-reject').exists()).toBe(false)
      expect(wrapper.find('.btn-accept').exists()).toBe(false)
    })
  })
})
