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
        <div class="logo">LOGO</div>
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
.login-page {
  min-height: 100vh;
  box-sizing: border-box;
  background: #eeeeee;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
}
.login-card {
  width: 100%;
  max-width: 420px;
  background: #ffffff;
  border: 1px dashed #9a9a9a;
  border-radius: 6px;
  padding: 44px 40px 36px;
  display: flex;
  flex-direction: column;
  gap: 22px;
  box-sizing: border-box;
}
.brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
}
.logo {
  width: 56px;
  height: 56px;
  border: 1px dashed #9a9a9a;
  border-radius: 4px;
  background: #f5f5f5;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  color: #9a9a9a;
  letter-spacing: 0.05em;
}
.brand-name {
  margin: 0;
  font-size: 20px;
  font-weight: 700;
  color: #222222;
}
.brand-tagline {
  font-size: 12px;
  color: #8a8a8a;
}
.divider {
  height: 1px;
  background: #e2e2e2;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.field label {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: #7a7a7a;
}
.field input {
  height: 44px;
  border: 1px solid #b0b0b0;
  border-radius: 4px;
  background: #fafafa;
  padding: 0 12px;
  font-size: 14px;
  color: #333333;
  box-sizing: border-box;
}
.field input:focus {
  outline: none;
  border-color: #555555;
  background: #ffffff;
}
.options {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.remember {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  color: #666666;
}
.remember input {
  width: 14px;
  height: 14px;
  margin: 0;
}
.forgot {
  font-size: 13px;
  color: #666666;
  text-decoration: underline;
}
.error {
  margin: 0;
  color: #c0392b;
  font-size: 13px;
}
.submit {
  height: 48px;
  border: none;
  border-radius: 4px;
  background: #444444;
  color: #ffffff;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}
.submit:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.footnote {
  text-align: center;
  font-size: 12px;
  color: #9a9a9a;
  line-height: 1.5;
  border-top: 1px dashed #e2e2e2;
  padding-top: 16px;
}
</style>
