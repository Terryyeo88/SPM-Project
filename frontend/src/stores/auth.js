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
        await this.loadProfile()
      }
      this.restored = true
    },
  },
})
