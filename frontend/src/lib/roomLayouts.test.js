import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./api', () => ({ apiGet: vi.fn() }))

import { apiGet } from './api'
import { fetchRoomLayouts, roomLayoutOptions, venueLayoutChoices } from './roomLayouts'

describe('fetchRoomLayouts', () => {
  beforeEach(() => apiGet.mockReset())

  it('returns the names of the active layouts from the backend', async () => {
    apiGet.mockResolvedValue([{ room_layout_id: 'a', name: 'theatre' }, { room_layout_id: 'b', name: 'u-shape' }])

    expect(await fetchRoomLayouts()).toEqual(['theatre', 'u-shape'])
    expect(apiGet).toHaveBeenCalledWith('/room-layouts')
  })

  it('shares one request between callers while it is in flight, then fetches afresh', async () => {
    apiGet.mockResolvedValue([{ name: 'theatre' }])

    await Promise.all([fetchRoomLayouts(), fetchRoomLayouts(), fetchRoomLayouts()])
    expect(apiGet).toHaveBeenCalledTimes(1)

    await fetchRoomLayouts()
    expect(apiGet).toHaveBeenCalledTimes(2)
  })

  it('passes a failed request on to the caller', async () => {
    apiGet.mockRejectedValueOnce(new Error('Network down'))

    await expect(fetchRoomLayouts()).rejects.toMatchObject({ message: 'Network down' })
  })
})

describe('roomLayoutOptions', () => {
  it('offers the active layouts', () => {
    expect(roomLayoutOptions(['theatre', 'banquet'], 'theatre').map((o) => o.value)).toEqual(['theatre', 'banquet'])
  })

  it("keeps the session's soft-deleted layout, marked as no longer offered", () => {
    const options = roomLayoutOptions(['theatre'], 'banquet')

    expect(options.at(-1)).toEqual({ value: 'banquet', label: 'banquet (no longer offered)', retired: true })
  })

  it('adds nothing for a session with no layout yet', () => {
    expect(roomLayoutOptions(['theatre'], '')).toHaveLength(1)
  })
})

describe('venueLayoutChoices', () => {
  const all = [
    { room_layout_id: 't', name: 'theatre', is_active: true },
    { room_layout_id: 'b', name: 'banquet', is_active: true },
    { room_layout_id: 'old', name: 'old style', is_active: false },
    { room_layout_id: 'gone', name: 'gone style', is_active: false },
  ]

  it('offers every active layout, sorted by name', () => {
    expect(venueLayoutChoices(all, []).map((c) => c.name)).toEqual(['banquet', 'theatre'])
  })

  it('also offers a soft-deleted layout the venue already lists, marked retired -- but no others', () => {
    const choices = venueLayoutChoices(all, [{ room_layout_id: 'old', name: 'old style', is_active: false }])

    expect(choices.map((c) => c.name)).toEqual(['banquet', 'old style', 'theatre'])
    expect(choices.find((c) => c.room_layout_id === 'old').retired).toBe(true)
  })
})
