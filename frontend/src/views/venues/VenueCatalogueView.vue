<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { apiGet } from '../../lib/api'
import { ROLES, hasAnyRole } from '../../lib/roles'
import { useAuthStore } from '../../stores/auth'
import AppNavBar from '../../components/AppNavBar.vue'

const route = useRoute()
const auth = useAuthStore()
// IS-61: Venue Staff add venues from here; after a delete, the venue page
// sends them back here with what the delete did (?deleted=...).
const isVenueStaff = computed(() => hasAnyRole(auth.roles, [ROLES.VENUE_STAFF]))
const deletedMessage = computed(() => (typeof route.query.deleted === 'string' ? route.query.deleted : ''))

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
        <div class="heading">
          <h1 class="title">Venue Catalogue</h1>
          <router-link v-if="isVenueStaff" :to="{ name: 'venue-create' }" class="add-btn">Add venue</router-link>
        </div>
        <p v-if="deletedMessage" class="deleted-message" role="status">{{ deletedMessage }}</p>

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
              <span class="status cs-pill" :class="`status-${venue.status} cs-status-${venue.status}`">{{ venue.status }}</span>
            </router-link>
          </template>
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
.page { min-height: 100vh; display: flex; flex-direction: column; }
.content { flex: 1 1 auto; padding: var(--cs-space-6) var(--cs-space-4) var(--cs-space-8); display: flex; justify-content: center; }
.container { width: 100%; max-width: 880px; display: flex; flex-direction: column; gap: var(--cs-space-5); }
.title { margin: 0; font-size: var(--cs-text-xl); font-family: var(--cs-font-display); color: var(--cs-ink); }
.heading { display: flex; align-items: center; justify-content: space-between; gap: var(--cs-space-3); flex-wrap: wrap; }
.add-btn {
  min-height: 36px; padding: 0 var(--cs-space-4); border-radius: var(--cs-radius-sm); background: var(--cs-signal); color: #fff;
  font-size: var(--cs-text-sm); font-weight: 700; text-decoration: none; display: inline-flex; align-items: center;
}
.add-btn:hover { background: var(--cs-signal-strong); }
.deleted-message { margin: 0; padding: var(--cs-space-2) var(--cs-space-3); background: var(--cs-available-tint); color: var(--cs-available); border-radius: var(--cs-radius-sm); font-size: var(--cs-text-base); }
.tabs { display: flex; align-items: center; gap: var(--cs-space-2); flex-wrap: wrap; }
.tab {
  border: 1px solid var(--cs-line);
  background: var(--cs-surface);
  color: var(--cs-ink-soft);
  font-size: var(--cs-text-sm);
  font-weight: 600;
  padding: 7px var(--cs-space-4);
  border-radius: var(--cs-radius-full);
  cursor: pointer;
  text-transform: capitalize;
}
.tab.active { border-color: var(--cs-ink); background: var(--cs-ink); color: #ffffff; }
.list { background: var(--cs-surface); border: 1px solid var(--cs-line); border-radius: var(--cs-radius-md); padding: 4px 18px; box-sizing: border-box; }
.message { margin: 0; padding: var(--cs-space-4) 0; font-size: var(--cs-text-base); color: var(--cs-ink-soft); }
.error { color: var(--cs-occupied); }
.row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--cs-space-3);
  padding: var(--cs-space-4) 0;
  border-bottom: 1px solid var(--cs-line);
  text-decoration: none;
  color: inherit;
}
.row:last-child { border-bottom: none; }
.row:hover .row-name { text-decoration: underline; }
.row-main { display: flex; flex-direction: column; gap: 3px; }
.row-name { font-size: var(--cs-text-sm); font-weight: 600; color: var(--cs-ink); }
.row-meta { font-size: var(--cs-text-xs); color: var(--cs-ink-soft); }
</style>
