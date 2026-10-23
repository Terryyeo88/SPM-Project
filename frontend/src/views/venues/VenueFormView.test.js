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

function saveButton(wrapper) {
  return wrapper.find('button[type="submit"]')
}

function shownError(wrapper, field) {
  const error = wrapper.find(`[data-error="${field}"]`)
  return error.exists() ? error.text() : null
}

async function fillRequired(wrapper) {
  await wrapper.find('#venue-name').setValue('Annex')
  await wrapper.find('#venue-location').setValue('East Campus')
  await wrapper.find('#venue-capacity').setValue('40')
  await wrapper.find('input[value="classroom"]').setValue(true)
}

describe('VenueFormView -- checks as you go', () => {
  it('keeps Save disabled until every required field is filled', async () => {
    const wrapper = await render()

    expect(saveButton(wrapper).attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-test="save-hint"]').exists()).toBe(true)

    await wrapper.find('#venue-name').setValue('Annex')
    await wrapper.find('#venue-location').setValue('East Campus')
    await wrapper.find('#venue-capacity').setValue('40')
    expect(saveButton(wrapper).attributes('disabled')).toBeDefined() // still no room layout

    await wrapper.find('input[value="classroom"]').setValue(true)
    expect(saveButton(wrapper).attributes('disabled')).toBeUndefined()
    expect(wrapper.find('[data-test="save-hint"]').exists()).toBe(false)
  })

  it('shows no errors on a fresh form until a field is left', async () => {
    const wrapper = await render()

    expect(wrapper.findAll('[data-error]')).toHaveLength(0)

    await wrapper.find('#venue-name').trigger('blur')
    expect(shownError(wrapper, 'name')).toBe('Name is required.')
    expect(shownError(wrapper, 'location')).toBeNull() // not left yet
    expect(wrapper.find('#venue-name').attributes('aria-invalid')).toBe('true')
  })

  it('clears an error as soon as the field is fixed', async () => {
    const wrapper = await render()

    await wrapper.find('#venue-capacity').setValue('0')
    await wrapper.find('#venue-capacity').trigger('blur')
    expect(shownError(wrapper, 'capacity')).toContain('at least 1')

    await wrapper.find('#venue-capacity').setValue('20')
    expect(shownError(wrapper, 'capacity')).toBeNull()
  })

  it('flags a setup or turnaround time under 5 minutes when the field is left', async () => {
    const wrapper = await render()

    await wrapper.find('#venue-setup').setValue('4')
    await wrapper.find('#venue-setup').trigger('blur')
    await wrapper.find('#venue-turnaround').setValue('3')
    await wrapper.find('#venue-turnaround').trigger('blur')

    expect(shownError(wrapper, 'setup_minutes')).toBe('Setup time must be a whole number of at least 5 minutes.')
    expect(shownError(wrapper, 'turnaround_minutes')).toBe('Turnaround time must be a whole number of at least 5 minutes.')

    await fillRequired(wrapper)
    expect(saveButton(wrapper).attributes('disabled')).toBeDefined()

    await wrapper.find('#venue-setup').setValue('5')
    await wrapper.find('#venue-turnaround').setValue('5')
    expect(saveButton(wrapper).attributes('disabled')).toBeUndefined()
  })

  it('flags a missing room layout once focus leaves the group, not while moving between boxes', async () => {
    const wrapper = await render()
    const group = wrapper.find('[data-field="supported_layouts"]')
    const classroom = group.find('input[value="classroom"]').element

    await group.trigger('focusout', { relatedTarget: classroom }) // theatre -> classroom: still inside
    expect(shownError(wrapper, 'supported_layouts')).toBeNull()

    await group.trigger('focusout', { relatedTarget: null }) // left the group
    expect(shownError(wrapper, 'supported_layouts')).toBe('Choose at least one supported room layout.')

    await wrapper.find('input[value="theatre"]').setValue(true)
    expect(shownError(wrapper, 'supported_layouts')).toBeNull()
  })
})

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

  it('a forced submit of an incomplete form shows every problem and calls nothing', async () => {
    const wrapper = await render()

    await wrapper.find('form').trigger('submit')

    expect(apiPost).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Name is required.')
    expect(wrapper.text()).toContain('Location is required.')
    expect(wrapper.text()).toContain('Choose at least one supported room layout.')
  })

  it("shows the backend's refusal", async () => {
    apiPost.mockRejectedValue(new Error('Unknown room layout: classroom. Refresh the page to see the current list.'))
    const wrapper = await render()

    await fillRequired(wrapper)
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

  it('a valid venue can be saved straight away', async () => {
    const wrapper = await render()

    expect(saveButton(wrapper).attributes('disabled')).toBeUndefined()
    expect(wrapper.findAll('[data-error]')).toHaveLength(0)
  })

  it('a venue that already breaks a rule shows why at once, and stays unsaveable until fixed', async () => {
    apiGet.mockImplementation((path) =>
      Promise.resolve(path === '/room-layouts' ? LAYOUTS : { ...venue, supported_layouts: [], setup_minutes: 0 }),
    )
    const wrapper = await render()

    expect(shownError(wrapper, 'supported_layouts')).toBe('Choose at least one supported room layout.')
    expect(shownError(wrapper, 'setup_minutes')).toContain('at least 5 minutes')
    expect(saveButton(wrapper).attributes('disabled')).toBeDefined()

    await wrapper.find('input[value="theatre"]').setValue(true)
    await wrapper.find('#venue-setup').setValue('10')
    expect(saveButton(wrapper).attributes('disabled')).toBeUndefined()
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
