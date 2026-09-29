<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { NAV_LINKS, hasAnyRole } from '../lib/roles'

const auth = useAuthStore()
const router = useRouter()

// Same role-filtered NAV_LINKS the dashboard has always used -- see
// roles.js's ROUTE_ACCESS for why the nav and the router guard both read
// from that one table. `hasAnyRole` is a union check, so a multi-role
// user sees every link any of their roles unlocks.
const visibleLinks = computed(() => NAV_LINKS.filter((link) => hasAnyRole(auth.roles, link.roles)))

async function handleSignOut() {
  // try/finally: local state is already cleared by auth.signOut() even
  // if its Supabase network call failed (see the store's own comment),
  // so the user should still land on /login either way rather than
  // being stranded on a page that now thinks it's logged out.
  try {
    await auth.signOut()
  } finally {
    router.push({ name: 'login' })
  }
}
</script>

<template>
  <header class="navbar">
    <div class="navbar-inner">
      <router-link :to="{ name: 'dashboard' }" class="brand">
        <span class="logo">LOGO</span>
        <span class="brand-name">ConnectSphere</span>
      </router-link>

      <nav class="links">
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
        <span v-if="auth.profile" class="user-name">{{ auth.profile.name }}</span>
        <button type="button" class="sign-out" @click="handleSignOut">Sign out</button>
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
}
.user-name {
  font-size: 13px;
  color: #666666;
}
.sign-out {
  height: 34px;
  border: 1px solid #b0b0b0;
  border-radius: 4px;
  background: #fafafa;
  color: #333333;
  font-size: 13px;
  font-weight: 600;
  padding: 0 14px;
  cursor: pointer;
}
.sign-out:hover {
  background: #f0f0f0;
}
</style>
