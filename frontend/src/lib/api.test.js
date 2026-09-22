import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

// vi.mock() calls are hoisted above imports by Vitest's transform, so
// any outer-scope variable they close over must itself be declared via
// vi.hoisted() -- otherwise it's a TDZ reference error at module-eval
// time. This is the documented-safe pattern for exactly this situation.
const { clearLocalState, push, routerMock } = vi.hoisted(() => {
  const clearLocalState = vi.fn()
  const push = vi.fn()
  const routerMock = { currentRoute: { value: { name: 'dashboard' } }, push }
  return { clearLocalState, push, routerMock }
})

vi.mock('./supabaseClient', () => ({
  supabase: {
    auth: {
      getSession: vi.fn(),
      signOut: vi.fn(),
    },
  },
}))

// Mocks BOTH the static import in stores/auth.js's own module (not
// under test here) and api.js's dynamic import('../stores/auth') --
// Vitest's module mocking applies to a specifier regardless of whether
// the real code imports it statically or dynamically.
vi.mock('../stores/auth', () => ({
  useAuthStore: () => ({ clearLocalState }),
}))

vi.mock('../router', () => ({ default: routerMock }))

import { supabase } from './supabaseClient'
import { apiDelete, apiGet, apiPost } from './api'

function mockFetchResponse({ ok, status, body }) {
  return { ok, status, json: async () => body }
}

