import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('../lib/supabaseClient', () => ({
  supabase: {
    auth: {
      signInWithPassword: vi.fn(),
      signOut: vi.fn(),
      getSession: vi.fn(),
    },
  },
}))

vi.mock('../lib/api', () => ({
  apiGet: vi.fn(),
}))

import { supabase } from '../lib/supabaseClient'
import { apiGet } from '../lib/api'
import { useAuthStore } from './auth'

const SESSION = { access_token: 'tok', user: { id: 'u1' } }
const PROFILE = { id: 'u1', email: 'a@b.com', name: 'Ann', roles: ['event_coordinator'] }

describe('auth store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    // restoreSession()'s non-auth-error branch intentionally
    // console.error()s (see stores/auth.js's own comment on why) --
    // silenced here so a deliberately-triggered, expected error path
    // doesn't clutter test output the way an unexpected one should.
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('signIn', () => {
    it('on success, sets the session and loads the profile', async () => {
      supabase.auth.signInWithPassword.mockResolvedValue({ data: { session: SESSION }, error: null })
      apiGet.mockResolvedValue(PROFILE)

      const auth = useAuthStore()
      await auth.signIn('a@b.com', 'pw')

      expect(auth.session).toEqual(SESSION)
      expect(auth.profile).toEqual(PROFILE)
      expect(auth.isLoggedIn).toBe(true)
    })

    it('on bad credentials, throws and leaves session/profile untouched', async () => {
      supabase.auth.signInWithPassword.mockResolvedValue({ data: {}, error: new Error('Invalid credentials') })

      const auth = useAuthStore()
      await expect(auth.signIn('a@b.com', 'wrong')).rejects.toThrow('Invalid credentials')
      expect(auth.session).toBeNull()
      expect(auth.profile).toBeNull()
      expect(apiGet).not.toHaveBeenCalled()
    })

    it('if the subsequent /me call fails, the error still propagates to the caller (LoginView relies on this to show a message)', async () => {
      supabase.auth.signInWithPassword.mockResolvedValue({ data: { session: SESSION }, error: null })
      const err = new Error('/me is down')
      err.code = 'internal_error'
      apiGet.mockRejectedValue(err)

      const auth = useAuthStore()
      await expect(auth.signIn('a@b.com', 'pw')).rejects.toThrow('/me is down')
      // Session WAS set (Supabase sign-in itself succeeded) even though
      // profile never loaded -- documenting the actual behaviour, not
      // asserting an "ideal" one this test would be inventing.
      expect(auth.session).toEqual(SESSION)
      expect(auth.profile).toBeNull()
    })
  })

  describe('signOut', () => {
    it('signs out of Supabase and clears local state', async () => {
      supabase.auth.signOut.mockResolvedValue({ error: null })
      const auth = useAuthStore()
      auth.session = SESSION
      auth.profile = PROFILE

      await auth.signOut()

      expect(supabase.auth.signOut).toHaveBeenCalledTimes(1)
      expect(auth.session).toBeNull()
      expect(auth.profile).toBeNull()
    })

    it('still clears local state even if the Supabase signOut call itself fails, though the error still propagates', async () => {
      supabase.auth.signOut.mockRejectedValue(new Error('network down'))
      const auth = useAuthStore()
      auth.session = SESSION
      auth.profile = PROFILE

      await expect(auth.signOut()).rejects.toThrow('network down')
      expect(auth.session).toBeNull()
      expect(auth.profile).toBeNull()
    })
  })

  describe('clearLocalState', () => {
    it('nulls session and profile without touching Supabase', () => {
      const auth = useAuthStore()
      auth.session = SESSION
      auth.profile = PROFILE
      auth.clearLocalState()
      expect(auth.session).toBeNull()
      expect(auth.profile).toBeNull()
      expect(supabase.auth.signOut).not.toHaveBeenCalled()
    })
  })

  describe('restoreSession', () => {
    it('with no stored Supabase session: sets session null, never calls loadProfile, marks restored', async () => {
      supabase.auth.getSession.mockResolvedValue({ data: { session: null } })
      const auth = useAuthStore()

      await auth.restoreSession()

      expect(auth.session).toBeNull()
      expect(apiGet).not.toHaveBeenCalled()
      expect(auth.restored).toBe(true)
      expect(auth.profileLoadError).toBeNull()
    })

    it('with a stored session and a successful /me: loads the profile, no error', async () => {
      supabase.auth.getSession.mockResolvedValue({ data: { session: SESSION } })
      apiGet.mockResolvedValue(PROFILE)
      const auth = useAuthStore()

      await auth.restoreSession()

      expect(auth.session).toEqual(SESSION)
      expect(auth.profile).toEqual(PROFILE)
      expect(auth.restored).toBe(true)
      expect(auth.profileLoadError).toBeNull()
    })

    // -- The exact bug four independent code reviewers converged on:
    // the original bare `catch {}` swallowed every failure, including
    // ones that were never supposed to be swallowed. These two tests
    // are the regression coverage for that fix. --

    it('when /me fails with an auth_* code (session itself is invalid), clears local state so the router guard redirects to login', async () => {
      supabase.auth.getSession.mockResolvedValue({ data: { session: SESSION } })
      const err = new Error('Token signature is invalid.')
      err.code = 'auth_invalid_signature'
      apiGet.mockRejectedValue(err)
      const auth = useAuthStore()

      await auth.restoreSession()

      expect(auth.session).toBeNull()
      expect(auth.profile).toBeNull()
      expect(auth.restored).toBe(true)
      // NOT surfaced as a load error -- this is a "you're logged out"
      // case, not a "something broke while you were logged in" case.
      expect(auth.profileLoadError).toBeNull()
    })

    it('when /me fails with a NON-auth error (network outage, backend 500), does NOT clear the session, and surfaces profileLoadError instead', async () => {
      supabase.auth.getSession.mockResolvedValue({ data: { session: SESSION } })
      const err = new Error('Backend unreachable')
      // No .code at all -- simulates a raw network failure just as much
      // as a recognised-but-non-auth backend error code would.
      apiGet.mockRejectedValue(err)
      const auth = useAuthStore()

      await auth.restoreSession()

      // The critical assertion: session must NOT be wiped over a
      // transient failure that says nothing about whether the token
      // itself is valid.
      expect(auth.session).toEqual(SESSION)
      expect(auth.isLoggedIn).toBe(true)
      expect(auth.profile).toBeNull()
      expect(auth.profileLoadError).toBe('Backend unreachable')
      expect(auth.restored).toBe(true)
    })

    it('a fresh restoreSession() call clears a stale profileLoadError from a previous failed attempt once it succeeds', async () => {
      supabase.auth.getSession.mockResolvedValue({ data: { session: SESSION } })
      apiGet.mockRejectedValueOnce(new Error('first attempt fails'))
      const auth = useAuthStore()
      await auth.restoreSession()
      expect(auth.profileLoadError).toBe('first attempt fails')

      apiGet.mockResolvedValueOnce(PROFILE)
      await auth.restoreSession()
      expect(auth.profileLoadError).toBeNull()
      expect(auth.profile).toEqual(PROFILE)
    })

    // -- Re-entrancy: api.js's forced-logout redirect can call back into
    // the router guard, which calls restoreSession() again, WHILE the
    // first call is still in flight (see router/index.js's own comment
    // on this). Without the in-flight guard, this duplicates the /me
    // call and the whole forced-logout cycle. --

    it('concurrent restoreSession() calls share ONE in-flight attempt -- loadProfile only runs once', async () => {
      supabase.auth.getSession.mockResolvedValue({ data: { session: SESSION } })
      apiGet.mockResolvedValue(PROFILE)
      const auth = useAuthStore()

      // Fired back-to-back, synchronously, before either has a chance to
      // resolve -- restoreSession()'s in-flight guard is set
      // synchronously (before its first internal `await`), so the
      // SECOND call here must see it already set and just await the
      // SAME promise rather than starting its own independent restore.
      const first = auth.restoreSession()
      const second = auth.restoreSession()
      await Promise.all([first, second])

      expect(apiGet).toHaveBeenCalledTimes(1)
      expect(auth.profile).toEqual(PROFILE)
      expect(auth.restored).toBe(true)
    })

    it('a SECOND, sequential (non-overlapping) restoreSession() call DOES re-fetch -- the guard only dedupes genuinely concurrent calls, not repeat visits', async () => {
      supabase.auth.getSession.mockResolvedValue({ data: { session: SESSION } })
      apiGet.mockResolvedValue(PROFILE)
      const auth = useAuthStore()

      await auth.restoreSession()
      await auth.restoreSession()

      expect(apiGet).toHaveBeenCalledTimes(2)
    })
  })
})
