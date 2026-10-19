import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../lib/api', () => ({ apiGet: vi.fn() }))

import { apiGet } from '../lib/api'
import EquipmentBookingStatus from './EquipmentBookingStatus.vue'

const confirmedRequest = {
  id: 'req-1',
  status: 'confirmed',
  needed_start: '2026-11-10T10:00:00+08:00',
  needed_end: '2026-11-10T14:00:00+08:00',
  items: [
    { type: 'projector', quantity: 1 },
    { type: 'microphone', quantity: 2 },
  ],
  total_quantity: 3,
  allocated: [
    { equipment_type_id: 't-mic', type: 'microphone', quantity: 2, units: [
      { id: 'u-mic-1', asset_tag: 'MIC-001' },
      { id: 'u-mic-2', asset_tag: 'MIC-002' },
    ] },
    { equipment_type_id: 't-prj', type: 'projector', quantity: 1, units: [{ id: 'u-prj-1', asset_tag: 'PRJ-001' }] },
  ],
}

const pendingRequest = {
  id: 'req-2',
  status: 'pending',
  needed_start: '2026-11-10T10:00:00+08:00',
  needed_end: '2026-11-10T14:00:00+08:00',
  items: [{ type: 'screen', quantity: 1 }],
  total_quantity: 1,
  allocated: [],
}

// Braces matter: a function returned from beforeEach is run as teardown,
// and apiGet IS a function -- it would be called once more after each test.
beforeEach(() => {
  apiGet.mockReset()
})

async function render(event, requests) {
  apiGet.mockResolvedValue(requests)
  const wrapper = mount(EquipmentBookingStatus, { props: { event }, global: { stubs: { RouterLink: RouterLinkStub } } })
  await flushPromises()
  return wrapper
}

describe('EquipmentBookingStatus', () => {
  it("loads this event's equipment requests", async () => {
    await render({ id: 'session-1', status: 'planning' }, [])
    expect(apiGet).toHaveBeenCalledWith('/events/session-1/equipment-requests')
  })

  it('says so when nothing has been requested', async () => {
    const wrapper = await render({ id: 'session-1', status: 'planning' }, [])
    expect(wrapper.text()).toContain('No equipment has been requested')
    expect(wrapper.find('table').exists()).toBe(false)
  })

  it('shows each request with its items, total quantity and status', async () => {
    const wrapper = await render({ id: 'session-1', status: 'planning' }, [pendingRequest, confirmedRequest])
    const rows = wrapper.findAll('tbody tr')
    expect(rows).toHaveLength(2)
    expect(rows[0].text()).toContain('1 × screen')
    expect(rows[0].find('.status').text()).toBe('Pending')
    expect(rows[1].text()).toContain('1 × projector, 2 × microphone')
    expect(rows[1].findAll('td')[1].text()).toBe('3')
    expect(rows[1].find('.status').text()).toBe('Confirmed')
  })

  it('shows why a request was rejected, and no reason line for other requests', async () => {
    const rejected = { ...pendingRequest, id: 'req-3', status: 'rejected', rejection_reason: 'Only 1 screen free that day' }
    const wrapper = await render({ id: 'session-1', status: 'planning' }, [pendingRequest, rejected])
    const rows = wrapper.findAll('tbody tr')
    expect(rows[0].find('.rejection').exists()).toBe(false)
    expect(rows[1].find('.status').text()).toBe('Rejected')
    expect(rows[1].find('.rejection').text()).toBe('Reason: Only 1 screen free that day')
  })

  it('lists the reserved units by type, with quantity and asset tags, once confirmed', async () => {
    const wrapper = await render({ id: 'session-1', status: 'planning' }, [confirmedRequest])
    const groups = wrapper.findAll('.group')
    expect(groups.map((g) => g.find('.group-type').text())).toEqual(['Microphone', 'Projector'])
    expect(groups[0].find('.group-qty').text()).toBe('× 2')
    expect(groups[0].findAll('.unit').map((u) => u.text())).toEqual(['MIC-001', 'MIC-002'])
    expect(groups[1].findAll('.unit').map((u) => u.text())).toEqual(['PRJ-001'])
  })

  it('shows no allocated equipment while requests are only pending', async () => {
    const wrapper = await render({ id: 'session-1', status: 'planning' }, [pendingRequest])
    expect(wrapper.find('.allocated').exists()).toBe(false)
  })

  it('marks confirmed requests released and lists no units when the event is cancelled', async () => {
    const wrapper = await render({ id: 'session-1', status: 'cancelled' }, [confirmedRequest])
    expect(wrapper.find('tbody .status').text()).toBe('Released')
    expect(wrapper.find('.allocated').exists()).toBe(false)
    expect(wrapper.text()).toContain('reserved equipment has been released')
  })

  it('shows an error if the requests cannot be loaded', async () => {
    apiGet.mockRejectedValue(new Error('Network down'))
    const wrapper = mount(EquipmentBookingStatus, {
      props: { event: { id: 'session-1', status: 'planning' } },
      global: { stubs: { RouterLink: RouterLinkStub } },
    })
    await flushPromises()
    expect(wrapper.find('[role="alert"]').text()).toContain('Network down')
  })

  // Record Equipment Request for Event (IS-17)
  describe('requesting equipment', () => {
    it('offers Request Equipment while the event is in planning', async () => {
      const wrapper = await render({ id: 'session-1', status: 'planning' }, [])
      const link = wrapper.findComponent(RouterLinkStub)
      expect(link.exists()).toBe(true)
      expect(link.text()).toBe('Request Equipment')
      expect(link.props('to')).toEqual({ name: 'request-equipment', params: { eventId: 'session-1' } })
    })

    it('says Request more equipment once something has already been requested', async () => {
      const wrapper = await render({ id: 'session-1', status: 'planning' }, [pendingRequest])
      expect(wrapper.findComponent(RouterLinkStub).text()).toBe('Request more equipment')
    })

    it('tells an approved event to start planning first, with no request link', async () => {
      const wrapper = await render({ id: 'session-1', status: 'approved' }, [])
      expect(wrapper.findComponent(RouterLinkStub).exists()).toBe(false)
      expect(wrapper.text()).toContain('Start planning')
    })

    it.each(['draft', 'under_review', 'safety_review', 'confirmed', 'cancelled'])(
      'offers no request link when the event is %s',
      async (status) => {
        const wrapper = await render({ id: 'session-1', status }, [])
        expect(wrapper.findComponent(RouterLinkStub).exists()).toBe(false)
      },
    )
  })
})
