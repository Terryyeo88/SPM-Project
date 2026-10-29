import { defineStore } from 'pinia'
import { fetchUnreadCount } from '../lib/notifications'

/**
 * The caller's unread notification count (IS-69), shared so anything
 * showing it (the notifications page, and a nav bell) agrees without each
 * refetching. Whoever gets a fresh count from the backend -- every
 * notifications route returns one -- hands it to setUnreadCount().
 *
 * `unreadCount` is null until something has loaded it.
 */
export const useNotificationStore = defineStore('notifications', {
  state: () => ({
    unreadCount: null,
  }),

  actions: {
    setUnreadCount(count) {
      this.unreadCount = typeof count === 'number' ? count : this.unreadCount
    },

    /** GET /notifications/unread-count. Throws on failure, like apiGet. */
    async refreshUnreadCount() {
      const body = await fetchUnreadCount()
      this.setUnreadCount(body?.unread_count)
      return this.unreadCount
    },
  },
})
