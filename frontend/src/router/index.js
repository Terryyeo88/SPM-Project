import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { NAV_LINKS, hasAnyRole } from '../lib/roles'
import LoginView from '../views/LoginView.vue'
import DashboardView from '../views/DashboardView.vue'
import EventsPlaceholder from '../views/events/EventsPlaceholder.vue'
import ReassignCoordinatorView from '../views/events/ReassignCoordinatorView.vue'
import VenuesPlaceholder from '../views/venues/VenuesPlaceholder.vue'

// roles.js's NAV_LINKS is the single source of truth for "which roles
// can reach this named route" -- built into a lookup here and used
// below for route-level gating, AND separately imported by
// DashboardView.vue for nav-link visibility. Reading from the same
// array means the two can never drift apart from each other (they did,
// briefly, in an earlier version of this branch: the route itself had
// no gate at all, only the nav link was hidden -- an authenticated user
// of any role could still reach e.g. /events/reassign by typing the URL
// directly). A route with no entry in NAV_LINKS has no role
// restriction -- currently just '/' and '/login'.
const _rolesByRouteName = new Map(NAV_LINKS.map((link) => [link.routeName, link.roles]))

const routes = [
  { path: '/login', name: 'login', component: LoginView, meta: { public: true } },
  { path: '/', name: 'dashboard', component: DashboardView },
  {
    path: '/events',
    name: 'events',
    component: EventsPlaceholder,
    meta: { roles: _rolesByRouteName.get('events') },
  },
  {
    path: '/events/reassign',
    name: 'reassign-coordinator',
    component: ReassignCoordinatorView,
    meta: { roles: _rolesByRouteName.get('reassign-coordinator') },
  },
  {
    path: '/venues',
    name: 'venues',
    component: VenuesPlaceholder,
    meta: { roles: _rolesByRouteName.get('venues') },
  },
]

/**
 * Builds a fresh router instance with the app's real routes and guard.
 *
 * Exported (not just the default singleton below) specifically so tests
 * can create an independent instance per test. Sharing the one singleton
 * across tests caused a real test-isolation bug during development:
 * vue-router treats pushing to the route it's ALREADY at as a no-op and
 * does NOT re-run `beforeEach` for it -- so a route left over from a
 * PREVIOUS test silently absorbed the next test's `router.push(...)`,
 * meaning that test's own mocks (and the guard logic being tested) never
 * ran at all, without any error to say so. A fresh router per test
 * sidesteps this entirely instead of trying to reset shared state by
 * hand between tests.
 */
export function createAppRouter() {
  const router = createRouter({
    history: createWebHistory(),
    routes,
  })

  router.beforeEach(async (to) => {
    const auth = useAuthStore()

    // On a hard refresh, Pinia's state is empty even though Supabase
    // still has a valid session sitting in local storage -- restore it
    // once before making any auth decisions.
    //
    // NOTE: restoreSession() can itself trigger a forced-logout redirect
    // (api.js's _handleAuthRedirect, via loadProfile() -> apiGet('/me'))
    // that calls router.push({name:'login'}) WHILE this same `await` is
    // still pending -- that re-enters this guard for the new navigation
    // before `auth.restored` is set. restoreSession() is safe against
    // that specific re-entrancy (see stores/auth.js's module-level
    // `_restoring` comment), so the worst case here is this guard's own
    // eventual `return {name:'login'}` below being a harmless duplicate
    // of a navigation that already happened.
    if (!auth.restored) {
      await auth.restoreSession()
    }

    if (!to.meta.public && !auth.isLoggedIn) {
      return { name: 'login' }
    }
    if (to.name === 'login' && auth.isLoggedIn) {
      return { name: 'dashboard' }
    }
    // Route-level role gate. Still only a UI-layer convenience, not the
    // real enforcement -- app/authz/rules.py on the backend is (e.g.
    // rule_event_reassign_coordinator) -- this just stops an
    // unauthorised role from being served a page whose every action
    // would 403/404 anyway. Redirects to dashboard rather than a
    // dedicated "forbidden" page, since none exists yet.
    if (to.meta.roles && auth.isLoggedIn && !hasAnyRole(auth.roles, to.meta.roles)) {
      return { name: 'dashboard' }
    }
  })

  return router
}

export default createAppRouter()
