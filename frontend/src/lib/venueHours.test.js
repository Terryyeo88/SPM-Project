import { describe, expect, it } from 'vitest'
import { outsideHoursEntries, outsideHoursLabel } from './venueHours'

// [start, end) as lib/calendar.js builds it: local midnights.
const day = (y, m, d) => new Date(y, m - 1, d)
const oneDay = { start: day(2026, 11, 2), end: day(2026, 11, 3) }
const week = { start: day(2026, 11, 1), end: day(2026, 11, 8) }

const clock = (iso) => {
  const d = new Date(iso)
  return `${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

describe('outsideHoursEntries (IS-11 AC5)', () => {
  it('marks the time before opening and after closing as unavailable', () => {
    const entries = outsideHoursEntries(oneDay, '08:00:00', '20:00:00', 'day')

    expect(entries.map((e) => [e.period, clock(e.start), clock(e.end)])).toEqual([
      ['before_opening', '2 00:00', '2 08:00'],
      ['after_closing', '2 20:00', '3 00:00'],
    ])
    expect(entries.every((e) => e.state === 'outside_hours')).toBe(true)
  })

  it('does this for every day of a week', () => {
    expect(outsideHoursEntries(week, '08:00', '20:00', 'week')).toHaveLength(14)
  })

  it('gives the month grid one entry a day', () => {
    const month = { start: day(2026, 11, 1), end: day(2026, 12, 1) }
    const entries = outsideHoursEntries(month, '08:00', '20:00', 'month')

    expect(entries).toHaveLength(30)
    expect(new Date(entries[29].start).getDate()).toBe(30)
  })

  it('marks nothing for a venue with no set hours', () => {
    expect(outsideHoursEntries(week, null, null, 'week')).toEqual([])
    expect(outsideHoursEntries(week, '', '', 'month')).toEqual([])
  })

  it('treats a 23:59 closing time as open until midnight', () => {
    const entries = outsideHoursEntries(oneDay, '07:00:00', '23:59:00', 'day')

    expect(entries.map((e) => e.period)).toEqual(['before_opening'])
  })

  it('has no morning entry for a venue opening at midnight', () => {
    const entries = outsideHoursEntries(oneDay, '00:00', '18:00', 'day')

    expect(entries.map((e) => e.period)).toEqual(['after_closing'])
  })

  it('writes times in UTC, so they sort with the backend\'s UTC timestamps', () => {
    const [first] = outsideHoursEntries(oneDay, '08:00', '20:00', 'day')

    expect(first.start).toBe(day(2026, 11, 2).toISOString())
  })
})

describe('outsideHoursLabel', () => {
  it('says when the venue is closed', () => {
    const [before, after] = outsideHoursEntries(oneDay, '08:00', '20:00', 'day')
    const [wholeDay] = outsideHoursEntries(oneDay, '08:00', '20:00', 'month')

    expect(outsideHoursLabel(before)).toBe('Closed until 08:00')
    expect(outsideHoursLabel(after)).toBe('Closed from 20:00')
    expect(outsideHoursLabel(wholeDay)).toBe('Open 08:00–20:00 only')
  })
})
