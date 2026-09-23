<script setup>
import { onMounted, ref, watch } from 'vue'
import { apiGet } from '../../lib/api'

const events = ref([])
const loading = ref(true)
const error = ref('')
const statusFilter = ref('')

const STATUSES = [
  'draft',
  'submitted',
  'under_review',
  'approved',
  'planning',
  'confirmed',
  'completed',
  'cancelled',
  'rejected',
]

async function loadEvents() {
  loading.value = true
  error.value = ''
  try {
    const query = statusFilter.value ? `?status=${statusFilter.value}` : ''
    events.value = await apiGet(`/events${query}`)
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    loading.value = false
  }
}

function formatDate(value) {
  return value || 'Not set'
}

watch(statusFilter, loadEvents)
onMounted(loadEvents)
</script>

<template>
  <main class="events-list">
    <p><router-link to="/">&larr; Back</router-link></p>
    <header>
      <h1>Event requests</h1>
      <label class="filter">
        Status
        <select v-model="statusFilter">
          <option value="">All</option>
          <option v-for="status in STATUSES" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
    </header>

    <p v-if="loading">Loading event requests...</p>
    <p v-else-if="error" class="error" role="alert">{{ error }}</p>
    <p v-else-if="events.length === 0" class="empty">
      No event requests to show{{ statusFilter ? ` with status "${statusFilter}"` : '' }}.
    </p>
    <ul v-else class="event-cards">
      <li v-for="event in events" :key="event.id">
        <router-link :to="`/events/${event.id}`" class="event-card">
          <div class="event-card-main">
            <strong>{{ event.name }}</strong>
            <span class="muted">{{ formatDate(event.preferred_start_date) }}</span>
          </div>
          <span class="status" :class="`status-${event.status}`">{{ event.status }}</span>
        </router-link>
      </li>
    </ul>
  </main>
</template>

<style scoped>
.events-list { max-width: 760px; margin: 2rem auto; padding: 0 1rem 3rem; }
header { display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap; }
.filter { display: flex; align-items: center; gap: .5rem; font-weight: 600; }
.filter select { padding: .4rem .6rem; border: 1px solid #94a3b8; border-radius: 4px; font: inherit; }
.event-cards { list-style: none; margin: 1.5rem 0 0; padding: 0; display: grid; gap: .75rem; }
.event-card {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  padding: .9rem 1.1rem;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  text-decoration: none;
  color: inherit;
}
.event-card:hover { border-color: #0f766e; }
.event-card-main { display: flex; flex-direction: column; gap: .2rem; }
.muted { color: #64748b; font-size: .9rem; }
.status { padding: .3rem .6rem; background: #e2e8f0; border-radius: 4px; text-transform: capitalize; font-size: .85rem; white-space: nowrap; }
.error { color: #b42318; }
.empty { color: #64748b; margin-top: 1.5rem; }
</style>
