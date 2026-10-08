<script setup>
/**
 * The event's audit trail (GET /events/<id>/logs): what was asked for and
 * what was changed on the request after it was submitted, who did it, and
 * when. The organiser can only REQUEST changes (kind "requested"); the
 * coordinator's edits and approvals take effect (kind "changed").
 * Read-only; entries are written by the backend (app.events.event_log).
 * One entry per change, for the whole request (event_logs is keyed by
 * shared_event_id, not by session).
 */
import { ref, watch } from 'vue'
import { apiGet } from '../lib/api'
import { describeLogEntry } from '../lib/changeRequests'

const props = defineProps({
  event: { type: Object, required: true },
  // Bump to reload, e.g. after an approval wrote a new entry.
  refreshKey: { type: Number, default: 0 },
})

const entries = ref([])
const loading = ref(true)
const error = ref('')

function when(value) {
  return value ? new Date(value).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : ''
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    entries.value = await apiGet(`/events/${props.event.id}/logs`)
  } catch (requestError) {
    error.value = `Couldn't load the change history: ${requestError.message}`
  } finally {
    loading.value = false
  }
}

watch(() => [props.event.id, props.refreshKey], load, { immediate: true })
</script>

<template>
  <section class="card" aria-labelledby="event-log-heading">
    <h2 id="event-log-heading" class="card-title">Change History</h2>
    <p v-if="loading" class="muted small">Loading change history...</p>
    <p v-else-if="error" class="message error" role="alert">{{ error }}</p>
    <p v-else-if="!entries.length" class="muted small">No changes have been requested or made since this request was submitted.</p>
    <ol v-else class="log">
      <li v-for="entry in entries" :key="entry.event_log_id" class="entry">
        <div class="entry-header">
          <span class="entry-title" :class="`kind-${entry.kind}`">
            {{ entry.kind === 'requested' ? 'Change requested by' : 'Changed by' }} {{ entry.profiles?.name || 'unknown user' }}
          </span>
          <span class="muted small">{{ when(entry.changed_at) }}</span>
        </div>
        <ul class="changes">
          <li v-for="change in describeLogEntry(entry)" :key="change.field">
            <strong>{{ change.label }}:</strong> {{ change.from }} &rarr; {{ change.to }}
          </li>
        </ul>
      </li>
    </ol>
  </section>
</template>

<style scoped src="../styles/event-form.css"></style>
<style scoped>
.muted { color: #6b6b6b; }
.small { font-size: 13px; margin: 0; }
.message { margin: 0; font-size: 14px; }
.error { color: #b42318; }
.log { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 12px; }
.entry { border-left: 3px solid #b0b0b0; padding: 4px 0 4px 12px; display: flex; flex-direction: column; gap: 6px; }
.entry-header { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.entry-title { font-size: 13px; font-weight: 600; color: #333; }
.entry:has(.kind-requested) { border-left-color: #d9b779; }
.kind-requested { color: #8a5a12; }
.changes { margin: 0; padding-left: 18px; font-size: 13px; color: #2a2a2a; display: flex; flex-direction: column; gap: 4px; overflow-wrap: anywhere; }
</style>
