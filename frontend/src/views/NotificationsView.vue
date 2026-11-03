<script setup>
/**
 * Notifications (IS-69): the caller's own notifications, newest first,
 * unread ones marked out. Clicking one marks it read; "Mark all as read"
 * clears the lot. Every notifications route returns the new unread count,
 * so the count is taken from the response, never refetched.
 *
 * A notification about something with a page (an event, a safety review)
 * links to it; anything else is plain text -- see lib/notifications.js's
 * notificationLink().
 */
import { computed, onMounted, ref } from 'vue'
import AppNavBar from '../components/AppNavBar.vue'
import {
  fetchNotifications,
  isUnread,
  markAllInList,
  markAllNotificationsRead,
  markNotificationRead,
  notificationLink,
  notificationLinkLabel,
  notificationTime,
  replaceNotification,
} from '../lib/notifications'
import { useAuthStore } from '../stores/auth'
import { useNotificationStore } from '../stores/notifications'

const auth = useAuthStore()
const store = useNotificationStore()

const notifications = ref([])
const loading = ref(true)
const loadError = ref('')
const actionError = ref('')
const markingAll = ref(false)

const unreadCount = computed(() => store.unreadCount ?? notifications.value.filter(isUnread).length)

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const body = await fetchNotifications()
    notifications.value = body?.notifications ?? []
    store.setUnreadCount(body?.unread_count)
  } catch (err) {
    loadError.value = err.message
  } finally {
    loading.value = false
  }
}

async function markRead(notification) {
  if (!isUnread(notification)) return
  actionError.value = ''
  try {
    const body = await markNotificationRead(notification.id)
    notifications.value = replaceNotification(notifications.value, body.notification)
    store.setUnreadCount(body.unread_count)
  } catch (err) {
    actionError.value = `Couldn't mark it as read: ${err.message}`
  }
}

async function markAll() {
  markingAll.value = true
  actionError.value = ''
  try {
    const body = await markAllNotificationsRead()
    notifications.value = markAllInList(notifications.value, new Date().toISOString())
    store.setUnreadCount(body.unread_count)
  } catch (err) {
    actionError.value = `Couldn't mark them as read: ${err.message}`
  } finally {
    markingAll.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="cs-page">
    <AppNavBar />

    <main class="cs-content">
      <div class="cs-container cs-container--narrow">
        <router-link :to="{ name: 'dashboard' }" class="back">&larr; Back to Dashboard</router-link>

        <section class="card cs-card" aria-labelledby="notifications-heading">
          <div class="card-header">
            <div>
              <h1 id="notifications-heading">Notifications</h1>
              <p v-if="!loading && !loadError" class="muted" data-test="unread-summary">
                {{ unreadCount === 1 ? '1 unread' : `${unreadCount} unread` }}
              </p>
            </div>
            <button
              v-if="notifications.length"
              type="button"
              class="mark-all"
              data-test="mark-all"
              :disabled="markingAll || unreadCount === 0"
              @click="markAll"
            >
              Mark all as read
            </button>
          </div>

          <p v-if="actionError" class="error" role="alert">{{ actionError }}</p>

          <p v-if="loading" class="muted">Loading your notifications...</p>
          <p v-else-if="loadError" class="error" role="alert">Couldn't load your notifications: {{ loadError }}</p>
          <p v-else-if="!notifications.length" class="empty" data-test="empty">
            You have no notifications yet.
          </p>
          <ul v-else class="list">
            <li
              v-for="notification in notifications"
              :key="notification.id"
              class="item"
              :class="{ unread: isUnread(notification) }"
              data-test="notification"
            >
              <span v-if="isUnread(notification)" class="dot" aria-hidden="true" />
              <div class="body">
                <button
                  v-if="isUnread(notification)"
                  type="button"
                  class="message"
                  data-test="message"
                  :aria-label="`${notification.message} (unread, mark as read)`"
                  @click="markRead(notification)"
                >
                  {{ notification.message }}
                </button>
                <p v-else class="message" data-test="message">{{ notification.message }}</p>
                <div class="meta">
                  <time :datetime="notification.created_at">{{ notificationTime(notification) }}</time>
                  <router-link
                    v-if="notificationLink(notification, auth.roles)"
                    :to="notificationLink(notification, auth.roles)"
                    class="entity-link"
                    data-test="entity-link"
                    @click="markRead(notification)"
                  >
                    {{ notificationLinkLabel(notification) }}
                  </router-link>
                </div>
              </div>
            </li>
          </ul>
        </section>
      </div>
    </main>
  </div>
</template>

<style scoped>
.back { align-self: flex-start; font-size: var(--cs-text-sm); color: var(--cs-ink-soft); }
.card {
  width: 100%; box-sizing: border-box; display: flex; flex-direction: column; gap: var(--cs-space-4);
  padding: var(--cs-space-7) var(--cs-space-8);
}
.card-header { display: flex; align-items: flex-start; justify-content: space-between; gap: var(--cs-space-3); flex-wrap: wrap; }
h1 { margin: 0 0 4px; font-size: var(--cs-text-xl); color: var(--cs-ink); }
.muted { margin: 0; font-size: var(--cs-text-sm); color: var(--cs-ink-soft); }
.mark-all {
  height: 38px; padding: 0 var(--cs-space-4); border: 1px solid var(--cs-line-strong); border-radius: var(--cs-radius-sm); background: var(--cs-surface);
  color: var(--cs-ink); font: inherit; font-size: var(--cs-text-sm); font-weight: 700; cursor: pointer;
}
.mark-all:hover:not(:disabled) { border-color: var(--cs-ink); }
.mark-all:disabled { opacity: 0.5; cursor: default; }
.mark-all:focus-visible { outline: 2px solid var(--cs-signal); outline-offset: 2px; }
.empty {
  margin: 0; padding: var(--cs-space-7) var(--cs-space-4); text-align: center; font-size: var(--cs-text-base); color: var(--cs-ink-soft);
  border: 1px solid var(--cs-line); border-radius: var(--cs-radius-sm);
}
.list { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; }
.item {
  position: relative; display: flex; gap: var(--cs-space-3); padding: var(--cs-space-4) var(--cs-space-3) var(--cs-space-4) var(--cs-space-7);
  border-top: 1px solid var(--cs-line);
}
.item:first-child { border-top: 0; }
.item.unread { background: var(--cs-signal-tint); }
.dot { position: absolute; left: 10px; top: 20px; width: 8px; height: 8px; border-radius: 50%; background: var(--cs-signal); }
.body { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.message {
  margin: 0; padding: 0; border: 0; background: none; text-align: left;
  font: inherit; font-size: var(--cs-text-base); color: var(--cs-ink-soft); overflow-wrap: anywhere;
}
.unread .message { color: var(--cs-ink); font-weight: 700; }
button.message { cursor: pointer; }
button.message:hover { text-decoration: underline; }
button.message:focus-visible { outline: 2px solid var(--cs-signal); outline-offset: 2px; }
.meta { display: flex; align-items: center; gap: var(--cs-space-4); flex-wrap: wrap; font-size: var(--cs-text-xs); color: var(--cs-ink-soft); }
.entity-link { color: var(--cs-signal-strong); font-weight: 600; }
.error { margin: 0; color: var(--cs-occupied); font-size: var(--cs-text-sm); }
@media (max-width: 600px) { .card { padding: var(--cs-space-5) var(--cs-space-4); } }
</style>
