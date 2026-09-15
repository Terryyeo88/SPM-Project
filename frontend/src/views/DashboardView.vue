<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { NAV_LINKS, hasAnyRole } from '../lib/roles'

const auth = useAuthStore()
const router = useRouter()

// IS-27's "routed to a view appropriate to their role" criterion: this
// is the one Dashboard route everyone lands on after login, and ITS
// CONTENT is what adapts by role -- see roles.js's module docstring for
// why no separate per-role page was built. `hasAnyRole` is a union
// check, so a user holding multiple roles (e.g. Coordinator AND Venue
// Staff) sees the union of what either role unlocks, not just whatever
// `roles[0]` happens to be.
const visibleLinks = computed(() => NAV_LINKS.filter((link) => hasAnyRole(auth.roles, link.roles)))

async function handleSignOut() {
  await auth.signOut()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="dashboard">
    <header>
      <h1>ConnectSphere</h1>
      <button @click="handleSignOut">Sign out</button>
    </header>

    <section v-if="auth.profile">
      <p>
        Signed in as <strong>{{ auth.profile.name }}</strong> ({{ auth.profile.email }})
      </p>
      <p>Roles: {{ auth.profile.roles.join(', ') || 'none' }}</p>
    </section>

    <nav v-if="visibleLinks.length">
      <router-link v-for="link in visibleLinks" :key="link.routeName" :to="link.to">
        {{ link.label }}
      </router-link>
    </nav>
    <p v-else class="no-sections">
      Nothing's been built yet for your role(s) this sprint -- see docs/traceability.md's
      "Explicitly deferred" section.
    </p>
  </div>
</template>

<style scoped>
.dashboard {
  max-width: 640px;
  margin: 2rem auto;
  padding: 0 1rem;
}
header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
nav {
  display: flex;
  gap: 1rem;
  margin-top: 1.5rem;
}
.no-sections {
  margin-top: 1.5rem;
  color: #666;
  font-size: 0.9rem;
}
</style>
