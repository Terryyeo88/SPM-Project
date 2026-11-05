// IS-48 Event search bar, on the attendee's dashboard. GET
// /registrations/open only ever returns confirmed sessions (the backend's
// test_registrations.py::test_attendee_cannot_see_a_session_that_is_not_confirmed);
// the search filters that list client-side, so it can't surface anything else.
import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../lib/api', () => ({ apiGet: vi.fn() }))

import { apiGet } from '../../lib/api'
import AttendeeDashboard from './AttendeeDashboard.vue'

function session(id, name, overrides = {}) {
  return {
    id,
    name,
    status: 'confirmed',
    registration_needs: true,
    preferred_start_date: '2099-03-01',
    preferred_end_date: '2099-03-01',
    preferred_start_time: '10:00:00',
    preferred_end_time: '12:00:00',
    venues: [],
    ...overrides,
  }
}

async function render(open, mine = []) {
  apiGet.mockImplementation(async (path) => (path === '/registrations/mine' ? mine : open))
  const wrapper = mount(AttendeeDashboard, { global: { stubs: { RouterLink: RouterLinkStub } } })
  await flushPromises()
  return wrapper
}

async function search(wrapper, text) {
  await wrapper.find('#attendee-search').setValue(text)
  await wrapper.find('form[role="search"]').trigger('submit')
}

const results = (wrapper) => wrapper.findAll('.card .card-name').map((n) => n.text())

beforeEach(() => {
  apiGet.mockReset()
})

describe('AttendeeDashboard -- event search bar (IS-48)', () => {
  it('shows a search bar (AC1)', async () => {
    const wrapper = await render([session('s1', 'Annual Tech Symposium')])
    expect(wrapper.find('#attendee-search').exists()).toBe(true)
    expect(wrapper.find('#attendee-search').attributes('placeholder')).toBe('Search by event name')
  })

  it('filters by event name, ignoring upper or lower case (AC2)', async () => {
    const wrapper = await render([session('s1', 'Annual Tech Symposium'), session('s2', 'Charity Gala')])
    await search(wrapper, 'CHARITY')
    expect(results(wrapper)).toEqual(['Charity Gala'])
  })

  it('only ever narrows the confirmed sessions the API returned (AC3)', async () => {
    const wrapper = await render([session('s1', 'Annual Tech Symposium')])
    await search(wrapper, 'Gala')
    expect(results(wrapper)).toEqual([])
    expect(apiGet).toHaveBeenCalledTimes(2) // the initial two loads only; searching fetches nothing
  })

  it('says so when no event matches, instead of an error or a blank page (AC4)', async () => {
    const wrapper = await render([session('s1', 'Annual Tech Symposium')])
    await search(wrapper, 'zzz')
    expect(wrapper.text()).toContain('No events match your search.')
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('clearing the search goes back to the full dashboard (AC5)', async () => {
    const wrapper = await render([session('s1', 'Annual Tech Symposium')])
    await search(wrapper, 'zzz')
    await wrapper.findAll('button').find((b) => b.text().includes('Clear search')).trigger('click')
    expect(wrapper.text()).not.toContain('No events match your search.')
    expect(wrapper.find('#attendee-search').element.value).toBe('')
    await search(wrapper, '')
    expect(results(wrapper)).toEqual(['Annual Tech Symposium'])
  })
})
