<script setup>
import { onMounted, ref, watch } from 'vue'
import { apiGet } from '../../lib/api'
import AppNavBar from '../../components/AppNavBar.vue'

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
  <div class="page">
    <AppNavBar />

    <main class="content">
      <div class="container">
        <h1 class="title">Venue Catalogue</h1>

        <div class="tabs" role="group" aria-label="Filter by status">
          <button
            type="button"
            class="tab"
            :class="{ active: statusFilter === '' }"
            @click="statusFilter = ''"
          >
            All<template v-if="statusFilter === '' && !loading && !error"> ({{ venues.length }})</template>
          </button>
          <button
            v-for="status in STATUSES"
            :key="status"
            type="button"
            class="tab"
            :class="{ active: statusFilter === status }"
            @click="statusFilter = status"
          >
            {{ status }}<template v-if="statusFilter === status && !loading && !error"> ({{ venues.length }})</template>
          </button>
        </div>

        <div class="list">
          <p v-if="loading" class="message">Loading venues...</p>
          <p v-else-if="error" class="message error" role="alert">{{ error }}</p>
          <p v-else-if="venues.length === 0" class="message">
            No venues to show{{ statusFilter ? ` with status "${statusFilter}"` : '' }}.
          </p>
          <template v-else>
            <router-link v-for="venue in venues" :key="venue.id" :to="`/venues/${venue.id}`" class="row">
              <div class="row-main">
                <span class="row-name">{{ venue.name }}</span>
                <span class="row-meta">{{ venue.location }} &middot; capacity {{ venue.capacity }}</span>
              </div>
              <span class="status" :class="`status-${venue.status}`">{{ venue.status }}</span>
            </router-link>
          </template>
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
.page { min-height: 100vh; display: flex; flex-direction: column; background: #eeeeee; }
.content { flex: 1 1 auto; padding: 32px 16px; display: flex; justify-content: center; }
.container { width: 100%; max-width: 880px; display: flex; flex-direction: column; gap: 20px; }
.title { margin: 0; font-size: 20px; font-weight: 700; color: #1f1f1f; }
.tabs { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.tab {
  border: 1px solid #b0b0b0;
  background: #ffffff;
  color: #555555;
  font-size: 13px;
  font-weight: 600;
  padding: 7px 16px;
  border-radius: 20px;
  cursor: pointer;
  text-transform: capitalize;
}
.tab.active { border-color: #444444; background: #444444; color: #ffffff; }
.list { background: #ffffff; border: 1px dashed #9a9a9a; border-radius: 6px; padding: 4px 18px; box-sizing: border-box; }
.message { margin: 0; padding: 16px 0; font-size: 14px; color: #8a8a8a; }
.error { color: #b42318; }
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 16px 0;
  border-bottom: 1px dashed #e2e2e2;
  text-decoration: none;
  color: inherit;
}
.row:last-child { border-bottom: none; }
.row:hover .row-name { text-decoration: underline; }
.row-main { display: flex; flex-direction: column; gap: 3px; }
.row-name { font-size: 14px; font-weight: 600; color: #2a2a2a; }
.row-meta { font-size: 12px; color: #8a8a8a; }
.status {
  font-size: 11px;
  font-weight: 600;
  color: #6a6a6a;
  background: #f0f0f0;
  border-radius: 10px;
  padding: 3px 10px;
  text-transform: capitalize;
  white-space: nowrap;
}
.status-available { background: #d1fae5; color: #067647; }
.status-occupied { background: #fee2e2; color: #b42318; }
.status-maintenance { background: #fef3c7; color: #92400e; }
</style>
