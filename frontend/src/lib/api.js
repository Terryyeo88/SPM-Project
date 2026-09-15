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

/**
 * Signs the caller out and sends them to /login. Called only for the
 * three codes above.
 *
 * Uses dynamic import() for the auth store and router, not a top-level
 * import -- stores/auth.js imports apiGet from this module already, so a
 * static top-level import here (of the store directly, or of router,
 * which itself imports the store) would be a circular ES module
 * dependency. Deferring the import to call-time (this function only
 * runs on an actual auth failure, not on module load) sidesteps that
 * entirely instead of relying on bundler-specific circular-import
 * resolution behaviour.
 */
async function _handleAuthRedirect() {
  const [{ useAuthStore }, { default: router }] = await Promise.all([
    import('../stores/auth'),
    import('../router'),
  ])

  const auth = useAuthStore()
  // Calls clearLocalState() directly rather than auth.signOut(), so a
  // Supabase network error/delay can't block clearing local state -- the
  // caller is being force-logged-out because the backend already
  // rejected them; local state must clear regardless of whether the
  // signOut round trip to Supabase itself succeeds.
  auth.clearLocalState()
  supabase.auth.signOut().catch(() => {})

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

    if (_AUTH_REDIRECT_CODES.has(code)) {
      // Deliberately does NOT throw after this. The caller is about to
      // be navigated to /login regardless of what this specific request
      // was for, so surfacing "Session has been idle too long" as a
      // component-level error (e.g. in ReassignCoordinatorView's
      // `error` ref) right as the page changes underneath it would be
      // confusing, not helpful. Resolving to `undefined` instead of
      // throwing is safe for every current caller: auth.js's
      // loadProfile() just assigns it to `profile` (about to be
      // discarded on redirect anyway), and every apiPost() caller
      // already tears its own component down on navigation.
      await _handleAuthRedirect()
      return undefined
    }

    const message = body?.error?.message || `Request failed with status ${response.status}`
    const error = new Error(message)
    error.status = response.status
    error.code = code
    throw error
  }

  return body
}

export const apiGet = (path) => request(path, { method: 'GET' })
export const apiPost = (path, data) => request(path, { method: 'POST', body: JSON.stringify(data) })
