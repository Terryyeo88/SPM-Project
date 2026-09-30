<script setup>
import { computed } from 'vue'
import { useAuthStore } from '../stores/auth'
import { NAV_LINKS, ROLES, hasAnyRole, navRoles } from '../lib/roles'
import AppNavBar from '../components/AppNavBar.vue'
import CoordinatorDashboard from './dashboard/CoordinatorDashboard.vue'

const auth = useAuthStore()

// IS-27's "routed to a view appropriate to their role" criterion: this
// is the one Dashboard route everyone lands on after login, and ITS
// CONTENT is what adapts by role -- see roles.js's module docstring for
// why no separate per-role page was built. `hasAnyRole` is a union
// check, so a user holding multiple roles (e.g. Coordinator AND Venue
// Staff) sees the union of what either role unlocks, not just whatever
// `roles[0]` happens to be. The links themselves live in AppNavBar
// (which filters NAV_LINKS the same way); this copy drives the section
// cards below and the "nothing built for your role" fallback. navRoles()
// leaves out the coordinator role -- per the coordinator wireframe a
// coordinator gets the "My Assigned Events" dashboard instead of links.
const visibleLinks = computed(() => NAV_LINKS.filter((link) => hasAnyRole(navRoles(auth.roles), link.roles)))
const isCoordinator = computed(() => hasAnyRole(auth.roles, [ROLES.EVENT_COORDINATOR]))
</script>

<template>
  <div class="page">
    <AppNavBar />

    <main class="content">
      <div class="container">
        <section v-if="auth.profile" class="welcome">
          <span class="title">Welcome, {{ auth.profile.name }}</span>
        </section>
        <!-- Distinct from the "nothing built for your role" case below: this
        is a genuine error (network/backend failure while loading /me), not
        an access decision -- see stores/auth.js's profileLoadError. -->
        <p v-else-if="auth.profileLoadError" class="load-error">
          Couldn't load your profile: {{ auth.profileLoadError }} -- try refreshing.
        </p>

        <div v-if="visibleLinks.length" class="sections">
          <router-link
            v-for="link in visibleLinks"
            :key="link.routeName"
            :to="{ name: link.routeName }"
            class="section-card"
          >
            <span class="section-label">{{ link.label }}</span>
            <span class="section-arrow">&rarr;</span>
          </router-link>
        </div>
        <!-- v-else-if (not v-else) on auth.profile specifically: only claims
        "nothing built for your role" once we actually KNOW the roles (a
        genuinely empty match), never while profile is still null/failed --
        that case is the message above instead. -->
        <p v-else-if="auth.profile && !isCoordinator" class="no-sections">
          Nothing's been built yet for your role(s) this sprint -- see docs/traceability.md's
          "Explicitly deferred" section.
        </p>

        <CoordinatorDashboard v-if="isCoordinator" />
      </div>
    </main>
  </div>
</template>

<style scoped>
.page {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  background: #eeeeee;
}
.content {
  flex: 1 1 auto;
  padding: 32px 16px;
  display: flex;
  justify-content: center;
}
.container {
  width: 100%;
  max-width: 880px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.welcome {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.title {
  font-size: 20px;
  font-weight: 700;
  color: #1f1f1f;
}
.subtitle {
  font-size: 13px;
  color: #8a8a8a;
}
.sections {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 12px;
}
.section-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #ffffff;
  border: 1px dashed #9a9a9a;
  border-radius: 6px;
  padding: 20px 18px;
  text-decoration: none;
  color: #2a2a2a;
  font-size: 14px;
  font-weight: 600;
}
.section-card:hover {
  border-style: solid;
  border-color: #444444;
}
.section-arrow {
  color: #9a9a9a;
}
.no-sections {
  margin: 0;
  color: #666666;
  font-size: 13px;
}
.load-error {
  margin: 0;
  color: #c0392b;
  font-size: 13px;
}
</style>
