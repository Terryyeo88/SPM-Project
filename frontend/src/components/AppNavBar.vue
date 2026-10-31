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
        <span class="logo">LOGO</span>
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
  background: #ffffff;
  border-bottom: 1px dashed #9a9a9a;
}
.navbar-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 16px;
  min-height: 64px;
  display: flex;
  align-items: center;
  gap: 24px;
  flex-wrap: wrap;
  box-sizing: border-box;
}
.brand {
  display: flex;
  align-items: center;
  gap: 10px;
  text-decoration: none;
}
.logo {
  width: 32px;
  height: 32px;
  border: 1px dashed #9a9a9a;
  border-radius: 4px;
  background: #f5f5f5;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 8px;
  color: #9a9a9a;
  letter-spacing: 0.05em;
}
.brand-name {
  font-size: 16px;
  font-weight: 700;
  color: #222222;
}
.links {
  flex: 1 1 auto;
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
}
.link {
  font-size: 13px;
  font-weight: 600;
  color: #666666;
  text-decoration: none;
  padding: 7px 12px;
  border-radius: 4px;
}
.link:hover {
  background: #f0f0f0;
  color: #222222;
}
.link.active {
  background: #444444;
  color: #ffffff;
}
.account {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-left: auto;
}
.role-badge {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: #6a6a6a;
  border: 1px solid #d8d8d8;
  border-radius: 12px;
  padding: 4px 10px;
  background: #f7f7f7;
}
.avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: 1px solid #9a9a9a;
  background: #f5f5f5;
  color: #6a6a6a;
  display: flex;
  align-items: center;
  justify-content: center;
}
.avatar:hover,
.avatar.router-link-active {
  border-color: #2568e8;
  color: #2568e8;
}
.avatar:focus-visible {
  outline: 2px solid #2568e8;
  outline-offset: 2px;
}
.bell {
  position: relative;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  color: #6a6a6a;
  display: flex;
  align-items: center;
  justify-content: center;
}
.bell:hover,
.bell.router-link-active {
  background: #f0f0f0;
  color: #2568e8;
}
.bell:focus-visible {
  outline: 2px solid #2568e8;
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
  border-radius: 9px;
  background: #c0362c;
  color: #ffffff;
  font-size: 11px;
  font-weight: 700;
  line-height: 18px;
  text-align: center;
}
</style>
