import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../lib/supabaseClient', () => ({
  supabase: {
    auth: {
      getSession: vi.fn(),
      signOut: vi.fn(),
      signInWithPassword: vi.fn(),
    },
  },
}))

import { supabase } from '../lib/supabaseClient'
import { ROUTE_ACCESS } from '../lib/roles'
import { createAppRouter } from './index'

// A fresh router per test -- see createAppRouter()'s own comment on why
// reusing one shared instance across tests is unsafe here (a same-route
// push is a silent no-op that skips the guard entirely).
let router

function mockSession(present) {
  supabase.auth.getSession.mockResolvedValue({ data: { session: present ? { access_token: 'tok' } : null } })
}

function mockMe(rolesOrRole) {
  const roles = Array.isArray(rolesOrRole) ? rolesOrRole : [rolesOrRole]
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ id: 'u1', email: 'a@b.com', name: 'Ann', roles }),
  })
}

// This file tests the fix for the most serious finding from the code
// review: only the NAV LINK was role-filtered (DashboardView.vue) --
// the route itself had no guard, so an authenticated user of any role
// could reach e.g. /events/reassign by typing the URL directly, using a
// bookmark, or browser back/forward. router/index.js's beforeEach now
// checks `to.meta.roles` (sourced from roles.js's ROUTE_ACCESS) for this.
describe('router: authentication and role-based route guarding', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    supabase.auth.signOut.mockResolvedValue({ error: null })
    router = createAppRouter()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('an unauthenticated user hitting a protected route is sent to /login', async () => {
    mockSession(false)
    await router.push('/events')
    expect(router.currentRoute.value.name).toBe('login')
  })

  it('/login itself is reachable without a session (public route)', async () => {
    mockSession(false)
    await router.push('/login')
    expect(router.currentRoute.value.name).toBe('login')
  })

  it('an already-authenticated user visiting /login is bounced to /dashboard', async () => {
    mockSession(true)
    mockMe('event_organizer')
    await router.push('/login')
    expect(router.currentRoute.value.name).toBe('dashboard')
  })

  it('the dashboard route has no role restriction -- any authenticated role can reach it', async () => {
    mockSession(true)
    mockMe('attendee')
    await router.push('/')
    expect(router.currentRoute.value.name).toBe('dashboard')
  })

  describe('role-gated routes', () => {
    it('a role WITHOUT access to a gated route is redirected to /dashboard, not served the page', async () => {
      mockSession(true)
      mockMe('attendee')
      await router.push('/events/reassign')
      expect(router.currentRoute.value.name).toBe('dashboard')
    })

    it('a role WITH access reaches the route directly', async () => {
      mockSession(true)
      mockMe('event_coordinator')
      await router.push('/events/reassign')
      expect(router.currentRoute.value.name).toBe('reassign-coordinator')
    })

    it('venue_staff can reach /venues but not /events/reassign', async () => {
      mockSession(true)
      mockMe('venue_staff')
      await router.push('/venues')
      expect(router.currentRoute.value.name).toBe('venues')

      await router.push('/events/reassign')
      expect(router.currentRoute.value.name).toBe('dashboard')
    })

    it('event_organizer can reach /events but not /venues or /events/reassign', async () => {
      mockSession(true)
      mockMe('event_organizer')

      await router.push('/events')
      expect(router.currentRoute.value.name).toBe('events')

      await router.push('/venues')
      expect(router.currentRoute.value.name).toBe('dashboard')

      await router.push('/events/reassign')
      expect(router.currentRoute.value.name).toBe('dashboard')
    })

    it('a multi-role user reaches a route via EITHER of their roles, not just roles[0] (the exact case Terry flagged)', async () => {
      mockSession(true)
      // 'attendee' listed FIRST -- if the guard incorrectly used
      // roles[0], this user would wrongly be denied /venues.
      mockMe(['attendee', 'venue_staff'])
      await router.push('/venues')
      expect(router.currentRoute.value.name).toBe('venues')
    })

    it('a user with an unrecognised/future role is denied a gated route rather than the check throwing', async () => {
      mockSession(true)
      mockMe('some_future_role')
      await router.push('/events/reassign')
      expect(router.currentRoute.value.name).toBe('dashboard')
    })
  })

  // /create-event used to carry its own inline `meta.roles` and a
  // hardcoded nav v-if -- a second copy of a decision ROUTE_ACCESS now
  // owns. These tests hold the behaviour steady across that unification.
  describe('/create-event (organiser only)', () => {
    it('an organiser reaches it', async () => {
      mockSession(true)
      mockMe('event_organizer')
      await router.push('/create-event')
      expect(router.currentRoute.value.name).toBe('create-event')
    })

    it.each(['event_coordinator', 'venue_staff', 'technical_support_staff', 'attendee'])(
      '%s is redirected to /dashboard, not served the form',
      async (role) => {
        mockSession(true)
        mockMe(role)
        await router.push('/create-event')
        expect(router.currentRoute.value.name).toBe('dashboard')
      },
    )

    it('a multi-role user reaches it via the organiser role even when it is listed LAST (no roles[0] assumption)', async () => {
      mockSession(true)
      mockMe(['event_coordinator', 'event_organizer'])
      await router.push('/create-event')
      expect(router.currentRoute.value.name).toBe('create-event')
    })

    it('an unauthenticated visitor is sent to /login, not to the dashboard', async () => {
      mockSession(false)
      await router.push('/create-event')
      expect(router.currentRoute.value.name).toBe('login')
    })
  })

  describe('/events/:eventId (event-details)', () => {
    it('an organiser reaches it and the id arrives as a route param', async () => {
      mockSession(true)
      mockMe('event_organizer')
      await router.push('/events/abc-123')
      expect(router.currentRoute.value.name).toBe('event-details')
      expect(router.currentRoute.value.params.eventId).toBe('abc-123')
    })

    it('a coordinator reaches it', async () => {
      mockSession(true)
      mockMe('event_coordinator')
      await router.push('/events/abc-123')
      expect(router.currentRoute.value.name).toBe('event-details')
    })

    it.each(['venue_staff', 'technical_support_staff', 'attendee'])(
      '%s is redirected to /dashboard (previously this route had no role gate at all)',
      async (role) => {
        mockSession(true)
        mockMe(role)
        await router.push('/events/abc-123')
        expect(router.currentRoute.value.name).toBe('dashboard')
      },
    )

    it('an unauthenticated visitor is sent to /login', async () => {
      mockSession(false)
      await router.push('/events/abc-123')
      expect(router.currentRoute.value.name).toBe('login')
    })

    it('a percent-encoded id is decoded into the param rather than breaking the route', async () => {
      mockSession(true)
      mockMe('event_organizer')
      await router.push('/events/a%20b')
      expect(router.currentRoute.value.name).toBe('event-details')
      expect(router.currentRoute.value.params.eventId).toBe('a b')
    })
  })

  // The sharpest regression guard here: if the dynamic /events/:eventId
  // ever swallowed the static /events/reassign, an ORGANISER (allowed on
  // event-details, denied on reassign) would suddenly be let through to a
  // page treating the literal string "reassign" as an event id.
  describe('static /events/reassign is never swallowed by /events/:eventId', () => {
    it('a coordinator lands on reassign-coordinator, not event-details', async () => {
      mockSession(true)
      mockMe('event_coordinator')
      await router.push('/events/reassign')
      expect(router.currentRoute.value.name).toBe('reassign-coordinator')
    })

    it('an organiser is DENIED (dashboard) -- not let through to event-details with eventId="reassign"', async () => {
      mockSession(true)
      mockMe('event_organizer')
      await router.push('/events/reassign')
      expect(router.currentRoute.value.name).toBe('dashboard')
    })

    it('a trailing slash resolves the same way (coordinator allowed, organiser denied)', async () => {
      mockSession(true)
      mockMe('event_coordinator')
      await router.push('/events/reassign/')
      expect(router.currentRoute.value.name).toBe('reassign-coordinator')

      const organiserRouter = createAppRouter()
      setActivePinia(createPinia())
      mockMe('event_organizer')
      await organiserRouter.push('/events/reassign/')
      expect(organiserRouter.currentRoute.value.name).toBe('dashboard')
    })
  })

  // Deny-by-default drift guard. ROUTE_ACCESS is a hand-maintained table
  // that has to be kept in step with the route list; these fail loudly
  // (naming the route and the fix) the moment either side changes alone,
  // rather than leaving a new page silently reachable by every role.
  describe('route table vs ROUTE_ACCESS (drift guard)', () => {
    const OPEN_ROUTES = ['login', 'dashboard'] // intentionally not role-gated

    it('every ROUTE_ACCESS entry names a route that is really registered', () => {
      for (const entry of ROUTE_ACCESS) {
        expect(router.hasRoute(entry.routeName), `ROUTE_ACCESS lists "${entry.routeName}" but no such route is registered`).toBe(true)
      }
    })

    it('every registered route except login/dashboard has an ROUTE_ACCESS entry -- a new route added without one would be reachable by ALL roles', () => {
      const byName = new Map(ROUTE_ACCESS.map((e) => [e.routeName, e]))
      for (const route of router.getRoutes()) {
        if (OPEN_ROUTES.includes(route.name)) continue
        expect(
          byName.has(route.name),
          `route "${String(route.name)}" (${route.path}) has no ROUTE_ACCESS entry in src/lib/roles.js -- add one, or it is open to every role`,
        ).toBe(true)
      }
    })

    it("each route's meta.roles is exactly what ROUTE_ACCESS says (no inline copy that can diverge)", () => {
      for (const entry of ROUTE_ACCESS) {
        const route = router.getRoutes().find((r) => r.name === entry.routeName)
        expect(route.meta.roles).toEqual(entry.roles)
      }
    })

    it('login is public and dashboard has no role restriction', () => {
      const login = router.getRoutes().find((r) => r.name === 'login')
      const dashboard = router.getRoutes().find((r) => r.name === 'dashboard')
      expect(login.meta.public).toBe(true)
      expect(login.meta.roles).toBeUndefined()
      expect(dashboard.meta.roles).toBeUndefined()
    })
  })
})
