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
              <span class="status" :class="`status-${unit.status}`">{{ unitStatusLabel(unit.status) }}</span>
            </router-link>
          </div>
        </template>
      </div>
    </main>
  </div>
</template>

<style scoped>
.page { min-height: 100vh; display: flex; flex-direction: column; background: #eeeeee; }
.content { flex: 1 1 auto; padding: 32px 16px; display: flex; justify-content: center; }
.container { width: 100%; max-width: 880px; display: flex; flex-direction: column; gap: 20px; }
.title { margin: 0; font-size: 20px; font-weight: 700; color: #1f1f1f; }
.message { margin: 0; padding: 16px 0; font-size: 14px; color: #8a8a8a; }
.error { color: #b42318; }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }

.filters { display: flex; gap: 12px; flex-wrap: wrap; }
.filters input, .filters select {
  height: 46px; box-sizing: border-box; padding: 0 16px; border: 1px solid #b0b0b0; border-radius: 8px;
  background: #fff; font: inherit; font-size: 14px;
}
.filters input { flex: 1 1 240px; }

.list { background: #ffffff; border: 1px dashed #9a9a9a; border-radius: 6px; padding: 4px 18px; box-sizing: border-box; }
.row {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  padding: 14px 0; border-bottom: 1px dashed #e2e2e2; text-decoration: none; color: inherit;
}
.row:last-child { border-bottom: none; }
.row:hover .row-name { text-decoration: underline; }
.row-main { display: flex; flex-direction: column; gap: 3px; }
.row-name { font-size: 14px; font-weight: 600; color: #2a2a2a; }
.row-meta { font-size: 12px; color: #8a8a8a; text-transform: capitalize; }

.status { font-size: 11px; font-weight: 600; border-radius: 10px; padding: 3px 10px; white-space: nowrap; }
.status-available { color: #0f6e6a; background: #ddf3f1; }
.status-maintenance { color: #8a6d00; background: #fff4c2; }
.status-retired { color: #6a6a6a; background: #f0f0f0; }
</style>
