/**
 * Notifications (IS-69): the calls to the backend's /notifications routes,
 * and the pure helpers the notifications page uses, kept out of the
 * component so they can be unit-tested without mounting.
 *
 * Every authenticated role has notifications, and the backend scopes each
 * route to the caller: someone else's notification, or a malformed id, is
 * a 404. Shapes (backend/app/notifications/routes.py):
 *
 *   GET  /notifications               -> { notifications: [...], unread_count }
 *                                         newest first, capped at 50
 *   GET  /notifications/unread-count  -> { unread_count }
 *   POST /notifications/<id>/read     -> { notification, unread_count }
 *   POST /notifications/read-all      -> { marked_read, unread_count }
 */
import { apiGet, apiPost } from './api'
import { ROUTE_ACCESS, hasAnyRole } from './roles'
import { formatSgt } from './registrations'

export const fetchNotifications = () => apiGet('/notifications')
export const fetchUnreadCount = () => apiGet('/notifications/unread-count')
export const markNotificationRead = (id) => apiPost(`/notifications/${encodeURIComponent(id)}/read`, {})
export const markAllNotificationsRead = () => apiPost('/notifications/read-all', {})

/**
 * Where a notification's `entity_type` can link to: only entities that
 * already have a page. Anything else (or a type added to the backend later)
 * is shown as plain text rather than a dead link.
 *
 *   event          -- the event details page (organiser, coordinator, Lead)
 *   safety_review  -- one safety review (Safety Officer)
 */
export const ENTITY_ROUTES = Object.freeze({
  event: Object.freeze({ name: 'event-details', param: 'eventId', label: 'View event' }),
  safety_review: Object.freeze({ name: 'safety-review', param: 'reviewId', label: 'View safety review' }),
})

const _rolesByRouteName = new Map(ROUTE_ACCESS.map((entry) => [entry.routeName, entry.roles]))

/**
 * The route location a notification links to, or null to show it as plain
 * text: when it has no entity, when no page exists for that entity type, or
 * when the caller's roles can't reach that page (the router would only
 * bounce them to the dashboard).
 */
export function notificationLink(notification, userRoles) {
  const target = ENTITY_ROUTES[notification?.entity_type]
  if (!target || !notification.entity_id) return null
  const roles = _rolesByRouteName.get(target.name)
  if (roles && !hasAnyRole(userRoles, roles)) return null
  return { name: target.name, params: { [target.param]: notification.entity_id } }
}

/** "View event" for a linked notification, '' otherwise. */
export function notificationLinkLabel(notification) {
  return ENTITY_ROUTES[notification?.entity_type]?.label ?? ''
}

export function isUnread(notification) {
  return !notification?.read_at
}

/** When it was sent, in Singapore time, e.g. "3 Nov 2026, 2:00 pm". */
export function notificationTime(notification) {
  return formatSgt(notification?.created_at)
}

/**
 * The list after one notification was marked read: that one replaced by
 * the server's copy (with its `read_at`), the rest untouched and in order.
 */
export function replaceNotification(notifications, updated) {
  return (notifications ?? []).map((n) => (n.id === updated.id ? updated : n))
}

/** The list after "mark all read": every unread one stamped `readAt`. */
export function markAllInList(notifications, readAt) {
  return (notifications ?? []).map((n) => (n.read_at ? n : { ...n, read_at: readAt }))
}
