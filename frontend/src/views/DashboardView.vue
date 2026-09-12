<script setup>
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()

async function handleSignOut() {
  await auth.signOut()
  router.push({ name: 'login' })
}
</script>

<template>
  <div class="dashboard">
    <header>
      <h1>ConnectSphere</h1>
      <button @click="handleSignOut">Sign out</button>
    </header>

    <section v-if="auth.profile">
      <p>
        Signed in as <strong>{{ auth.profile.name }}</strong> ({{ auth.profile.email }})
      </p>
      <p>Roles: {{ auth.profile.roles.join(', ') || 'none' }}</p>
    </section>

    <nav>
      <router-link to="/events">Events</router-link>
      <router-link to="/venues">Venues</router-link>
      <router-link to="/events/reassign">Reassign Coordinator</router-link>
    </nav>
  </div>
</template>

<style scoped>
.dashboard {
  max-width: 640px;
  margin: 2rem auto;
  padding: 0 1rem;
}
header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
nav {
  display: flex;
  gap: 1rem;
  margin-top: 1.5rem;
}
</style>
