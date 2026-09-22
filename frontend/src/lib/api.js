/**
 * Thin fetch wrapper for the Flask backend. Attaches the current
 * Supabase session's access token as a Bearer header on every request --
 * this is what app/auth/context.py on the backend actually reads.
 */
import { supabase } from './supabaseClient'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:5000'

// Every `code` app/shared/errors.py's AuthenticationError can carry (see
// app/auth/jwt.py and app/auth/context.py's module docstrings), split by
// what the frontend should DO about each -- this split came from Terry,
// who owns the backend codes, not guessed at here:
//
//   auth_session_idle, auth_token_expired, auth_missing_token
//     -- the caller simply isn't authenticated (any more). The one fix
//        is signing in again, so these three trigger an automatic
//        sign-out + redirect to /login.
//
//   auth_malformed_token, auth_invalid_signature, auth_unknown_key,
//   auth_wrong_audience
//     -- something is actually broken (a corrupted/tampered token, a
//        client bug, a JWKS mismatch). Signing out and back in won't
//        necessarily fix these, and silently redirecting risks a loop if
//        whatever's producing the bad token keeps producing it. These
//        are deliberately NOT auto-redirected -- they fall through and
//        throw, same as any other error, so the calling component shows
//        the real message instead of hiding it behind a login screen.
const _AUTH_REDIRECT_CODES = new Set(['auth_session_idle', 'auth_token_expired', 'auth_missing_token'])

// De-dupes concurrent/re-entrant calls to _handleAuthRedirect -- without
// this, two API calls failing at once (or restoreSession's own /me call
// racing against its own triggered redirect re-entering the router
// guard -- see router/index.js's comment on this) would each
// independently re-import the store/router, clear state again, and call
// signOut()/push() again. Holding the SAME in-flight promise instead
// means a second caller just awaits the first one's outcome.
let _redirectInFlight = null

/**
 * Signs the caller out and sends them to /login. Called only for the
 * three codes above -- see _AUTH_REDIRECT_CODES' own comment.
 */
function _handleAuthRedirect() {
  if (!_redirectInFlight) {
    _redirectInFlight = _doHandleAuthRedirect().finally(() => {
      _redirectInFlight = null
    })
  }
  return _redirectInFlight
}

/**
 * Uses dynamic import() for the auth store and router, not a top-level
 * import -- stores/auth.js imports apiGet from this module already, so a
 * static top-level import here (of the store directly, or of router,
 * which itself imports the store) would be a circular ES module
 * dependency. Deferring the import to call-time (this function only
 * runs on an actual auth failure, not on module load) sidesteps that
 * entirely instead of relying on bundler-specific circular-import
 * resolution behaviour.
 */
async function _doHandleAuthRedirect() {
  const [{ useAuthStore }, { default: router }] = await Promise.all([
    import('../stores/auth'),
    import('../router'),
  ])

  const auth = useAuthStore()
  // Cleared first, before the (awaited) Supabase call below -- so any
  // reactive code watching auth.isLoggedIn reflects the forced logout
  // immediately, not after a network round trip.
  auth.clearLocalState()

  // AWAITED, not fire-and-forget -- a caller who gets force-logged-out
  // here and immediately signs back in (see stores/auth.js::signIn())
  // must not have that fresh sign-in silently undone by THIS call's
  // signOut() resolving late and clearing Supabase's own session storage
  // out from under it. try/catch so a slow/failing Supabase round trip
  // still lets the redirect below happen -- the caller is being
  // force-logged-out regardless of whether Supabase's own signOut
  // network call succeeds; local state (cleared above) is authoritative.
  try {
    await supabase.auth.signOut()
  } catch {
    // best-effort only, see comment above
  }

  // Also reached from router/index.js's own beforeEach guard (via
  // restoreSession -> loadProfile -> this module, see stores/auth.js) --
  // that guard separately redirects to login too once it sees
  // isLoggedIn === false, so this push can be a harmless duplicate of
  // one already in flight. Guarding on currentRoute avoids at least the
  // common case (already on /login) triggering a redundant navigation.
  if (router.currentRoute.value.name !== 'login') {
    router.push({ name: 'login' })
  }
}

async function authHeaders() {
  const { data } = await supabase.auth.getSession()
  const token = data.session?.access_token
  return token ? { Authorization: `Bearer ${token}` } : {}
}

async function request(path, options = {}) {
  const headers = {
    'Content-Type': 'application/json',
    ...(await authHeaders()),
    ...(options.headers || {}),
  }

  const response = await fetch(`${API_BASE_URL}${path}`, { ...options, headers })
  const body = await response.json().catch(() => null)

  if (!response.ok) {
    // Backend error shape: {"error": {"code": "...", "message": "..."}}
    // -- see backend/app/shared/errors.py.
    const code = body?.error?.code
    const message = body?.error?.message || `Request failed with status ${response.status}`
    const error = new Error(message)
    error.status = response.status
    error.code = code

    if (_AUTH_REDIRECT_CODES.has(code)) {
      // Fires the redirect, but still throws below -- every
      // apiGet/apiPost caller gets ONE error contract (always throws on
      // failure, never silently resolves), so a future call site can't
      // be surprised by an `undefined` it didn't ask for. The component
      // whose request failed may briefly show this error's message
      // before the redirect takes it off-screen (e.g.
      // ReassignCoordinatorView's own `error` ref) -- that's acceptable,
      // and more honest than hiding it. stores/auth.js's restoreSession()
      // is the one caller that specifically needs to tell this case
      // apart from the "something's actually broken" codes below; it
      // does so via `error.code`, not by this function's return shape.
      await _handleAuthRedirect()
    }

    throw error
  }

  return body
}

export const apiGet = (path) => request(path, { method: 'GET' })
export const apiPost = (path, data) => request(path, { method: 'POST', body: JSON.stringify(data) })
export const apiDelete = (path) => request(path, { method: 'DELETE' })
