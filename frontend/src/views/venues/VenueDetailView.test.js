import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const auth = { roles: ['venue_staff'] }
const route = { params: { venueId: 'venue-1' }, query: {} }
const push = vi.fn()

vi.mock('../../lib/api', () => ({ apiGet: vi.fn(), apiPost: vi.fn(), apiDelete: vi.fn() }))
vi.mock('../../stores/auth', () => ({ useAuthStore: () => auth }))
vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => ({ push }) }))
vi.mock('../../components/AppNavBar.vue', () => ({ default: { template: '<nav />' } }))

import { apiDelete, apiGet } from '../../lib/api'
import VenueDetailView from './VenueDetailView.vue'

const venue = {
  id: 'venue-1',
  name: 'Grand Ballroom',
  location: 'Main Building, Level 3',
  capacity: 300,
  facilities: [],
  accessibility_features: [],
  supported_layouts: ['theatre'],
  status: 'available',
  setup_minutes: 30,
  turnaround_minutes: 30,
  operating_hours_start: null,
  operating_hours_end: null,
  deleted_at: null,
}

beforeEach(() => {
  apiGet.mockReset()
  apiDelete.mockReset()
  push.mockReset()
  auth.roles = ['venue_staff']
  route.query = {}
  apiGet.mockResolvedValue(venue)
})

async function render() {
  const wrapper = mount(VenueDetailView, { global: { stubs: { RouterLink: RouterLinkStub } } })
  await flushPromises()
  return wrapper
}

function button(wrapper, label) {
  return wrapper.findAll('button').find((b) => b.text() === label)
}

describe('VenueDetailView -- IS-61 Venue Staff actions', () => {
  it('offers Venue Staff an edit link (AC2) and a delete button (AC3)', async () => {
    const wrapper = await render()

    const links = wrapper.findAllComponents(RouterLinkStub).map((link) => link.props('to'))
    expect(links).toContainEqual({ name: 'venue-edit', params: { venueId: 'venue-1' } })
    expect(button(wrapper, 'Delete venue')).toBeTruthy()
  })

  it('offers coordinators neither', async () => {
    auth.roles = ['event_coordinator']
    const wrapper = await render()

    expect(wrapper.find('[data-test="staff-actions"]').exists()).toBe(false)
  })

  it('asks for confirmation, warning that ongoing events lose their booking', async () => {
    const wrapper = await render()

    await button(wrapper, 'Delete venue').trigger('click')

    const panel = wrapper.find('[data-test="delete-panel"]')
    expect(panel.text()).toContain('Ongoing events that have booked it will lose their booking')
    expect(panel.text()).toContain('Confirmed events go back to planning')
    expect(apiDelete).not.toHaveBeenCalled()
  })

  it('deletes on confirmation and returns to the catalogue saying what happened', async () => {
    apiDelete.mockResolvedValue({ venue, released_bookings: [{}], returned_to_planning: ['e-1'] })
    const wrapper = await render()

    await button(wrapper, 'Delete venue').trigger('click')
    await wrapper.find('[data-test="delete-panel"] .danger-solid').trigger('click')
    await flushPromises()

    expect(apiDelete).toHaveBeenCalledWith('/venues/venue-1')
    const [[target]] = push.mock.calls
    expect(target.name).toBe('venues')
    expect(target.query.deleted).toContain('1 booking for ongoing events was released')
  })

  it('shows a refused delete and stays on the page', async () => {
    apiDelete.mockRejectedValue(new Error('This venue has already been deleted from the catalogue.'))
    const wrapper = await render()

    await button(wrapper, 'Delete venue').trigger('click')
    await wrapper.find('[data-test="delete-panel"] .danger-solid').trigger('click')
    await flushPromises()

    expect(wrapper.find('[role="alert"]').text()).toContain('already been deleted')
    expect(push).not.toHaveBeenCalled()
  })

  it('marks a deleted venue opened by link and hides the staff actions', async () => {
    apiGet.mockResolvedValue({ ...venue, deleted_at: '2026-10-23T10:00:00+00:00' })
    const wrapper = await render()

    expect(wrapper.find('[data-test="venue-deleted"]').exists()).toBe(true)
    expect(wrapper.find('[data-test="staff-actions"]').exists()).toBe(false)
  })

  it('confirms a save after adding or editing', async () => {
    route.query = { saved: 'updated' }
    const wrapper = await render()

    expect(wrapper.find('[role="status"]').text()).toBe('Venue details saved.')
  })
})

describe('VenueDetailView -- IS-61 permanent delete', () => {
  const deleted = { ...venue, deleted_at: '2026-10-23T10:00:00+00:00' }

  it('offers Venue Staff a permanent delete only once the venue is deleted', async () => {
    const active = await render()
    expect(active.find('[data-test="permanent-actions"]').exists()).toBe(false)

    apiGet.mockResolvedValue(deleted)
    const deletedPage = await render()
    expect(button(deletedPage, 'Delete permanently')).toBeTruthy()
  })

  it('offers coordinators no permanent delete', async () => {
    auth.roles = ['event_coordinator']
    apiGet.mockResolvedValue(deleted)
    const wrapper = await render()

    expect(wrapper.find('[data-test="permanent-actions"]').exists()).toBe(false)
  })

  it('asks for confirmation, saying past bookings keep the name and it cannot be undone', async () => {
    apiGet.mockResolvedValue(deleted)
    const wrapper = await render()

    await button(wrapper, 'Delete permanently').trigger('click')

    const panel = wrapper.find('[data-test="permanent-delete-panel"]')
    expect(panel.text()).toContain("can't be undone")
    expect(panel.text()).toContain("Past bookings, including completed and cancelled events', keep the venue's name")
    expect(apiDelete).not.toHaveBeenCalled()
  })

  it('permanently deletes on confirmation and returns to the catalogue saying so', async () => {
    apiGet.mockResolvedValue(deleted)
    apiDelete.mockResolvedValue(null)
    const wrapper = await render()

    await button(wrapper, 'Delete permanently').trigger('click')
    await wrapper.find('[data-test="permanent-delete-panel"] .danger-solid').trigger('click')
    await flushPromises()

    expect(apiDelete).toHaveBeenCalledWith('/venues/venue-1/permanent')
    expect(push).toHaveBeenCalledWith({
      name: 'venues',
      query: { deleted: 'Grand Ballroom was permanently deleted. Past bookings still show its name.' },
    })
  })

  it('shows a refused permanent delete and stays on the page', async () => {
    apiGet.mockResolvedValue(deleted)
    apiDelete.mockRejectedValue(new Error('Venue "Grand Ballroom" still has bookings for ongoing events'))
    const wrapper = await render()

    await button(wrapper, 'Delete permanently').trigger('click')
    await wrapper.find('[data-test="permanent-delete-panel"] .danger-solid').trigger('click')
    await flushPromises()

    expect(wrapper.find('[role="alert"]').text()).toContain('still has bookings for ongoing events')
    expect(push).not.toHaveBeenCalled()
  })
})
