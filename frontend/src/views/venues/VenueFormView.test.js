import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const route = { params: {}, query: {} }
const push = vi.fn()

vi.mock('../../lib/api', () => ({ apiGet: vi.fn(), apiPost: vi.fn(), apiDelete: vi.fn() }))
vi.mock('vue-router', () => ({ useRoute: () => route, useRouter: () => ({ push }) }))
vi.mock('../../components/AppNavBar.vue', () => ({ default: { template: '<nav />' } }))

import { apiGet, apiPost } from '../../lib/api'
import VenueFormView from './VenueFormView.vue'

const LAYOUTS = [{ name: 'theatre' }, { name: 'classroom' }]
const venue = {
  id: 'venue-1',
  name: 'Grand Ballroom',
  location: 'Main Building, Level 3',
  capacity: 300,
  facilities: ['wifi'],
  accessibility_features: [],
  supported_layouts: ['theatre'],
  status: 'available',
  setup_minutes: 30,
  turnaround_minutes: 30,
  operating_hours_start: '07:00:00',
  operating_hours_end: '23:59:00',
  deleted_at: null,
}

beforeEach(() => {
  apiGet.mockReset()
  apiPost.mockReset()
  push.mockReset()
  route.params = {}
  apiGet.mockImplementation((path) => Promise.resolve(path === '/room-layouts' ? LAYOUTS : venue))
})

async function render() {
  const wrapper = mount(VenueFormView, { global: { stubs: { RouterLink: RouterLinkStub } } })
  await flushPromises()
  return wrapper
}

describe('VenueFormView -- add (IS-61 AC1)', () => {
  it('offers the active room layouts, facilities and accessibility provisions', async () => {
    const wrapper = await render()

    expect(wrapper.find('h1').text()).toBe('Add a venue')
    const values = wrapper.findAll('input[type="checkbox"]').map((input) => input.element.value)
    expect(values).toEqual(expect.arrayContaining(['theatre', 'classroom', 'projector', 'wheelchair_access']))
  })

  it('has no status field', async () => {
    const wrapper = await render()

    expect(wrapper.find('select').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Status')
  })

  it('adds a venue as available and opens it', async () => {
    apiPost.mockResolvedValue({ id: 'venue-new' })
    const wrapper = await render()

    await wrapper.find('#venue-name').setValue('Annex')
    await wrapper.find('#venue-location').setValue('East Campus')
    await wrapper.find('#venue-capacity').setValue('40')
    await wrapper.find('input[value="classroom"]').setValue(true)
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    const [[path, body]] = apiPost.mock.calls
    expect(path).toBe('/venues')
    expect(body).toMatchObject({
      name: 'Annex',
      location: 'East Campus',
      capacity: 40,
      supported_layouts: ['classroom'],
      status: 'available',
    })
    expect(push).toHaveBeenCalledWith({
      name: 'venue-details',
      params: { venueId: 'venue-new' },
      query: { saved: 'created' },
    })
  })

  it('shows what is missing without calling the backend', async () => {
    const wrapper = await render()

    await wrapper.find('form').trigger('submit')

    expect(apiPost).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Name is required.')
    expect(wrapper.text()).toContain('Location is required.')
  })

  it("shows the backend's refusal", async () => {
    apiPost.mockRejectedValue(new Error('Unknown room layout: classroom. Refresh the page to see the current list.'))
    const wrapper = await render()

    await wrapper.find('#venue-name').setValue('Annex')
    await wrapper.find('#venue-location').setValue('East Campus')
    await wrapper.find('#venue-capacity').setValue('40')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[role="alert"]').text()).toContain('Unknown room layout')
    expect(push).not.toHaveBeenCalled()
  })
})

describe('VenueFormView -- edit (IS-61 AC2)', () => {
  beforeEach(() => {
    route.params = { venueId: 'venue-1' }
  })

  it("fills the form with the venue's details", async () => {
    const wrapper = await render()

    expect(wrapper.find('h1').text()).toBe('Edit venue')
    expect(wrapper.find('#venue-name').element.value).toBe('Grand Ballroom')
    expect(wrapper.find('#venue-capacity').element.value).toBe('300')
  })

  it('has no operating hours fields', async () => {
    const wrapper = await render()

    expect(wrapper.find('input[type="time"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('Opens')
  })

  it('sends only what changed (never the status)', async () => {
    apiPost.mockResolvedValue({ id: 'venue-1' })
    const wrapper = await render()

    await wrapper.find('#venue-capacity').setValue('250')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/venues/venue-1', { capacity: 250 })
    expect(push).toHaveBeenCalledWith({
      name: 'venue-details',
      params: { venueId: 'venue-1' },
      query: { saved: 'updated' },
    })
  })

  it('goes back without saving when nothing changed', async () => {
    const wrapper = await render()

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(apiPost).not.toHaveBeenCalled()
    expect(push).toHaveBeenCalledWith({ name: 'venue-details', params: { venueId: 'venue-1' } })
  })

  it('does not offer to edit a deleted venue', async () => {
    apiGet.mockImplementation((path) =>
      Promise.resolve(path === '/room-layouts' ? LAYOUTS : { ...venue, deleted_at: '2026-10-23T10:00:00+00:00' }),
    )
    const wrapper = await render()

    expect(wrapper.find('form').exists()).toBe(false)
    expect(wrapper.find('[role="alert"]').text()).toContain('deleted from the catalogue')
  })
})
