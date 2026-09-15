import { defineStore } from 'pinia'
import { supabase } from '../lib/supabaseClient'
import { apiGet } from '../lib/api'

// The in-flight restoreSession() promise, if any. Kept as a plain
// module-scoped variable, NOT reactive Pinia state -- there's no reason
// for a Promise to be wrapped in Vue's reactivity, and this app has no
// SSR (see main.js: client-only createApp/mount), so a module-scoped
// singleton behaves exactly like the store's own singleton-ness with
// none of the "should a Promise be reactive" questions. Guards against
// restoreSession() being re-entered while it's still running -- which
// genuinely happens: _handleAuthRedirect() (api.js) can call
// router.push({name:'login'}) WHILE the router guard's own
// `await auth.restoreSession()` for a DIFFERENT navigation is still
// pending (see router/index.js's own comment on this), re-entering the
// guard before `restored` is set. Without this guard, that would start
// a second, fully independent restoreSession() -- a second /me call, a
// second forced-logout cycle racing the first.
let _restoring = null

export const useAuthStore = defineStore('auth', {
  state: () => ({
    session: null, // Supabase session (has .access_token)
    profile: null, // { id, email, name, roles } from GET /me
    restored: false, // has restoreSession() run yet this page load?
    // Set when restoreSession()'s own loadProfile() call fails for a
    // reason OTHER than the session being invalid (network outage,
    // backend 500) -- i.e. NOT one of the auth_* codes. Lets
    // DashboardView show a genuine "something went wrong" message
    // instead of silently rendering as if the user simply has no roles
    // (auth.roles resolves to [] either way once profile is null, so
    // the UI needs this to tell the two states apart). Cleared at the
    // start of every restoreSession() attempt.
    profileLoadError: null,
  }),

  getters: {
    isLoggedIn: (state) => !!state.session,
    roles: (state) => state.profile?.roles ?? [],
  },

  actions: {
    async signIn(email, password) {
      const { data, error } = await supabase.auth.signInWithPassword({ email, password })
      if (error) throw error
      this.session = data.session
      await this.loadProfile()
    },

    async signOut() {
      // try/finally, not try-then-call: an explicit "sign out" click must
      // clear local state even if the Supabase network round trip itself
      // fails -- same principle as api.js's forced-logout path. The
      // error (if any) still propagates after clearLocalState() runs, so
      // a caller that wants to know the Supabase call failed still can.
      try {
        await supabase.auth.signOut()
      } finally {
        this.clearLocalState()
      }
    },

    /** Just the local half of signing out (no Supabase network call).
     * Used by signOut() above, and by api.js's own force-logout on
     * auth_session_idle/auth_token_expired/auth_missing_token (see
     * api.js's _handleAuthRedirect, which awaits its own Supabase
     * signOut() call separately). Kept here, not duplicated in api.js,
     * so there's exactly one place that defines what "locally signed
     * out" means. */
    clearLocalState() {
      this.session = null
      this.profile = null
    },

    async loadProfile() {
      this.profile = await apiGet('/me')
    },

    /** Called once by the router guard on first navigation -- picks up
     * an existing Supabase session (e.g. after a page refresh) without
     * forcing the user to log in again. Safe to call multiple times
     * concurrently -- see the module-level `_restoring` comment above. */
    restoreSession() {
      if (!_restoring) {
        _restoring = this._doRestoreSession().finally(() => {
          _restoring = null
        })
      }
      return _restoring
    },

    async _doRestoreSession() {
      this.profileLoadError = null
      const { data } = await supabase.auth.getSession()
      this.session = data.session
      if (this.session) {
        try {
          await this.loadProfile()
        } catch (err) {
          // api.js's request() now throws for EVERY failure, uniformly
          // (including the three auth_session_idle/auth_token_expired/
          // auth_missing_token codes -- it fires the sign-out+redirect
          // itself first, then still throws; see its own comment). So
          // this catch sees every possible loadProfile() failure, and
          // has to tell two genuinely different cases apart by
          // `err.code`:
          if (err?.code?.startsWith('auth_')) {
            // The stored session itself is untrustworthy -- either one
            // of the three codes above (where _handleAuthRedirect
            // already cleared state and redirected; this is a harmless
            // repeat), or one of the four "something's actually broken"
            // codes (auth_malformed_token etc.) surviving in local
            // storage across a refresh. Either way, clearing it here
            // makes the router guard's own `!auth.isLoggedIn` check
            // redirect to /login for THIS SAME navigation attempt, same
            // as any other logged-out visit.
            this.clearLocalState()
          } else {
            // NOT proof the session is invalid -- a network outage or
            // backend 500 shouldn't force a real re-login over what
            // might be transient. Surfaced via profileLoadError (for
            // DashboardView to show) instead of thrown -- an uncaught
            // rejection here would fail the in-flight navigation itself
            // rather than letting it complete with a visible error.
            this.profileLoadError = err?.message || 'Failed to load your profile.'
            console.error('restoreSession: could not load profile', err)
          }
        }
      }
      this.restored = true
    },
  },
})
