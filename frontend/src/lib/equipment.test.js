import { describe, expect, it } from 'vitest'
import {
  REQUEST_TABS,
  describeAvailability,
  formatPeriod,
  groupRequestsByTab,
  isRequestTab,
  summariseCheck,
  summariseItems,
  unitStatusLabel,
} from './equipment'

describe('groupRequestsByTab', () => {
  it('splits requests by status into the three tabs', () => {
    const groups = groupRequestsByTab([
      { id: 'a', status: 'pending' },
      { id: 'b', status: 'confirmed' },
      { id: 'c', status: 'rejected' },
      { id: 'd', status: 'pending' },
    ])
    expect(groups.pending.map((r) => r.id)).toEqual(['a', 'd'])
    expect(groups.confirmed.map((r) => r.id)).toEqual(['b'])
    expect(groups.rejected.map((r) => r.id)).toEqual(['c'])
  })

  it('returns empty groups for no requests, and ignores an unknown status', () => {
    expect(groupRequestsByTab(undefined)).toEqual({ pending: [], confirmed: [], rejected: [] })
    expect(groupRequestsByTab([{ id: 'x', status: 'weird' }])).toEqual({ pending: [], confirmed: [], rejected: [] })
  })

  it('isRequestTab accepts exactly the tab keys', () => {
    for (const tab of REQUEST_TABS) expect(isRequestTab(tab.key)).toBe(true)
    expect(isRequestTab('nope')).toBe(false)
    expect(isRequestTab(undefined)).toBe(false)
  })
})

describe('summariseItems', () => {
  it('lists quantity and type for each line', () => {
    expect(summariseItems([{ type: 'projector', quantity: 2 }, { type: 'screen', quantity: 1 }])).toBe(
      '2 × projector, 1 × screen',
    )
  })

  it('says so when there are no items', () => {
    expect(summariseItems([])).toBe('No items')
    expect(summariseItems(undefined)).toBe('No items')
  })
})

describe('unitStatusLabel', () => {
  it('words each status and passes an unknown one through', () => {
    expect(unitStatusLabel('available')).toBe('In service')
    expect(unitStatusLabel('maintenance')).toBe('Under maintenance')
    expect(unitStatusLabel('retired')).toBe('Retired')
    expect(unitStatusLabel('mystery')).toBe('mystery')
  })
})

describe('describeAvailability', () => {
  const base = { requested: 2, total_units: 3, available: 2, out_of_service: 0, reserved_by_others: 0 }

  it('is sufficient when available meets the request exactly', () => {
    const result = describeAvailability(base)
    expect(result.state).toBe('sufficient')
    expect(result.label).toBe('Available')
    expect(result.detail).toBe('2 of 3 units free')
  })

  it('is insufficient, and says by how much, when available is lower', () => {
    const result = describeAvailability({ ...base, available: 1, out_of_service: 1, reserved_by_others: 1 })
    expect(result.state).toBe('insufficient')
    expect(result.label).toBe('Short by 1')
    expect(result.detail).toBe('1 of 3 units free (1 out of service, 1 reserved for other events)')
  })

  it('reports a type with no units at all', () => {
    const result = describeAvailability({ requested: 1, total_units: 0, available: 0, out_of_service: 0, reserved_by_others: 0 })
    expect(result.state).toBe('insufficient')
    expect(result.label).toBe('Short by 1')
    expect(result.detail).toBe('0 of 0 units free')
  })

  it('only mentions the reasons that apply', () => {
    expect(describeAvailability({ ...base, available: 1, reserved_by_others: 2 }).detail).toBe(
      '1 of 3 units free (2 reserved for other events)',
    )
  })
})

describe('summariseCheck', () => {
  it('reports every item sufficient', () => {
    const summary = summariseCheck({ items: [{ requested: 1, available: 1 }, { requested: 2, available: 5 }] })
    expect(summary).toMatchObject({ flagged: 0, sufficient: true })
  })

  it('counts flagged items, singular and plural', () => {
    expect(summariseCheck({ items: [{ requested: 2, available: 1 }, { requested: 1, available: 1 }] }).message).toBe(
      '1 item flagged: not enough equipment available.',
    )
    expect(summariseCheck({ items: [{ requested: 2, available: 1 }, { requested: 3, available: 0 }] }).message).toBe(
      '2 items flagged: not enough equipment available.',
    )
  })

  it('handles an empty request without calling it a pass or a failure', () => {
    expect(summariseCheck({ items: [] }).message).toBe('This request has no items to check.')
    expect(summariseCheck(undefined).flagged).toBe(0)
  })
})

describe('formatPeriod', () => {
  it('shows a same-day period as one date and a time range, in Singapore time', () => {
    // 01:00-05:00 UTC is 09:00-13:00 in Singapore (UTC+8).
    expect(formatPeriod('2026-12-01T01:00:00+00:00', '2026-12-01T05:00:00+00:00')).toBe('01 Dec 2026, 09:00 – 13:00')
  })

  it('is independent of the offset the timestamp is written in', () => {
    expect(formatPeriod('2026-12-01T09:00:00+08:00', '2026-12-01T13:00:00+08:00')).toBe('01 Dec 2026, 09:00 – 13:00')
  })

  it('shows both dates when the period crosses midnight in Singapore', () => {
    expect(formatPeriod('2026-12-01T22:00:00+08:00', '2026-12-02T02:00:00+08:00')).toBe(
      '01 Dec 2026 22:00 – 02 Dec 2026 02:00',
    )
  })

  it('returns an empty string when either end is missing', () => {
    expect(formatPeriod(null, '2026-12-01T05:00:00+00:00')).toBe('')
  })
})