describe('api.js: request()/apiGet/apiPost', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    supabase.auth.getSession.mockResolvedValue({ data: { session: null } })
    supabase.auth.signOut.mockResolvedValue({ error: null })
    routerMock.currentRoute.value.name = 'dashboard'
    global.fetch = vi.fn()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('happy path', () => {
    it('apiGet resolves with the parsed JSON body on a 2xx response', async () => {
      global.fetch.mockResolvedValue(mockFetchResponse({ ok: true, status: 200, body: { id: '1' } }))
      await expect(apiGet('/me')).resolves.toEqual({ id: '1' })
    })

    it('apiGet issues a GET request to the given path', async () => {
      global.fetch.mockResolvedValue(mockFetchResponse({ ok: true, status: 200, body: {} }))
      await apiGet('/me')
      const [url, options] = global.fetch.mock.calls[0]
      expect(url).toContain('/me')
      expect(options.method).toBe('GET')
    })

    it('apiPost issues a POST with a JSON-serialized body', async () => {
      global.fetch.mockResolvedValue(mockFetchResponse({ ok: true, status: 200, body: {} }))
      await apiPost('/events/1/reassign-coordinator', { new_coordinator_id: 'x' })
      const [, options] = global.fetch.mock.calls[0]
      expect(options.method).toBe('POST')
      expect(JSON.parse(options.body)).toEqual({ new_coordinator_id: 'x' })
    })

    it('attaches the Bearer token from the current Supabase session', async () => {
      supabase.auth.getSession.mockResolvedValue({ data: { session: { access_token: 'tok123' } } })
      global.fetch.mockResolvedValue(mockFetchResponse({ ok: true, status: 200, body: {} }))
      await apiGet('/me')
      const [, options] = global.fetch.mock.calls[0]
      expect(options.headers.Authorization).toBe('Bearer tok123')
    })

    it('sends no Authorization header when there is no session', async () => {
      global.fetch.mockResolvedValue(mockFetchResponse({ ok: true, status: 200, body: {} }))
      await apiGet('/me')
      const [, options] = global.fetch.mock.calls[0]
      expect(options.headers.Authorization).toBeUndefined()
    })
  })

  // apiDelete was added on main for draft deletion (DELETE /events/<id>
  // returns 204 with NO body), so the empty-body path matters here in a
  // way it doesn't for GET/POST.
  describe('apiDelete', () => {
    it('issues a DELETE with no request body', async () => {
      global.fetch.mockResolvedValue({ ok: true, status: 204, json: async () => { throw new Error('no body') } })
      await apiDelete('/events/abc')
      const [url, options] = global.fetch.mock.calls[0]
      expect(url).toContain('/events/abc')
      expect(options.method).toBe('DELETE')
      expect(options.body).toBeUndefined()
    })

    it('a 204 with an empty body resolves to null instead of throwing on the JSON parse', async () => {
      global.fetch.mockResolvedValue({ ok: true, status: 204, json: async () => { throw new Error('no body') } })
      await expect(apiDelete('/events/abc')).resolves.toBeNull()
    })

    it('a 404 (not the caller\'s event, or already deleted) throws with the real code and does not redirect', async () => {
      global.fetch.mockResolvedValue(
        mockFetchResponse({ ok: false, status: 404, body: { error: { code: 'not_found', message: 'Event not found.' } } }),
      )
      await expect(apiDelete('/events/abc')).rejects.toMatchObject({ status: 404, code: 'not_found' })
      expect(push).not.toHaveBeenCalled()
    })

    it('a 403 (event is no longer a draft) throws and does not redirect -- forbidden is not the same as logged out', async () => {
      global.fetch.mockResolvedValue(
        mockFetchResponse({ ok: false, status: 403, body: { error: { code: 'not_authorised', message: 'nope' } } }),
      )
      await expect(apiDelete('/events/abc')).rejects.toMatchObject({ status: 403, code: 'not_authorised' })
      expect(push).not.toHaveBeenCalled()
      expect(clearLocalState).not.toHaveBeenCalled()
    })

    it('an expired session on a DELETE still triggers the forced logout, exactly like GET/POST', async () => {
      global.fetch.mockResolvedValue(
        mockFetchResponse({ ok: false, status: 401, body: { error: { code: 'auth_session_idle', message: 'idle' } } }),
      )
      await expect(apiDelete('/events/abc')).rejects.toMatchObject({ code: 'auth_session_idle' })
      expect(clearLocalState).toHaveBeenCalledTimes(1)
      expect(push).toHaveBeenCalledWith({ name: 'login' })
    })

    it('sends the Bearer token like every other verb', async () => {
      supabase.auth.getSession.mockResolvedValue({ data: { session: { access_token: 'tok123' } } })
      global.fetch.mockResolvedValue({ ok: true, status: 204, json: async () => { throw new Error('no body') } })
      await apiDelete('/events/abc')
      expect(global.fetch.mock.calls[0][1].headers.Authorization).toBe('Bearer tok123')
    })
  })

  describe.each(['auth_session_idle', 'auth_token_expired', 'auth_missing_token'])(
    'redirect-triggering code: %s',
    (code) => {
      beforeEach(() => {
        global.fetch.mockResolvedValue(
          mockFetchResponse({ ok: false, status: 401, body: { error: { code, message: 'nope' } } }),
        )
      })

      it('still throws -- uniform error contract, never silently resolves to undefined', async () => {
        await expect(apiGet('/me')).rejects.toMatchObject({ code, message: 'nope', status: 401 })
      })

      it('clears local auth state exactly once', async () => {
        await apiGet('/me').catch(() => {})
        expect(clearLocalState).toHaveBeenCalledTimes(1)
      })

      it('signs out of Supabase exactly once', async () => {
        await apiGet('/me').catch(() => {})
        expect(supabase.auth.signOut).toHaveBeenCalledTimes(1)
      })

      it('redirects to /login', async () => {
        await apiGet('/me').catch(() => {})
        expect(push).toHaveBeenCalledWith({ name: 'login' })
      })

      it('does not push again if already on the login route', async () => {
        routerMock.currentRoute.value.name = 'login'
        await apiGet('/me').catch(() => {})
        expect(push).not.toHaveBeenCalled()
      })
    },
  )

  describe.each(['auth_malformed_token', 'auth_invalid_signature', 'auth_unknown_key', 'auth_wrong_audience'])(
    'non-redirect "something is actually broken" code: %s',
    (code) => {
      beforeEach(() => {
        global.fetch.mockResolvedValue(
          mockFetchResponse({ ok: false, status: 401, body: { error: { code, message: 'broken' } } }),
        )
      })

      it('throws with the real code and message', async () => {
        await expect(apiGet('/me')).rejects.toMatchObject({ code, status: 401, message: 'broken' })
      })

      it('does NOT clear local state', async () => {
        await apiGet('/me').catch(() => {})
        expect(clearLocalState).not.toHaveBeenCalled()
      })

      it('does NOT sign out', async () => {
        await apiGet('/me').catch(() => {})
        expect(supabase.auth.signOut).not.toHaveBeenCalled()
      })

      it('does NOT redirect', async () => {
        await apiGet('/me').catch(() => {})
        expect(push).not.toHaveBeenCalled()
      })
    },
  )

  describe.each(['not_authorised', 'not_found', 'validation_error', 'internal_error'])(
    'unrelated backend error code (proves the redirect Set is an exact match, not a fuzzy/prefix one): %s',
    (code) => {
      it('throws normally and never triggers a redirect', async () => {
        global.fetch.mockResolvedValue(
          mockFetchResponse({ ok: false, status: 403, body: { error: { code, message: 'nope' } } }),
        )
        await expect(apiGet('/events/1')).rejects.toMatchObject({ code })
        expect(push).not.toHaveBeenCalled()
        expect(clearLocalState).not.toHaveBeenCalled()
      })
    },
  )

  describe('malformed / unexpected responses', () => {
    it('an unparseable JSON body on a non-ok response still throws, with a generic message and undefined code', async () => {
      global.fetch.mockResolvedValue({
        ok: false,
        status: 500,
        json: async () => {
          throw new Error('not json')
        },
      })
      await expect(apiGet('/me')).rejects.toMatchObject({ status: 500, code: undefined })
    })

    it('an ok response with an unparseable body resolves to null rather than throwing', async () => {
      global.fetch.mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => {
          throw new Error('not json')
        },
      })
      await expect(apiGet('/me')).resolves.toBeNull()
    })

    it('a missing error.code entirely does not accidentally match the redirect Set (undefined is not in it)', async () => {
      global.fetch.mockResolvedValue(
        mockFetchResponse({ ok: false, status: 400, body: { error: { message: 'oops, no code field' } } }),
      )
      await expect(apiGet('/me')).rejects.toMatchObject({ code: undefined, message: 'oops, no code field' })
      expect(push).not.toHaveBeenCalled()
    })

    it('a network-level failure (fetch itself rejects) propagates and is not swallowed or misrouted into the redirect path', async () => {
      global.fetch.mockRejectedValue(new TypeError('Failed to fetch'))
      await expect(apiGet('/me')).rejects.toThrow('Failed to fetch')
      expect(push).not.toHaveBeenCalled()
      expect(clearLocalState).not.toHaveBeenCalled()
    })
  })

  describe('concurrency and resilience', () => {
    it('two concurrent auth-redirect failures only clear state / sign out / push ONCE (de-duped in-flight redirect)', async () => {
      global.fetch.mockResolvedValue(
        mockFetchResponse({ ok: false, status: 401, body: { error: { code: 'auth_session_idle', message: 'idle' } } }),
      )
      await Promise.allSettled([apiGet('/me'), apiGet('/events')])
      expect(clearLocalState).toHaveBeenCalledTimes(1)
      expect(supabase.auth.signOut).toHaveBeenCalledTimes(1)
      expect(push).toHaveBeenCalledTimes(1)
    })

    it('two SEQUENTIAL (non-overlapping) redirect failures each independently trigger their own cleanup', async () => {
      global.fetch.mockResolvedValue(
        mockFetchResponse({ ok: false, status: 401, body: { error: { code: 'auth_session_idle', message: 'idle' } } }),
      )
      await apiGet('/me').catch(() => {})
      await apiGet('/events').catch(() => {})
      expect(clearLocalState).toHaveBeenCalledTimes(2)
      expect(supabase.auth.signOut).toHaveBeenCalledTimes(2)
    })

    it('a failing Supabase signOut() during the redirect does not prevent the redirect from completing', async () => {
      supabase.auth.signOut.mockRejectedValue(new Error('supabase is down'))
      global.fetch.mockResolvedValue(
        mockFetchResponse({ ok: false, status: 401, body: { error: { code: 'auth_token_expired', message: 'expired' } } }),
      )
      await apiGet('/me').catch(() => {})
      expect(clearLocalState).toHaveBeenCalledTimes(1)
      expect(push).toHaveBeenCalledWith({ name: 'login' })
    })

    it('clearLocalState runs BEFORE the (awaited) Supabase signOut call resolves -- reactive state must update immediately, not after a network round trip', async () => {
      const callOrder = []
      clearLocalState.mockImplementation(() => callOrder.push('clearLocalState'))
      supabase.auth.signOut.mockImplementation(async () => {
        callOrder.push('signOut')
        return { error: null }
      })
      global.fetch.mockResolvedValue(
        mockFetchResponse({ ok: false, status: 401, body: { error: { code: 'auth_session_idle', message: 'idle' } } }),
      )
      await apiGet('/me').catch(() => {})
      expect(callOrder).toEqual(['clearLocalState', 'signOut'])
    })
  })
})
