<script setup>
/**
 * Venue Staff manage the room layouts event requests pick from and venues
 * list as supported (backend: app/room_layouts, room_layout.manage).
 *
 * Deleting is two steps, mirroring the backend:
 *   - Delete (soft): the layout can't be picked for new requests any more,
 *     and drafts using it have their layout cleared; submitted events and
 *     venues keep it. Restore makes it available again (cleared drafts
 *     stay cleared).
 *   - Delete permanently: only for a soft-deleted layout, and the backend
 *     refuses (409, message shown here) while any event using it isn't
 *     completed or cancelled. Events that used it keep its name.
 */
import { computed, onMounted, ref } from 'vue'
import AppNavBar from '../../components/AppNavBar.vue'
import {
  createRoomLayout,
  deleteRoomLayout,
  listAllRoomLayouts,
  renameRoomLayout,
  restoreRoomLayout,
  softDeleteRoomLayout,
} from '../../lib/roomLayouts'

const layouts = ref([])
const loading = ref(true)
const error = ref('')
const success = ref('')
const busy = ref(false)

const newName = ref('')
const editingId = ref(null)
const editName = ref('')

const activeLayouts = computed(() => layouts.value.filter((layout) => layout.is_active))
const deletedLayouts = computed(() => layouts.value.filter((layout) => !layout.is_active))

async function load() {
  loading.value = true
  error.value = ''
  try {
    layouts.value = await listAllRoomLayouts()
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    loading.value = false
  }
}

// Runs one change, then reloads the list. Clears the previous message first
// so an old success never sits next to a new error.
async function run(action, successMessage) {
  busy.value = true
  error.value = ''
  success.value = ''
  try {
    await action()
    success.value = successMessage
    await load()
    return true
  } catch (requestError) {
    error.value = requestError.message
    return false
  } finally {
    busy.value = false
  }
}

async function addLayout() {
  const name = newName.value.trim()
  if (!name) {
    error.value = 'Enter a name for the room layout.'
    success.value = ''
    return
  }
  if (await run(() => createRoomLayout(name), `Added "${name}".`)) newName.value = ''
}

function startRename(layout) {
  editingId.value = layout.room_layout_id
  editName.value = layout.name
}

function cancelRename() {
  editingId.value = null
}

async function saveRename(layout) {
  const name = editName.value.trim()
  if (!name || name === layout.name) {
    cancelRename()
    return
  }
  if (await run(() => renameRoomLayout(layout.room_layout_id, name), `Renamed "${layout.name}" to "${name}".`)) {
    cancelRename()
  }
}

function softDelete(layout) {
  return run(
    () => softDeleteRoomLayout(layout.room_layout_id),
    `Deleted "${layout.name}". It can no longer be chosen, and drafts using it now need a new layout. You can restore it.`,
  )
}

function restore(layout) {
  return run(() => restoreRoomLayout(layout.room_layout_id), `Restored "${layout.name}".`)
}

function deletePermanently(layout) {
  const confirmed = window.confirm(
    `Permanently delete "${layout.name}"? This can't be undone. Completed and cancelled events keep the name.`,
  )
  if (!confirmed) return
  return run(() => deleteRoomLayout(layout.room_layout_id), `Permanently deleted "${layout.name}".`)
}

onMounted(load)
</script>

<template>
  <div class="page">
    <AppNavBar />
    <main class="content">
      <div class="container">
        <div class="page-heading">
          <h1 class="page-title">Room Layouts</h1>
          <span class="page-subtitle">The layouts organisers choose from and venues list as supported.</span>
        </div>

        <p v-if="error" class="message error" role="alert">{{ error }}</p>
        <p v-if="success" class="message success" role="status">{{ success }}</p>

        <form class="card add-form" @submit.prevent="addLayout">
          <label class="field grow">
            <span class="field-label">New room layout</span>
            <input v-model="newName" class="input" type="text" placeholder="e.g. U-shape" maxlength="100" />
          </label>
          <button type="submit" class="btn btn-primary" :disabled="busy">Add layout</button>
        </form>

        <p v-if="loading" class="message">Loading room layouts...</p>
        <template v-else>
          <section class="card" aria-labelledby="active-heading">
            <h2 id="active-heading" class="card-title">Active ({{ activeLayouts.length }})</h2>
            <p v-if="activeLayouts.length === 0" class="message muted">No active room layouts.</p>
            <ul v-else class="layout-list">
              <li v-for="layout in activeLayouts" :key="layout.room_layout_id" class="layout-row" data-test="active-layout">
                <template v-if="editingId === layout.room_layout_id">
                  <input v-model="editName" class="input grow" type="text" :aria-label="`New name for ${layout.name}`" maxlength="100" @keyup.enter="saveRename(layout)" @keyup.escape="cancelRename" />
                  <button type="button" class="btn btn-primary" :disabled="busy" @click="saveRename(layout)">Save</button>
                  <button type="button" class="btn btn-outline" :disabled="busy" @click="cancelRename">Cancel</button>
                </template>
                <template v-else>
                  <span class="layout-name">{{ layout.name }}</span>
                  <button type="button" class="btn btn-outline" :disabled="busy" @click="startRename(layout)">Rename</button>
                  <button type="button" class="btn btn-danger" :disabled="busy" @click="softDelete(layout)">Delete</button>
                </template>
              </li>
            </ul>
          </section>

          <section class="card" aria-labelledby="deleted-heading">
            <h2 id="deleted-heading" class="card-title">Deleted ({{ deletedLayouts.length }})</h2>
            <p class="section-subtitle">
              Submitted events and venues already using these keep them; drafts had them cleared. A layout can be
              permanently deleted once every event using it is completed or cancelled.
            </p>
            <p v-if="deletedLayouts.length === 0" class="message muted">No deleted room layouts.</p>
            <ul v-else class="layout-list">
              <li v-for="layout in deletedLayouts" :key="layout.room_layout_id" class="layout-row" data-test="deleted-layout">
                <span class="layout-name muted">{{ layout.name }}</span>
                <button type="button" class="btn btn-outline" :disabled="busy" @click="restore(layout)">Restore</button>
                <button type="button" class="btn btn-danger" :disabled="busy" @click="deletePermanently(layout)">Delete permanently</button>
              </li>
            </ul>
          </section>
        </template>
      </div>
    </main>
  </div>
</template>

<style scoped src="../../styles/event-form.css"></style>
<style scoped>
.add-form { flex-direction: row; align-items: flex-end; gap: 12px; flex-wrap: wrap; }
.grow { flex: 1 1 220px; }
.layout-list { list-style: none; margin: 0; padding: 0; }
.layout-row {
  display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
  padding: 12px 0; border-bottom: 1px dashed #e2e2e2;
}
.layout-row:last-child { border-bottom: none; }
.layout-name { flex: 1 1 160px; font-size: 14px; font-weight: 600; color: #2a2a2a; text-transform: capitalize; }
.muted { color: #8a8a8a; }
</style>
