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
// IS-61: Venue Staff only -- venues deleted from the catalogue, waiting to be
// permanently deleted (GET /venues/deleted).
const DELETED = 'deleted'

async function loadVenues() {
  loading.value = true
  error.value = ''
  try {
    if (statusFilter.value === DELETED) {
      venues.value = await apiGet('/venues/deleted')
      return
    }
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
          <button
            v-if="isVenueStaff"
            type="button"
            class="tab tab-deleted"
            data-test="deleted-tab"
            :class="{ active: statusFilter === DELETED }"
            @click="statusFilter = DELETED"
          >
            Deleted<template v-if="statusFilter === DELETED && !loading && !error"> ({{ venues.length }})</template>
          </button>
        </div>
        <p v-if="statusFilter === DELETED" class="deleted-note">
          Deleted from the catalogue and no longer bookable. Open one to permanently delete it.
        </p>

        <div class="list">
          <p v-if="loading" class="message">Loading venues...</p>
          <p v-else-if="error" class="message error" role="alert">{{ error }}</p>
          <p v-else-if="venues.length === 0" class="message">
            <template v-if="statusFilter === DELETED">No deleted venues waiting to be permanently deleted.</template>
            <template v-else>No venues to show{{ statusFilter ? ` with status "${statusFilter}"` : '' }}.</template>
          </p>
          <template v-else>
            <router-link v-for="venue in venues" :key="venue.id" :to="`/venues/${venue.id}`" class="row">
              <div class="row-main">
                <span class="row-name">{{ venue.name }}</span>
                <span class="row-meta">{{ venue.location }} &middot; capacity {{ venue.capacity }}</span>
              </div>
              <span v-if="venue.deleted_at" class="status status-deleted">deleted</span>
              <span v-else class="status" :class="`status-${venue.status}`">{{ venue.status }}</span>
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
.heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.add-btn {
  min-height: 36px; padding: 0 16px; border-radius: 4px; background: #2568e8; color: #fff;
  font-size: 13px; font-weight: 700; text-decoration: none; display: inline-flex; align-items: center;
}
.deleted-message { margin: 0; padding: 10px 14px; background: #eaf5ec; color: #2f6b3f; border-radius: 4px; font-size: 14px; }
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
.status-deleted { background: #f5e6e6; color: #a33f3f; }
.tab-deleted.active { border-color: #a33f3f; background: #a33f3f; color: #ffffff; }
.deleted-note { margin: 0; font-size: 13px; color: #6b6b6b; }
</style>
