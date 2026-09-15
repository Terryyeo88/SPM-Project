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
// checks `to.meta.roles` (sourced from roles.js's NAV_LINKS) for this.
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
})
