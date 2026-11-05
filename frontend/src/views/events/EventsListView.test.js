// IS-48 Event search bar, on the organiser's event requests list. The search
// is client-side over the requests GET /events already returned for this
// caller, so it can only narrow what the user may see (AC3's scoping itself
// is the backend's: test_event_list_integration.py).
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../lib/api', () => ({ apiGet: vi.fn() }))
vi.mock('../../stores/auth', () => ({ useAuthStore: () => ({ roles: ['event_organizer'], profile: { id: 'org-1' } }) }))
vi.mock('../../components/AppNavBar.vue', () => ({ default: { template: '<div />' } }))

import { apiGet } from '../../lib/api'
import EventsListView from './EventsListView.vue'

function session(id, name, overrides = {}) {
  return {
    id,
    shared_event_id: `group-${id}`,
    name,
    status: 'submitted',
    preferred_start_date: '2099-03-01',
    preferred_end_date: '2099-03-01',
    ...overrides,
  }
}

async function render(events) {
  apiGet.mockResolvedValue(events)
  const wrapper = mount(EventsListView, { global: { stubs: { RouterLink: RouterLinkStub } } })
  await flushPromises()
  return wrapper
}

const names = (wrapper) => wrapper.findAll('.request .row-name').map((n) => n.text())
const searchBox = (wrapper) => wrapper.find('input[aria-label="Search event requests"]')

beforeEach(() => {
  apiGet.mockReset()
})

describe('EventsListView -- event search bar (IS-48)', () => {
  it('shows a search bar on the events list (AC1)', async () => {
    const wrapper = await render([session('s1', 'Annual Tech Symposium')])
    expect(searchBox(wrapper).exists()).toBe(true)
    expect(searchBox(wrapper).attributes('placeholder')).toBe('Search your event requests...')
  })

  it('filters by event name, ignoring upper or lower case (AC2)', async () => {
    const wrapper = await render([session('s1', 'Annual Tech Symposium'), session('s2', 'Charity Gala')])
    await searchBox(wrapper).setValue('tech SYMP')
    expect(names(wrapper)).toEqual(['Annual Tech Symposium'])
  })

  it('only ever narrows the requests the API returned for this user (AC3)', async () => {
    const wrapper = await render([session('s1', 'Annual Tech Symposium')])
    await searchBox(wrapper).setValue('Gala')
    expect(names(wrapper)).toEqual([])
    expect(apiGet).toHaveBeenCalledTimes(1) // searching fetches nothing new
  })

  it('says so when no event matches, instead of an error or a blank list (AC4)', async () => {
    const wrapper = await render([session('s1', 'Annual Tech Symposium')])
    await searchBox(wrapper).setValue('zzz')
    expect(wrapper.text()).toContain('No event requests match "zzz".')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('restores the full list when the search is cleared (AC5)', async () => {
    const wrapper = await render([session('s1', 'Annual Tech Symposium'), session('s2', 'Charity Gala')])
    await searchBox(wrapper).setValue('gala')
    expect(names(wrapper)).toEqual(['Charity Gala'])
    await searchBox(wrapper).setValue('')
    expect(names(wrapper).sort()).toEqual(['Annual Tech Symposium', 'Charity Gala'])
  })
})
