import { beforeEach, describe, expect, it, vi } from 'vitest'

const apiGet = vi.fn()
const apiPost = vi.fn()
vi.mock('./api', () => ({
  apiGet: (...args) => apiGet(...args),
  apiPost: (...args) => apiPost(...args),
}))

import {
  ENTITY_ROUTES,
  fetchNotifications,
  fetchUnreadCount,
  isUnread,
  markAllInList,
  markAllNotificationsRead,
  markNotificationRead,
  notificationLink,
  notificationLinkLabel,
  replaceNotification,
} from './notifications'
import { ROLES, ROUTE_ACCESS } from './roles'

const note = (id, extra = {}) => ({ id, message: `note ${id}`, read_at: null, entity_type: null, entity_id: null, ...extra })

describe('the API calls', () => {
  beforeEach(() => {
    apiGet.mockReset().mockResolvedValue({})
    apiPost.mockReset().mockResolvedValue({})
  })

  it('call the four notification routes', async () => {
    await fetchNotifications()
    await fetchUnreadCount()
    await markNotificationRead('n-1')
    await markAllNotificationsRead()
    expect(apiGet.mock.calls).toEqual([['/notifications'], ['/notifications/unread-count']])
    expect(apiPost.mock.calls).toEqual([['/notifications/n-1/read', {}], ['/notifications/read-all', {}]])
  })

  it('encode the id into the path', async () => {
    await markNotificationRead('a/b')
    expect(apiPost).toHaveBeenCalledWith('/notifications/a%2Fb/read', {})
  })
})

describe('notificationLink', () => {
  it('links an event notification to the event page for a coordinator', () => {
    const link = notificationLink(note('1', { entity_type: 'event', entity_id: 'e-1' }), [ROLES.EVENT_COORDINATOR])
    expect(link).toEqual({ name: 'event-details', params: { eventId: 'e-1' } })
  })

  it('links a safety review notification to the review for a Safety Officer', () => {
    const link = notificationLink(note('1', { entity_type: 'safety_review', entity_id: 'r-1' }), [ROLES.SAFETY_OFFICER])
    expect(link).toEqual({ name: 'safety-review', params: { reviewId: 'r-1' } })
  })

  it('is null (plain text) with no entity', () => {
    expect(notificationLink(note('1'), Object.values(ROLES))).toBeNull()
  })

  it('is null (plain text) for an entity type with no page', () => {
    expect(notificationLink(note('1', { entity_type: 'venue_booking', entity_id: 'b-1' }), Object.values(ROLES))).toBeNull()
  })

  it('is null when the caller cannot reach that page, rather than a link the router would bounce', () => {
    expect(notificationLink(note('1', { entity_type: 'event', entity_id: 'e-1' }), [ROLES.ATTENDEE])).toBeNull()
    expect(notificationLink(note('1', { entity_type: 'safety_review', entity_id: 'r-1' }), [ROLES.EVENT_COORDINATOR])).toBeNull()
  })

  it('is null for half a link', () => {
    expect(notificationLink(note('1', { entity_type: 'event' }), [ROLES.EVENT_COORDINATOR])).toBeNull()
  })

  it('only ever points at routes that exist in ROUTE_ACCESS', () => {
    const names = new Set(ROUTE_ACCESS.map((entry) => entry.routeName))
    for (const target of Object.values(ENTITY_ROUTES)) {
      expect(names.has(target.name)).toBe(true)
    }
  })

  it('labels a link by what it opens', () => {
    expect(notificationLinkLabel(note('1', { entity_type: 'event', entity_id: 'e' }))).toBe('View event')
    expect(notificationLinkLabel(note('1'))).toBe('')
  })
})

describe('list helpers', () => {
  it('isUnread is true until read_at is set', () => {
    expect(isUnread(note('1'))).toBe(true)
    expect(isUnread(note('1', { read_at: '2026-10-29T01:00:00Z' }))).toBe(false)
  })

  it('replaceNotification swaps in the server copy and keeps the order', () => {
    const list = [note('1'), note('2'), note('3')]
    const updated = { ...list[1], read_at: '2026-10-29T01:00:00Z' }
    expect(replaceNotification(list, updated)).toEqual([list[0], updated, list[2]])
  })

  it('markAllInList stamps only the unread ones', () => {
    const earlier = '2026-10-28T01:00:00Z'
    const list = [note('1'), note('2', { read_at: earlier })]
    const now = '2026-10-29T01:00:00Z'
    expect(markAllInList(list, now).map((n) => n.read_at)).toEqual([now, earlier])
  })
})
