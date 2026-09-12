<script setup>
import { ref } from 'vue'
import { apiPost } from '../../lib/api'

const eventId = ref('')
const newCoordinatorId = ref('')
const reason = ref('')
const result = ref(null)
const error = ref('')
const loading = ref(false)

async function handleSubmit() {
  error.value = ''
  result.value = null
  loading.value = true
  try {
    result.value = await apiPost(`/events/${eventId.value}/reassign-coordinator`, {
      new_coordinator_id: newCoordinatorId.value,
      reason: reason.value || undefined,
    })
  } catch (e) {
    error.value = e.message || 'Reassignment failed.'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="reassign">
    <p><router-link to="/">&larr; Back</router-link></p>
    <h2>Reassign Coordinator</h2>
    <p class="hint">
      Only works if you're signed in as the coordinator currently assigned to the event -- that's enforced by the
      backend's authz policy, not by this form.
    </p>

    <form @submit.prevent="handleSubmit">
      <label>
        Event ID
        <input v-model="eventId" required />
      </label>
      <label>
        New coordinator's user ID
        <input v-model="newCoordinatorId" required />
      </label>
      <label>
        Reason (optional)
        <input v-model="reason" />
      </label>
      <button type="submit" :disabled="loading">{{ loading ? 'Submitting...' : 'Reassign' }}</button>
    </form>

    <p v-if="error" class="error">{{ error }}</p>
    <pre v-if="result">{{ JSON.stringify(result, null, 2) }}</pre>
  </div>
</template>

<style scoped>
.reassign {
  max-width: 480px;
  margin: 2rem auto;
  padding: 0 1rem;
}
.hint {
  font-size: 0.85rem;
  color: #666;
}
form {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  margin: 1rem 0;
}
label {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  font-size: 0.9rem;
}
input {
  padding: 0.5rem;
}
button {
  padding: 0.6rem;
  cursor: pointer;
}
.error {
  color: #c0392b;
}
pre {
  background: #f4f4f4;
  padding: 1rem;
  overflow-x: auto;
}
</style>
