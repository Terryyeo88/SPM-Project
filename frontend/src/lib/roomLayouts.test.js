import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./api', () => ({ apiGet: vi.fn() }))

import { apiGet } from './api'
import { fetchRoomLayouts, removedLayoutNotice, roomLayoutOptions } from './roomLayouts'

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

describe('removedLayoutNotice', () => {
  it('names the layout Venue Staff removed while the session has none', () => {
    expect(removedLayoutNotice({ room_layout: '', room_layout_removed: 'banquet' })).toBe(
      'The room layout "banquet" is no longer available, so it has been removed from this session. Please choose a new room layout.',
    )
  })

  it('is empty once a layout is chosen, or when none was removed', () => {
    expect(removedLayoutNotice({ room_layout: 'theatre', room_layout_removed: 'banquet' })).toBe('')
    expect(removedLayoutNotice({ room_layout: '', room_layout_removed: '' })).toBe('')
  })
})
