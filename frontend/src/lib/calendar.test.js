import { describe, expect, it } from 'vitest'
import { addDays, monthCells, rangeFor, rangeQuery, sortedByStart, stepAnchor, useCalendarRange } from './calendar'

// Local-time dates throughout, like the calendar itself.
const day = (y, m, d) => new Date(y, m - 1, d)

describe('rangeFor', () => {
  it('day view is the anchor day only', () => {
    expect(rangeFor('day', day(2026, 10, 16))).toEqual({ start: day(2026, 10, 16), end: day(2026, 10, 17) })
  })

  it('week view runs Sunday to the next Sunday', () => {
    // 2026-10-16 is a Friday.
    expect(rangeFor('week', day(2026, 10, 16))).toEqual({ start: day(2026, 10, 11), end: day(2026, 10, 18) })
  })

  it('month view runs from the 1st to the 1st of the next month', () => {
    expect(rangeFor('month', day(2026, 12, 16))).toEqual({ start: day(2026, 12, 1), end: day(2027, 1, 1) })
  })
})

describe('rangeQuery', () => {
  it('sends the last included day as end, not the exclusive boundary', () => {
    const range = { start: new Date(Date.UTC(2026, 9, 1)), end: new Date(Date.UTC(2026, 10, 1)) }
    expect(rangeQuery(range)).toBe(
      `start=2026-10-01&end=${addDays(range.end, -1).toISOString().slice(0, 10)}`,
    )
  })
})

describe('stepAnchor', () => {
  it('moves a day, a week, or to the 1st of the next month', () => {
    expect(stepAnchor('day', day(2026, 10, 31), 1)).toEqual(day(2026, 11, 1))
    expect(stepAnchor('week', day(2026, 10, 16), -1)).toEqual(day(2026, 10, 9))
    expect(stepAnchor('month', day(2026, 1, 31), 1)).toEqual(day(2026, 2, 1))
  })
})

describe('monthCells', () => {
  const october = rangeFor('month', day(2026, 10, 1))

  it('pads the first week with blanks and has one cell per day', () => {
    const cells = monthCells(october, [])
    // 2026-10-01 is a Thursday: four blanks (Sun-Wed).
    expect(cells.slice(0, 4).every((cell) => cell.blank)).toBe(true)
    expect(cells.filter((cell) => !cell.blank)).toHaveLength(31)
  })

  it('puts an entry in the cell of the day it starts, and ignores other months', () => {
    const inMonth = { start: new Date(2026, 9, 20, 10).toISOString() }
    const nextMonth = { start: new Date(2026, 10, 2, 10).toISOString() }
    const cells = monthCells(october, [inMonth, nextMonth])

    const filled = cells.filter((cell) => !cell.blank && cell.entries.length)
    expect(filled).toEqual([{ blank: false, day: 20, entries: [inMonth] }])
  })
})

describe('sortedByStart', () => {
  it('orders by start without changing the input', () => {
    const entries = [{ start: '2026-10-02T00:00:00Z' }, { start: '2026-10-01T00:00:00Z' }]
    expect(sortedByStart(entries).map((entry) => entry.start)).toEqual([
      '2026-10-01T00:00:00Z',
      '2026-10-02T00:00:00Z',
    ])
    expect(entries[0].start).toBe('2026-10-02T00:00:00Z')
  })
})

describe('useCalendarRange', () => {
  it('derives the range and label from the view and anchor', () => {
    const calendar = useCalendarRange('day')
    calendar.anchor.value = day(2026, 10, 16)
    expect(calendar.range.value).toEqual({ start: day(2026, 10, 16), end: day(2026, 10, 17) })

    calendar.step(1)
    expect(calendar.anchor.value).toEqual(day(2026, 10, 17))

    calendar.view.value = 'month'
    expect(calendar.label.value).toBe(day(2026, 10, 1).toLocaleDateString(undefined, { month: 'long', year: 'numeric' }))
  })
})
