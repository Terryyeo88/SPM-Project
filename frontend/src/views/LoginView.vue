<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const email = ref('')
const password = ref('')
const error = ref('')
const loading = ref(false)

const auth = useAuthStore()
const router = useRouter()

async function handleSubmit() {
  error.value = ''
  loading.value = true
  try {
    await auth.signIn(email.value, password.value)
    router.push({ name: 'dashboard' })
  } catch (e) {
    error.value = e.message || 'Sign in failed.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <form class="login-card" @submit.prevent="handleSubmit">
      <div class="brand">
        <div class="logo" aria-hidden="true">CS</div>
        <h1 class="brand-name">ConnectSphere</h1>
        <div class="brand-tagline">Event Planning &amp; Venue Booking</div>
      </div>

      <div class="divider"></div>

      <div class="field">
        <label for="login-email">Email</label>
        <input
          id="login-email"
          v-model="email"
          type="email"
          required
          autocomplete="username"
          placeholder="you@connectsphere.com"
        />
      </div>

      <div class="field">
        <label for="login-password">Password</label>
        <input
          id="login-password"
          v-model="password"
          type="password"
          required
          autocomplete="current-password"
          placeholder="••••••••"
        />
      </div>

      <div class="options">
        <label class="remember">
          <input type="checkbox" />
          Remember me
        </label>
        <a href="#" class="forgot" @click.prevent>Forgot password?</a>
      </div>

      <p v-if="error" class="error">{{ error }}</p>

      <button type="submit" class="submit" :disabled="loading">
        {{ loading ? 'Signing in...' : 'Log In' }}
      </button>

      <div class="footnote">
        One login for every role — Organiser, Coordinator,<br />
        Venue Staff, Technical Support, or Attendee.<br />
        Your dashboard is chosen automatically after sign-in.
      </div>
    </form>
  </div>
</template>

<style scoped>
/* A faint architectural grid, the one ambient texture this direction
   allows itself -- floor-plan ruled paper, barely visible, never
   competing with the form. */
.login-page {
  min-height: 100vh;
  box-sizing: border-box;
  background-color: var(--cs-paper);
  background-image:
    linear-gradient(var(--cs-line) 1px, transparent 1px),
    linear-gradient(90deg, var(--cs-line) 1px, transparent 1px);
  background-size: 40px 40px;
  background-position: center;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--cs-space-4);
}
.login-card {
  position: relative;
  width: 100%;
  max-width: 420px;
  background: var(--cs-surface);
  border: 1px solid var(--cs-line);
  border-radius: var(--cs-radius-md);
  padding: var(--cs-space-7) var(--cs-space-6) var(--cs-space-6);
  display: flex;
  flex-direction: column;
  gap: var(--cs-space-5);
  box-sizing: border-box;
  box-shadow: var(--cs-shadow-md);
}
/* Same corner-tick signature as .cs-card, at the login card's own scale --
   the one place in the whole app a visitor sees before anything else, so
   the motif is established right here. */
.login-card::before,
.login-card::after {
  content: '';
  position: absolute;
  width: 16px;
  height: 16px;
  pointer-events: none;
}
.login-card::before {
  top: -1px;
  left: -1px;
  border-top: 2px solid var(--cs-ink);
  border-left: 2px solid var(--cs-ink);
}
.login-card::after {
  bottom: -1px;
  right: -1px;
  border-bottom: 2px solid var(--cs-ink);
  border-right: 2px solid var(--cs-ink);
}
.brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--cs-space-3);
}
.logo {
  width: 52px;
  height: 52px;
  border-radius: var(--cs-radius-sm);
  background: var(--cs-ink);
  color: var(--cs-paper);
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--cs-font-display);
  font-weight: 700;
  font-size: 22px;
}
.brand-name {
  margin: 0;
  font-family: var(--cs-font-display);
  font-size: var(--cs-text-lg);
  font-weight: 700;
  color: var(--cs-ink);
  letter-spacing: -0.01em;
}
.brand-tagline {
  font-family: var(--cs-font-mono);
  font-size: var(--cs-text-xs);
  letter-spacing: 0.04em;
  color: var(--cs-ink-soft);
}
.divider {
  height: 1px;
  background: var(--cs-line);
}
.field {
  display: flex;
  flex-direction: column;
  gap: var(--cs-space-2);
}
.field label {
  font-size: var(--cs-text-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--cs-ink-soft);
}
.field input {
  height: 46px;
  border: 1px solid var(--cs-line-strong);
  border-radius: var(--cs-radius-sm);
  background: var(--cs-surface);
  padding: 0 var(--cs-space-3);
  font-family: inherit;
  font-size: var(--cs-text-base);
  color: var(--cs-ink);
  box-sizing: border-box;
}
.field input:focus-visible {
  outline: 2px solid var(--cs-signal);
  outline-offset: 1px;
  border-color: var(--cs-signal);
}
.options {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.remember {
  display: flex;
  align-items: center;
  gap: var(--cs-space-2);
  font-size: var(--cs-text-sm);
  color: var(--cs-ink-soft);
}
.remember input {
  width: 15px;
  height: 15px;
  margin: 0;
  accent-color: var(--cs-signal);
}
.forgot {
  font-size: var(--cs-text-sm);
  color: var(--cs-ink-soft);
  text-decoration: underline;
}
.error {
  margin: 0;
  color: var(--cs-occupied);
  font-size: var(--cs-text-sm);
}
.submit {
  height: 48px;
  border: none;
  border-radius: var(--cs-radius-sm);
  background: var(--cs-signal);
  color: #ffffff;
  font-family: inherit;
  font-size: var(--cs-text-sm);
  font-weight: 700;
  cursor: pointer;
  transition: background-color 120ms ease;
}
.submit:hover:not(:disabled) {
  background: var(--cs-signal-strong);
}
.submit:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.footnote {
  text-align: center;
  font-size: var(--cs-text-xs);
  color: var(--cs-ink-soft);
  line-height: 1.5;
  border-top: 1px solid var(--cs-line);
  padding-top: var(--cs-space-4);
}
</style>
