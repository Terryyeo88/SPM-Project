import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiGet = vi.fn()
const apiPost = vi.fn()
vi.mock('../../lib/api', () => ({
  apiGet: (...args) => apiGet(...args),
  apiPost: (...args) => apiPost(...args),
  apiDelete: vi.fn(),
}))
vi.mock('../../components/AppNavBar.vue', () => ({ default: { template: '<div />' } }))
vi.mock('vue-router', () => ({ useRoute: () => ({ params: { venueId: 'v1' } }) }))
const auth = { roles: [] }
vi.mock('../../stores/auth', () => ({ useAuthStore: () => auth }))

import VenueDetailView from './VenueDetailView.vue'

const VENUE = {
  id: 'v1',
  name: 'Hall A',
  status: 'available',
  location: 'Main Building',
  capacity: 100,
  facilities: [],
  accessibility_features: [],
  supported_layouts: ['old style', 'theatre'],
  supported_room_layouts: [
    { room_layout_id: 'old', name: 'old style', is_active: false },
    { room_layout_id: 't', name: 'theatre', is_active: true },
  ],
}
const ALL_LAYOUTS = [
  { room_layout_id: 't', name: 'theatre', is_active: true },
  { room_layout_id: 'b', name: 'banquet', is_active: true },
  { room_layout_id: 'old', name: 'old style', is_active: false },
  { room_layout_id: 'gone', name: 'gone style', is_active: false },
]

async function mountAs(roles) {
  auth.roles = roles
  const wrapper = mount(VenueDetailView)
  await flushPromises()
  return wrapper
}

function editButton(wrapper) {
  return wrapper.findAll('button').find((b) => b.text() === 'Edit layouts')
}

async function openEditor(wrapper) {
  await editButton(wrapper).trigger('click')
  await flushPromises()
}

describe('VenueDetailView -- supported room layouts', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
    apiGet.mockImplementation((path) => Promise.resolve(path === '/venues/v1' ? VENUE : ALL_LAYOUTS))
  })

  it('lists the venue layouts, marking a deleted one', async () => {
    const wrapper = await mountAs(['event_coordinator'])

    expect(wrapper.find('[data-test="layout-summary"]').text()).toBe('old style (deleted), theatre')
  })

  it('only Venue Staff get to edit them', async () => {
    expect(editButton(await mountAs(['event_coordinator']))).toBeUndefined()
    expect(editButton(await mountAs(['venue_staff']))).toBeDefined()
  })

  it('offers active layouts plus the deleted one the venue already lists, ticked as they are now', async () => {
    const wrapper = await mountAs(['venue_staff'])
    await openEditor(wrapper)

    const choices = wrapper.findAll('.layout-choice')
    expect(choices.map((c) => c.text().split(' (')[0].trim())).toEqual(['banquet', 'old style', 'theatre'])
    expect(choices.map((c) => c.find('input').element.checked)).toEqual([false, true, true])
  })

  it('saves the ticked layouts and shows the updated venue', async () => {
    apiPost.mockResolvedValue({
      ...VENUE,
      supported_room_layouts: [
        { room_layout_id: 'b', name: 'banquet', is_active: true },
        { room_layout_id: 't', name: 'theatre', is_active: true },
      ],
    })
    const wrapper = await mountAs(['venue_staff'])
    await openEditor(wrapper)

    const [banquet, oldStyle] = wrapper.findAll('.layout-choice input')
    await banquet.setValue(true)
    await oldStyle.setValue(false)
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/venues/v1/room-layouts', { room_layout_ids: ['t', 'b'] })
    expect(wrapper.find('[data-test="layout-summary"]').text()).toBe('banquet, theatre')
  })

  it('shows why a save was refused and stays in edit mode', async () => {
    apiPost.mockRejectedValueOnce(new Error('Soft-deleted room layouts cannot be added to a venue: old style.'))
    const wrapper = await mountAs(['venue_staff'])
    await openEditor(wrapper)

    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[role="alert"]').text()).toContain('cannot be added')
    expect(wrapper.find('.layout-editor').exists()).toBe(true)
  })
})
