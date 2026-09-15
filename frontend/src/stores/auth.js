import { defineStore } from 'pinia'
import { supabase } from '../lib/supabaseClient'
import { apiGet } from '../lib/api'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    session: null, // Supabase session (has .access_token)
    profile: null, // { id, email, name, roles } from GET /me
    restored: false, // has restoreSession() run yet this page load?
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
      await supabase.auth.signOut()
      this.clearLocalState()
    },

    /** Just the local half of signing out (no Supabase network call).
     * Used by signOut() above, and by api.js's own force-logout on
     * auth_session_idle/auth_token_expired/auth_missing_token -- that
     * path fires supabase.auth.signOut() itself, without awaiting it
     * (see api.js's _handleAuthRedirect), so it needs this piece
     * separately rather than going through signOut() and blocking the
     * redirect on a network round trip that doesn't need to finish
     * first. Kept here, not duplicated in api.js, so there's exactly one
     * place that defines what "locally signed out" means. */
    clearLocalState() {
      this.session = null
      this.profile = null
    },

    async loadProfile() {
      this.profile = await apiGet('/me')
    },

    /** Called once by the router guard on first navigation -- picks up
     * an existing Supabase session (e.g. after a page refresh) without
     * forcing the user to log in again. */
    async restoreSession() {
      const { data } = await supabase.auth.getSession()
      this.session = data.session
      if (this.session) {
        try {
          await this.loadProfile()
        } catch {
          // loadProfile() -> apiGet('/me') can throw if the stored
          // session's token has expired since the last page load --
          // api.js's own handler (see _handleAuthRedirect there) already
          // clears session/profile and redirects to /login for that
          // case, so there's nothing left to do here except NOT let this
          // propagate. An uncaught rejection here would reach the router
          // guard's own `await auth.restoreSession()` and fail the
          // in-flight navigation instead of the clean login redirect
          // api.js already triggered.
        }
      }
      this.restored = true
    },
  },
})
