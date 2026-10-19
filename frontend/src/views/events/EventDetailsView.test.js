import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

// IS-9 AC5 on the page: "Only users whose role and relationship to the event
// permit it can make updates; others can view but not edit." The backend
// enforces it (rule_event_edit, tested in test_event_update.py); this pins
// which layout each person is given, so nobody is shown an edit form the
// backend would refuse.

const auth = { profile: { id: 'org-1' }, roles: ['event_organizer'] }

vi.mock('../../lib/api', () => ({ apiGet: vi.fn(), apiPost: vi.fn(), apiDelete: vi.fn() }))
vi.mock('../../stores/auth', () => ({ useAuthStore: () => auth }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { eventId: 'session-1' }, query: {} }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))

import { apiGet } from '../../lib/api'
import EventDetailsView from './EventDetailsView.vue'

const STUBS = {
  RouterLink: RouterLinkStub,
  AppNavBar: true,
  CoordinatorEventReview: { name: 'CoordinatorEventReview', template: '<div class="coordinator-review" />' },
  EventChangeRequests: true,
  EventLogHistory: true,
  EventSessionFields: { name: 'EventSessionFields', template: '<div class="session-fields" />' },
  SessionSummaryCard: true,
  VenueBookingStatus: true,
  EquipmentBookingStatus: true,
  SafetyCheckStatus: true,
}

function session(status) {
  return {
    id: 'session-1',
    shared_event_id: 'group-1',
    organizer_id: 'org-1',
    coordinator_id: 'coord-1',
    status,
    name: 'Annual Tech Symposium',
    description: 'A symposium.',
    purpose: 'Learning.',
    preferred_start_date: '2099-11-10',
    preferred_end_date: '2099-11-10',
    preferred_start_time: '09:00:00',
    preferred_end_time: '17:00:00',
    expected_attendance: 100,
    room_layout: 'theatre',
    accessibility_needs: [],
    equipment_needed: { equipment: [] },
    registration_needs: false,
  }
}

async function viewAs(userId, roles, status) {
  auth.profile = { id: userId }
  auth.roles = roles
  const row = session(status)
  apiGet.mockImplementation((path) => Promise.resolve(
    path.endsWith('/sessions')
      ? { shared_event_id: 'group-1', name: row.name, description: row.description, purpose: row.purpose, sessions: [row] }
      : row,
  ))
  const wrapper = mount(EventDetailsView, { global: { stubs: STUBS } })
  await flushPromises()
  return wrapper
}

function isEditable(wrapper) {
  return wrapper.find('form.container-form').exists()
}

// Braces: a function returned from beforeEach is run as teardown, and apiGet
// IS a function -- it would be called once more, with no path, after each test.
beforeEach(() => {
  apiGet.mockReset()
})

describe('EventDetailsView -- who may edit (IS-9 AC5)', () => {
  it('gives the assigned coordinator the review page, where they edit the details', async () => {
    const wrapper = await viewAs('coord-1', ['event_coordinator'], 'planning')
    expect(wrapper.find('.coordinator-review').exists()).toBe(true)
    expect(isEditable(wrapper)).toBe(false)
  })

  it('lets the organiser edit their own draft', async () => {
    const wrapper = await viewAs('org-1', ['event_organizer'], 'draft')
    expect(isEditable(wrapper)).toBe(true)
    expect(wrapper.find('.coordinator-review').exists()).toBe(false)
  })

  it('lets the organiser fix a rejected session before resubmitting', async () => {
    const wrapper = await viewAs('org-1', ['event_organizer'], 'rejected')
    expect(isEditable(wrapper)).toBe(true)
  })

  it.each(['submitted', 'under_review', 'approved', 'planning', 'safety_review', 'confirmed'])(
    'shows the organiser a %s event read-only',
    async (status) => {
      const wrapper = await viewAs('org-1', ['event_organizer'], status)
      expect(wrapper.text()).toContain('Annual Tech Symposium')
      expect(isEditable(wrapper)).toBe(false)
      expect(wrapper.find('.coordinator-review').exists()).toBe(false)
    },
  )

  it('shows the Event Coordinator Lead the event read-only', async () => {
    const wrapper = await viewAs('lead-1', ['event_coordinator_lead'], 'planning')
    expect(wrapper.text()).toContain('Annual Tech Symposium')
    expect(isEditable(wrapper)).toBe(false)
    expect(wrapper.find('.coordinator-review').exists()).toBe(false)
  })

  it('shows another coordinator, not assigned to it, no review page', async () => {
    const wrapper = await viewAs('coord-2', ['event_coordinator'], 'planning')
    expect(wrapper.find('.coordinator-review').exists()).toBe(false)
    expect(isEditable(wrapper)).toBe(false)
  })
})
