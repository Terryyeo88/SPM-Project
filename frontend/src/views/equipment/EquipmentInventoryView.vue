<script setup>
/**
 * Equipment inventory, one row per physical unit -- Check Equipment
 * Availability (Nawaz, Sprint 2, IS-18), AC "Track equipment based on unit
 * level". The entry point to a unit's record (EquipmentDetailView), where
 * its occupancy is shown. Read-only: adding or retiring units is not part
 * of any story built so far.
 */
import { computed, onMounted, ref } from 'vue'
import { apiGet } from '../../lib/api'
import AppNavBar from '../../components/AppNavBar.vue'
import { unitStatusLabel } from '../../lib/equipment'

const units = ref([])
const loading = ref(true)
const error = ref('')
const typeFilter = ref('')
const search = ref('')

const typeOptions = computed(() => [...new Set(units.value.map((unit) => unit.type))].filter(Boolean).sort())
const visibleUnits = computed(() => {
  const needle = search.value.trim().toLowerCase()
  return units.value.filter(
    (unit) =>
      (!typeFilter.value || unit.type === typeFilter.value) &&
      (!needle || unit.asset_tag.toLowerCase().includes(needle)),
  )
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    units.value = await apiGet('/equipment')
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <AppNavBar />
    <main class="content">
      <div class="container">
        <h1 class="title">Equipment</h1>

        <p v-if="loading" class="message">Loading equipment...</p>
        <p v-else-if="error" class="message error" role="alert">Couldn't load equipment: {{ error }}</p>

        <template v-else>
          <div class="filters">
            <label class="visually-hidden" for="equipment-search">Search by equipment ID</label>
            <input id="equipment-search" v-model="search" type="search" placeholder="Search by equipment ID..." />
            <label class="visually-hidden" for="equipment-type">Filter by type</label>
            <select id="equipment-type" v-model="typeFilter">
              <option value="">All types</option>
              <option v-for="type in typeOptions" :key="type" :value="type">{{ type }}</option>
            </select>
          </div>

          <div class="list">
            <p v-if="visibleUnits.length === 0" class="message">No equipment matches.</p>
            <router-link
              v-for="unit in visibleUnits"
              :key="unit.id"
              :to="{ name: 'equipment-details', params: { equipmentId: unit.id } }"
              class="row"
            >
              <div class="row-main">
                <span class="row-name">{{ unit.asset_tag }}</span>
                <span class="row-meta">{{ unit.type }}</span>
              </div>
              <span class="status cs-pill" :class="`status-${unit.status} cs-status-${unit.status}`">{{ unitStatusLabel(unit.status) }}</span>
            </router-link>
          </div>
        </template>
      </div>
    </main>
  </div>
</template>

<style scoped>
.page { min-height: 100vh; display: flex; flex-direction: column; }
.content { flex: 1 1 auto; padding: var(--cs-space-6) var(--cs-space-4) var(--cs-space-8); display: flex; justify-content: center; }
.container { width: 100%; max-width: 880px; display: flex; flex-direction: column; gap: var(--cs-space-5); }
.title { margin: 0; font-size: var(--cs-text-xl); font-family: var(--cs-font-display); color: var(--cs-ink); }
.message { margin: 0; padding: var(--cs-space-4) 0; font-size: var(--cs-text-base); color: var(--cs-ink-soft); }
.error { color: var(--cs-occupied); }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }

.filters { display: flex; gap: var(--cs-space-3); flex-wrap: wrap; }
.filters input, .filters select {
  height: 46px; box-sizing: border-box; padding: 0 var(--cs-space-4); border: 1px solid var(--cs-line-strong); border-radius: var(--cs-radius-sm);
  background: var(--cs-surface); font: inherit; font-size: var(--cs-text-base);
}
.filters input { flex: 1 1 240px; }

.list { background: var(--cs-surface); border: 1px solid var(--cs-line); border-radius: var(--cs-radius-md); padding: 4px 18px; box-sizing: border-box; }
.row {
  display: flex; align-items: center; justify-content: space-between; gap: var(--cs-space-3);
  padding: var(--cs-space-4) 0; border-bottom: 1px solid var(--cs-line); text-decoration: none; color: inherit;
}
.row:last-child { border-bottom: none; }
.row:hover .row-name { text-decoration: underline; }
.row-main { display: flex; flex-direction: column; gap: 3px; }
.row-name { font-size: var(--cs-text-sm); font-weight: 600; color: var(--cs-ink); }
.row-meta { font-size: var(--cs-text-xs); color: var(--cs-ink-soft); text-transform: capitalize; }
</style>
