<script setup>
import { computed, onMounted } from 'vue'
import { useAuthStore } from '../stores/auth'
import { useNotificationStore } from '../stores/notifications'
import { NAV_LINKS, hasAnyRole, navRoles, roleLabel } from '../lib/roles'

const auth = useAuthStore()
const notifications = useNotificationStore()

// Same role-filtered NAV_LINKS the dashboard has always used -- see
// roles.js's ROUTE_ACCESS for why the nav and the router guard both read
// from that one table. `hasAnyRole` is a union check, so a multi-role
// user sees every link any of their roles unlocks.
// navRoles() leaves out the coordinator role: per the coordinator
// wireframe a coordinator has no nav links (they work from their
// dashboard), so a coordinator-only user sees just the logo + account.
const visibleLinks = computed(() => NAV_LINKS.filter((link) => hasAnyRole(navRoles(auth.roles), link.roles)))

// Role badge text, e.g. "Event Coordinator" (joined for multi-role users).
const roleText = computed(() => auth.roles.map(roleLabel).join(' · '))

// Sign out now lives on the profile page (per the wireframe, the header
// just shows the role and a profile icon).

// Notifications bell (IS-69): every signed-in role has one. The count is
// fetched each time a page mounts the nav bar (GET /notifications/unread-
// count); the notifications page updates the same store from its own
// responses. A failed fetch just leaves the bell without a count.
const unreadCount = computed(() => notifications.unreadCount ?? 0)
const unreadBadge = computed(() => (unreadCount.value > 99 ? '99+' : String(unreadCount.value)))

onMounted(() => {
  if (auth.isLoggedIn) notifications.refreshUnreadCount().catch(() => {})
})
</script>

<template>
  <header class="navbar">
    <div class="navbar-inner">
      <router-link :to="{ name: 'dashboard' }" class="brand">
        <span class="logo" aria-hidden="true">CS</span>
        <span class="brand-name">ConnectSphere</span>
      </router-link>

      <nav v-if="visibleLinks.length" class="links">
        <router-link :to="{ name: 'dashboard' }" class="link" exact-active-class="active">Dashboard</router-link>
        <router-link
          v-for="link in visibleLinks"
          :key="link.routeName"
          :to="{ name: link.routeName }"
          class="link"
          exact-active-class="active"
        >
          {{ link.label }}
        </router-link>
      </nav>

      <div class="account">
        <span v-if="roleText" class="role-badge">{{ roleText }}</span>
        <router-link
          v-if="auth.isLoggedIn"
          :to="{ name: 'notifications' }"
          class="bell"
          data-test="notification-bell"
          :aria-label="unreadCount ? `Notifications (${unreadCount} unread)` : 'Notifications'"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
            stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
            <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
          </svg>
          <span v-if="unreadCount" class="bell-count" data-test="unread-count">{{ unreadBadge }}</span>
        </router-link>
        <router-link
          :to="{ name: 'profile' }"
          class="avatar"
          :aria-label="auth.profile ? `Your profile (${auth.profile.name})` : 'Your profile'"
          :title="auth.profile?.name"
        >
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
            stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <circle cx="12" cy="8" r="4" />
            <path d="M4 20c0-4 3.5-7 8-7s8 3 8 7" />
          </svg>
        </router-link>
      </div>
    </div>
  </header>
</template>

<style scoped>
.navbar {
  background: var(--cs-surface);
  border-bottom: 1px solid var(--cs-line);
}
.navbar-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 var(--cs-space-4);
  min-height: 64px;
  display: flex;
  align-items: center;
  gap: var(--cs-space-6);
  flex-wrap: wrap;
  box-sizing: border-box;
}
.brand {
  display: flex;
  align-items: center;
  gap: var(--cs-space-2);
  text-decoration: none;
}
/* The corner-tick registration mark, same device as .cs-card, used here
   at the mark's own natural scale -- a small square instead of a card --
   so the brand itself carries the same "floor-plan sheet" motif that
   recurs through every bounded panel in the app. */
.logo {
  width: 30px;
  height: 30px;
  border-radius: var(--cs-radius-sm);
  background: var(--cs-ink);
  color: var(--cs-paper);
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--cs-font-display);
  font-weight: 700;
  font-size: 14px;
}
.brand-name {
  font-family: var(--cs-font-display);
  font-size: 18px;
  font-weight: 700;
  color: var(--cs-ink);
  letter-spacing: -0.01em;
}
.links {
  flex: 1 1 auto;
  display: flex;
  align-items: center;
  gap: var(--cs-space-1);
  flex-wrap: wrap;
}
.link {
  font-size: var(--cs-text-sm);
  font-weight: 600;
  color: var(--cs-ink-soft);
  text-decoration: none;
  padding: 7px 12px;
  border-radius: var(--cs-radius-sm);
}
.link:hover {
  background: var(--cs-paper);
  color: var(--cs-ink);
}
.link.active {
  background: var(--cs-ink);
  color: var(--cs-paper);
}
.account {
  display: flex;
  align-items: center;
  gap: var(--cs-space-3);
  margin-left: auto;
}
.role-badge {
  font-family: var(--cs-font-mono);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--cs-ink-soft);
  border: 1px solid var(--cs-line);
  border-radius: var(--cs-radius-full);
  padding: 4px 10px;
  background: var(--cs-paper);
}
.avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: 1px solid var(--cs-line);
  background: var(--cs-paper);
  color: var(--cs-ink-soft);
  display: flex;
  align-items: center;
  justify-content: center;
}
.avatar:hover,
.avatar.router-link-active {
  border-color: var(--cs-signal);
  color: var(--cs-signal);
}
.avatar:focus-visible {
  outline: 2px solid var(--cs-signal);
  outline-offset: 2px;
}
.bell {
  position: relative;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  color: var(--cs-ink-soft);
  display: flex;
  align-items: center;
  justify-content: center;
}
.bell:hover,
.bell.router-link-active {
  background: var(--cs-paper);
  color: var(--cs-signal);
}
.bell:focus-visible {
  outline: 2px solid var(--cs-signal);
  outline-offset: 2px;
}
.bell-count {
  position: absolute;
  top: 0;
  right: -2px;
  min-width: 18px;
  height: 18px;
  box-sizing: border-box;
  padding: 0 5px;
  border-radius: var(--cs-radius-full);
  background: var(--cs-occupied);
  color: #ffffff;
  font-size: 11px;
  font-weight: 700;
  line-height: 18px;
  text-align: center;
}
</style>
