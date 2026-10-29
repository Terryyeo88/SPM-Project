import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./api', () => ({ apiGet: vi.fn(), apiPost: vi.fn() }))

import { apiGet, apiPost } from './api'
import { blockReasonLabel, createVenueBlock, listVenueBlocks, updateVenueSettings, VENUE_BLOCK_REASONS } from './venues'

beforeEach(() => {
  apiGet.mockReset()
  apiPost.mockReset()
})

describe('updateVenueSettings', () => {
  it('posts the given fields to the venue settings endpoint', async () => {
    apiPost.mockResolvedValue({ id: 'venue-1', setup_minutes: 15 })

    const result = await updateVenueSettings('venue-1', { setup_minutes: 15 })

    expect(apiPost).toHaveBeenCalledWith('/venues/venue-1/settings', { setup_minutes: 15 })
    expect(result.setup_minutes).toBe(15)
  })
})

describe('listVenueBlocks', () => {
  it('gets the blocks for a venue', async () => {
    apiGet.mockResolvedValue([{ id: 'block-1' }])

    const result = await listVenueBlocks('venue-1')

    expect(apiGet).toHaveBeenCalledWith('/venues/venue-1/blocks')
    expect(result).toEqual([{ id: 'block-1' }])
  })
})

describe('createVenueBlock', () => {
  it('posts the block body to the venue blocks endpoint', async () => {
    const body = { reason: 'maintenance', block_start: '2026-11-01', block_end: '2026-11-02' }
    apiPost.mockResolvedValue({ block: { id: 'block-1' }, released_bookings: [] })

    const result = await createVenueBlock('venue-1', body)

    expect(apiPost).toHaveBeenCalledWith('/venues/venue-1/blocks', body)
    expect(result.block.id).toBe('block-1')
  })
})

describe('VENUE_BLOCK_REASONS', () => {
  it('matches the backend enum exactly', () => {
    expect([...VENUE_BLOCK_REASONS].sort()).toEqual(
      ['maintenance', 'renovation', 'safety_issue', 'internal_activity', 'other'].sort(),
    )
  })
})

describe('blockReasonLabel', () => {
  it('turns snake_case into a readable, capitalised label', () => {
    expect(blockReasonLabel('safety_issue')).toBe('Safety issue')
    expect(blockReasonLabel('maintenance')).toBe('Maintenance')
  })

  it('tolerates a missing reason without throwing', () => {
    expect(blockReasonLabel(undefined)).toBe('')
    expect(() => blockReasonLabel(null)).not.toThrow()
  })
})
