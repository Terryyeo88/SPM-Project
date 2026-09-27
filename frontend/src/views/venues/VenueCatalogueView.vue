<script setup>
import { onMounted, ref, watch } from 'vue'
import { apiGet } from '../../lib/api'

const venues = ref([])
const loading = ref(true)
const error = ref('')
const statusFilter = ref('')

const STATUSES = ['available', 'occupied', 'maintenance']

async function loadVenues() {
  loading.value = true
  error.value = ''
  try {
    const query = statusFilter.value ? `?status=${statusFilter.value}` : ''
    venues.value = await apiGet(`/venues${query}`)
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    loading.value = false
  }
}

watch(statusFilter, loadVenues)
onMounted(loadVenues)
</script>

<template>
  <main class="venues-list">
    <p><router-link to="/">&larr; Back</router-link></p>
    <header>
      <h1>Venue catalogue</h1>
      <label class="filter">
        Status
        <select v-model="statusFilter">
          <option value="">All</option>
          <option v-for="status in STATUSES" :key="status" :value="status">{{ status }}</option>
        </select>
      </label>
    </header>

    <p v-if="loading">Loading venues...</p>
    <p v-else-if="error" class="error" role="alert">{{ error }}</p>
    <p v-else-if="venues.length === 0" class="empty">
      No venues to show{{ statusFilter ? ` with status "${statusFilter}"` : '' }}.
    </p>
    <ul v-else class="venue-cards">
      <li v-for="venue in venues" :key="venue.id">
        <router-link :to="`/venues/${venue.id}`" class="venue-card">
          <div class="venue-card-main">
            <strong>{{ venue.name }}</strong>
            <span class="muted">{{ venue.location }} &middot; capacity {{ venue.capacity }}</span>
          </div>
          <span class="status" :class="`status-${venue.status}`">{{ venue.status }}</span>
        </router-link>
      </li>
    </ul>
  </main>
</template>

<style scoped>
.venues-list { max-width: 760px; margin: 2rem auto; padding: 0 1rem 3rem; }
header { display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap; }
.filter { display: flex; align-items: center; gap: .5rem; font-weight: 600; }
.filter select { padding: .4rem .6rem; border: 1px solid #94a3b8; border-radius: 4px; font: inherit; }
.venue-cards { list-style: none; margin: 1.5rem 0 0; padding: 0; display: grid; gap: .75rem; }
.venue-card {
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
.venue-card:hover { border-color: #0f766e; }
.venue-card-main { display: flex; flex-direction: column; gap: .2rem; }
.muted { color: #64748b; font-size: .9rem; }
.status { padding: .3rem .6rem; background: #e2e8f0; border-radius: 4px; text-transform: capitalize; font-size: .85rem; white-space: nowrap; }
.status-available { background: #d1fae5; color: #067647; }
.status-occupied { background: #fee2e2; color: #b42318; }
.status-maintenance { background: #fef3c7; color: #92400e; }
.error { color: #b42318; }
.empty { color: #64748b; margin-top: 1.5rem; }
</style>
