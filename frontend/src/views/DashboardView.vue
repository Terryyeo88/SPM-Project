<script setup>
import { computed } from 'vue'
import { useAuthStore } from '../stores/auth'
import { NAV_LINKS, ROLES, hasAnyRole, navRoles } from '../lib/roles'
import AppNavBar from '../components/AppNavBar.vue'
import CoordinatorDashboard from './dashboard/CoordinatorDashboard.vue'
import LeadDashboard from './dashboard/LeadDashboard.vue'
import AttendeeDashboard from './dashboard/AttendeeDashboard.vue'
import SafetyOfficerDashboard from './dashboard/SafetyOfficerDashboard.vue'

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
// Week 7 change #5: the Event Coordinator Lead's own dashboard (unassigned
// queue / assignments per coordinator / past), also instead of nav links.
const isLead = computed(() => hasAnyRole(auth.roles, [ROLES.EVENT_COORDINATOR_LEAD]))
// Attendee Registration: the attendee's dashboard (Dashboard-Attendee wireframe).
const isAttendee = computed(() => hasAnyRole(auth.roles, [ROLES.ATTENDEE]))
// Week 7 change #6: the Safety Officer's dashboard (Check Safety / Checked).
const isSafetyOfficer = computed(() => hasAnyRole(auth.roles, [ROLES.SAFETY_OFFICER]))
</script>

<template>
  <div class="cs-page">
    <AppNavBar />

    <main class="cs-content">
      <div class="cs-container">
        <section v-if="auth.profile" class="welcome">
          <span class="cs-eyebrow">Dashboard</span>
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
        <p v-else-if="auth.profile && !isCoordinator && !isLead && !isAttendee && !isSafetyOfficer" class="no-sections">
          Nothing's been built yet for your role(s) this sprint -- see docs/traceability.md's
          "Explicitly deferred" section.
        </p>

        <AttendeeDashboard v-if="isAttendee" />
        <SafetyOfficerDashboard v-if="isSafetyOfficer" />
        <LeadDashboard v-if="isLead" />
        <CoordinatorDashboard v-if="isCoordinator" />
      </div>
    </main>
  </div>
</template>

<style scoped>
.welcome {
  display: flex;
  flex-direction: column;
  gap: var(--cs-space-2);
}
.title {
  font-family: var(--cs-font-display);
  font-size: var(--cs-text-xl);
  font-weight: 700;
  color: var(--cs-ink);
}
.sections {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: var(--cs-space-3);
}
.section-card {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: var(--cs-surface);
  border: 1px solid var(--cs-line);
  border-radius: var(--cs-radius-md);
  padding: var(--cs-space-5) var(--cs-space-4);
  text-decoration: none;
  color: var(--cs-ink);
  font-size: var(--cs-text-base);
  font-weight: 600;
  transition: border-color 120ms ease;
}
.section-card:hover {
  border-color: var(--cs-signal);
}
.section-card:hover .section-arrow {
  color: var(--cs-signal);
}
.section-arrow {
  color: var(--cs-line-strong);
  font-family: var(--cs-font-display);
  transition: color 120ms ease;
}
.no-sections {
  margin: 0;
  color: var(--cs-ink-soft);
  font-size: var(--cs-text-sm);
}
.load-error {
  margin: 0;
  color: var(--cs-occupied);
  font-size: var(--cs-text-sm);
}
</style>
