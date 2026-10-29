import { describe, expect, it } from 'vitest'
import { paginate } from './pagination'

const twelve = Array.from({ length: 12 }, (_, index) => index + 1)

describe('paginate', () => {
  it('returns the first page', () => {
    expect(paginate(twelve, 1, 5)).toEqual({ items: [1, 2, 3, 4, 5], page: 1, pageCount: 3, total: 12, from: 1, to: 5 })
  })

  it('returns a middle page', () => {
    expect(paginate(twelve, 2, 5)).toMatchObject({ items: [6, 7, 8, 9, 10], from: 6, to: 10 })
  })

  it('returns a short last page', () => {
    expect(paginate(twelve, 3, 5)).toMatchObject({ items: [11, 12], page: 3, from: 11, to: 12 })
  })

  it('clamps a page past the end to the last page', () => {
    expect(paginate(twelve, 9, 5)).toMatchObject({ items: [11, 12], page: 3 })
  })

  it('clamps a page before the start to the first page', () => {
    expect(paginate(twelve, 0, 5).page).toBe(1)
    expect(paginate(twelve, -3, 5).page).toBe(1)
  })

  it('is page 1 of 1 with nothing shown for an empty or missing list', () => {
    const empty = { items: [], page: 1, pageCount: 1, total: 0, from: 0, to: 0 }
    expect(paginate([], 1, 5)).toEqual(empty)
    expect(paginate(undefined, 4, 5)).toEqual(empty)
  })

  it('fits an exact multiple of the page size into whole pages', () => {
    expect(paginate(twelve.slice(0, 10), 2, 5)).toMatchObject({ pageCount: 2, items: [6, 7, 8, 9, 10] })
  })
})
