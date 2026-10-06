import { describe, expect, it } from 'vitest'
import {
  assignTargetId,
  filterRequests,
  groupByCoordinator,
  groupForLead,
  groupRequests,
  isLeadTab,
  leadTabForRequest,
  reassignTargetId,
} from './leadDashboard'

function session(id, overrides = {}) {
  return {
    id,
    name: 'Workshop',
    shared_event_id: 'req-1',
    status: 'submitted',
    coordinator_id: null,
    preferred_start_date: '2026-11-10',
    preferred_end_date: '2026-11-10',
    ...overrides,
  }
}

describe('groupRequests', () => {
  it('folds the sessions of one request into a single entry, chronologically', () => {
    const [request] = groupRequests([
      session('b', { preferred_start_date: '2026-11-12', preferred_end_date: '2026-11-12' }),
      session('a'),
    ])
    expect(request.key).toBe('req-1')
    expect(request.sessions.map((s) => s.id)).toEqual(['a', 'b'])
    expect(request.startDate).toBe('2026-11-10')
    expect(request.endDate).toBe('2026-11-12')
  })

  it('treats a row without shared_event_id as a request of one, and skips drafts', () => {
    const requests = groupRequests([
      session('legacy', { shared_event_id: null }),
      session('draft', { shared_event_id: 'req-2', status: 'draft' }),
    ])
    expect(requests.map((r) => r.key)).toEqual(['legacy'])
  })
})

describe('leadTabForRequest / groupForLead', () => {
  it('sorts requests into Unassigned, Assigned and Past', () => {
    const groups = groupForLead([
      session('queue'),
      session('active', { shared_event_id: 'req-2', status: 'planning', coordinator_id: 'c1' }),
      session('done', { shared_event_id: 'req-3', status: 'completed', coordinator_id: 'c1' }),
      session('cancelled', { shared_event_id: 'req-4', status: 'cancelled', coordinator_id: 'c1' }),
    ])
    expect(groups.unassigned.map((r) => r.key)).toEqual(['req-1'])
    expect(groups.assigned.map((r) => r.key)).toEqual(['req-2'])
    expect(groups.past.map((r) => r.key).sort()).toEqual(['req-3', 'req-4'])
  })

  it('a request with one session finished and one still active is Assigned, not Past', () => {
    const [request] = groupRequests([
      session('a', { status: 'completed', coordinator_id: 'c1' }),
      session('b', { status: 'confirmed', coordinator_id: 'c1' }),
    ])
    expect(leadTabForRequest(request)).toBe('assigned')
  })

  it('a request with any session still waiting for a coordinator is Unassigned', () => {
    const [request] = groupRequests([
      session('a', { status: 'under_review', coordinator_id: 'c1' }),
      session('b'),
    ])
    expect(leadTabForRequest(request)).toBe('unassigned')
  })

  it('validates tab keys', () => {
    expect(isLeadTab('assigned')).toBe(true)
    expect(isLeadTab('needsReview')).toBe(false)
  })
})

describe('groupByCoordinator', () => {
  const coordinators = [
    { id: 'c1', name: 'Alice' },
    { id: 'c2', name: 'Brandon' },
  ]

  it('gives every coordinator a section, including those with nothing assigned', () => {
    const [request] = groupRequests([session('a', { status: 'planning', coordinator_id: 'c1' })])
    const sections = groupByCoordinator([request], coordinators)
    expect(sections.map((s) => [s.coordinator.name, s.requests.length])).toEqual([['Alice', 1], ['Brandon', 0]])
  })

  it('keeps a request whose coordinator is not in the list, under Unknown coordinator', () => {
    const [request] = groupRequests([session('a', { status: 'planning', coordinator_id: 'gone' })])
    const sections = groupByCoordinator([request], coordinators)
    expect(sections[2].coordinator.name).toBe('Unknown coordinator')
    expect(sections[2].requests).toHaveLength(1)
  })
})

describe('target ids', () => {
  it('assigns against a session still in the queue', () => {
    const [request] = groupRequests([
      session('a', { status: 'under_review', coordinator_id: 'c1' }),
      session('b'),
    ])
    expect(assignTargetId(request)).toBe('b')
  })

  it('reassigns against an unfinished session held by the request coordinator', () => {
    const [request] = groupRequests([
      session('a', { status: 'completed', coordinator_id: 'c1' }),
      session('b', { status: 'confirmed', coordinator_id: 'c1', preferred_start_date: '2026-11-11' }),
    ])
    expect(reassignTargetId(request)).toBe('b')
  })
})

describe('filterRequests', () => {
  it('matches the request name case-insensitively', () => {
    const requests = groupRequests([session('a', { name: 'Annual Gala' })])
    expect(filterRequests(requests, 'gala')).toHaveLength(1)
    expect(filterRequests(requests, 'symposium')).toHaveLength(0)
    expect(filterRequests(requests, '  ')).toHaveLength(1)
  })
})
