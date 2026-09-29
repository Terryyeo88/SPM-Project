import { describe, expect, it } from 'vitest'
import {
  DASHBOARD_TABS,
  filterBySearch,
  formatDateRange,
  groupEventsByTab,
  isDashboardTab,
  statusLabel,
  tabForStatus,
} from './coordinatorDashboard'

const ME = 'coord-1'
const OTHER = 'coord-2'

function event(overrides) {
  return { id: overrides.name, coordinator_id: ME, ...overrides }
}

describe('groupEventsByTab', () => {
  it('puts each status in the tab the team agreed on', () => {
    const events = [
      event({ name: 'a', status: 'under_review' }),
      event({ name: 'b', status: 'approved' }),
      event({ name: 'c', status: 'planning' }),
      event({ name: 'd', status: 'confirmed' }),
      event({ name: 'e', status: 'completed' }),
      event({ name: 'f', status: 'cancelled' }),
      event({ name: 'g', status: 'rejected' }),
    ]
    const groups = groupEventsByTab(events, ME)
    const names = (key) => groups[key].map((e) => e.name)
    expect(names('needsReview')).toEqual(['a'])
    expect(names('inPlanning')).toEqual(['b', 'c'])
    expect(names('confirmed')).toEqual(['d'])
    expect(names('past')).toEqual(['e', 'f', 'g'])
  })

  it('never shows draft or submitted requests (no coordinator is assigned yet)', () => {
    const groups = groupEventsByTab(
      [event({ name: 'd', status: 'draft' }), event({ name: 's', status: 'submitted' })],
      ME,
    )
    expect(Object.values(groups).flat()).toEqual([])
  })

  it('leaves out events assigned to another coordinator (multi-role users get a union list)', () => {
    const groups = groupEventsByTab(
      [event({ name: 'mine', status: 'under_review' }), event({ name: 'theirs', status: 'under_review', coordinator_id: OTHER })],
      ME,
    )
    expect(groups.needsReview.map((e) => e.name)).toEqual(['mine'])
  })

  it('returns every tab key, empty, for no events or an unknown user', () => {
    const keys = DASHBOARD_TABS.map((t) => t.key)
    expect(Object.keys(groupEventsByTab(undefined, ME))).toEqual(keys)
    expect(Object.values(groupEventsByTab([event({ name: 'x', status: 'under_review' })], null)).flat()).toEqual([])
  })

  it('maps every status to at most one tab', () => {
    const all = DASHBOARD_TABS.flatMap((t) => t.statuses)
    expect(new Set(all).size).toBe(all.length)
  })
})

describe('tabForStatus / isDashboardTab', () => {
  it('sends an event back to the tab matching its status', () => {
    expect(tabForStatus('under_review')).toBe('needsReview')
    expect(tabForStatus('planning')).toBe('inPlanning')
    expect(tabForStatus('confirmed')).toBe('confirmed')
    expect(tabForStatus('rejected')).toBe('past')
  })

  it('has no tab for draft or submitted', () => {
    expect(tabForStatus('draft')).toBe(null)
    expect(tabForStatus('submitted')).toBe(null)
  })

  it('only accepts real tab keys', () => {
    expect(isDashboardTab('past')).toBe(true)
    expect(isDashboardTab('nonsense')).toBe(false)
    expect(isDashboardTab(undefined)).toBe(false)
  })
})

describe('filterBySearch', () => {
  const events = [{ name: 'Spring Vendor Expo' }, { name: 'Founders Day' }]

  it('matches case-insensitively on part of the name', () => {
    expect(filterBySearch(events, 'vendor')).toEqual([{ name: 'Spring Vendor Expo' }])
  })

  it('returns everything for a blank query', () => {
    expect(filterBySearch(events, '   ')).toBe(events)
  })
})

describe('formatDateRange', () => {
  it('formats a single day', () => {
    expect(formatDateRange('2027-02-22', '2027-02-22')).toBe('22 Feb 2027')
  })

  it('formats a multi-day range', () => {
    expect(formatDateRange('2027-02-22', '2027-02-24')).toBe('22 Feb 2027 – 24 Feb 2027')
  })

  it('handles a missing start date', () => {
    expect(formatDateRange(null, null)).toBe('Date not set')
  })
})

describe('statusLabel', () => {
  it('turns snake_case statuses into title case', () => {
    expect(statusLabel('under_review')).toBe('Under Review')
    expect(statusLabel('confirmed')).toBe('Confirmed')
  })
})
