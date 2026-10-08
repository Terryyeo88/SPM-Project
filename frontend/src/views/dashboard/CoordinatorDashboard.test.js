import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../lib/api', () => ({ apiGet: vi.fn() }))
vi.mock('../../lib/supabaseClient', () => ({ supabase: {} }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ replace: vi.fn() }),
}))

import { apiGet } from '../../lib/api'
import { useAuthStore } from '../../stores/auth'
import CoordinatorDashboard from './CoordinatorDashboard.vue'

const ME = 'coord-1'

function session(overrides) {
  return {
    coordinator_id: ME,
    shared_event_id: 'group-1',
    name: 'Tech Conference',
    status: 'under_review',
    preferred_start_date: '2099-03-01',
    preferred_end_date: '2099-03-01',
    preferred_start_time: '09:00:00',
    preferred_end_time: '17:00:00',
    expected_attendance: 100,
    ...overrides,
  }
}

async function mountWith(events) {
  apiGet.mockResolvedValue(events)
  const wrapper = mount(CoordinatorDashboard, { global: { stubs: { RouterLink: RouterLinkStub } } })
  await flushPromises()
  return wrapper
}

beforeEach(() => {
  setActivePinia(createPinia())
  useAuthStore().profile = { id: ME, roles: ['event_coordinator'] }
  apiGet.mockReset()
})

describe('CoordinatorDashboard -- one card per event request', () => {
  it("groups a request's sessions into one card, with the sessions inside it", async () => {
    const wrapper = await mountWith([
      session({ id: 's1' }),
      session({ id: 's2', preferred_start_date: '2099-03-02', preferred_end_date: '2099-03-02' }),
      session({ id: 'solo', shared_event_id: 'group-2', name: 'Workshop' }),
    ])

    const cards = wrapper.findAll('.request')
    expect(cards).toHaveLength(2)

    const conference = cards.find((card) => card.find('.row-name').text() === 'Tech Conference')
    expect(conference.find('.request-header').text()).toContain('2 sessions')
    expect(conference.find('.request-header').text()).toContain('2 sessions awaiting your review')
    expect(conference.findAll('.session-row').map((row) => row.find('.session-name').text())).toEqual([
      'Session 1',
      'Session 2',
    ])

    // A single-session request is just the card, no nested list.
    const workshop = cards.find((card) => card.find('.row-name').text() === 'Workshop')
    expect(workshop.find('.sessions').exists()).toBe(false)
  })

  it('counts requests, not sessions, on the tabs and in the attention callout', async () => {
    const wrapper = await mountWith([session({ id: 's1' }), session({ id: 's2' })])

    expect(wrapper.find('.tab.active').text()).toBe('Needs Review (1)')
    expect(wrapper.find('.attention-title').text()).toContain('1 event needs your attention')
  })

  it("only shows the sessions that belong in the open tab", async () => {
    const wrapper = await mountWith([
      session({ id: 's1', status: 'under_review' }),
      session({ id: 's2', status: 'planning' }),
    ])

    const [card] = wrapper.findAll('.request')
    expect(card.find('.sessions').exists()).toBe(false)
    expect(card.find('.status').text()).toBe('Under Review')
  })
})
