import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./api', () => ({ apiGet: vi.fn(), apiPost: vi.fn() }))

import { apiGet, apiPost } from './api'
import {
  MAX_MESSAGE_LENGTH,
  authorLabel,
  canOrganiserReply,
  coordinatorHasAsked,
  fetchClarifications,
  messageError,
  sendClarificationReply,
  sendClarificationRequest,
} from './clarifications'

beforeEach(() => {
  apiGet.mockReset()
  apiPost.mockReset()
})

describe('clarifications API calls', () => {
  it('loads the thread of the session', async () => {
    apiGet.mockResolvedValue([])
    await fetchClarifications('session-1')
    expect(apiGet).toHaveBeenCalledWith('/events/session-1/clarifications')
  })

  it('posts the coordinator side to /request and the organiser side to /reply', async () => {
    await sendClarificationRequest('session-1', 'Is the date flexible?')
    await sendClarificationReply('session-1', 'Yes.')
    expect(apiPost).toHaveBeenNthCalledWith(1, '/events/session-1/clarifications/request', { message: 'Is the date flexible?' })
    expect(apiPost).toHaveBeenNthCalledWith(2, '/events/session-1/clarifications/reply', { message: 'Yes.' })
  })
})

describe('messageError', () => {
  it('refuses a blank message', () => {
    for (const text of ['', '   ', '\n', null, undefined]) {
      expect(messageError(text)).toBe('Enter a message before sending.')
    }
  })

  it('accepts up to the limit, counting the trimmed text', () => {
    expect(messageError('x'.repeat(MAX_MESSAGE_LENGTH))).toBe('')
    expect(messageError(`  ${'x'.repeat(MAX_MESSAGE_LENGTH)}  `)).toBe('')
  })

  it('refuses a message over the limit', () => {
    expect(messageError('x'.repeat(MAX_MESSAGE_LENGTH + 1))).toMatch('1000 characters')
  })
})

describe('authorLabel', () => {
  it('names the sender and their side', () => {
    expect(authorLabel({ author_name: 'Alice Tan', author_role: 'coordinator' })).toBe('Alice Tan (Event Coordinator)')
    expect(authorLabel({ author_name: 'Derek Ong', author_role: 'organizer' })).toBe('Derek Ong (Event Organiser)')
  })

  it('falls back to the side when the name is missing', () => {
    expect(authorLabel({ author_name: null, author_role: 'organizer' })).toBe('Event Organiser')
  })
})

describe('canOrganiserReply', () => {
  const asked = [{ author_role: 'coordinator' }]

  it('only once the coordinator has asked something', () => {
    expect(coordinatorHasAsked([])).toBe(false)
    expect(canOrganiserReply({ status: 'under_review' }, [])).toBe(false)
    expect(canOrganiserReply({ status: 'under_review' }, asked)).toBe(true)
  })

  it('only while the request is under review', () => {
    for (const status of ['submitted', 'approved', 'rejected', 'planning', 'confirmed']) {
      expect(canOrganiserReply({ status }, asked)).toBe(false)
    }
  })
})
