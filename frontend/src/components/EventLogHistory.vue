<script setup>
/**
 * The event's audit trail (GET /events/<id>/logs): what was asked for and
 * what was changed on the request after it was submitted, who did it, and
 * when. The organiser can only REQUEST changes (kind "requested"); the
 * coordinator's edits and approvals take effect (kind "changed").
 * Read-only; entries are written by the backend (app.events.event_log).
 * One entry per change, for the whole request (event_logs is keyed by
 * shared_event_id, not by session). IS-9: each entry is labelled a
 * significant or ordinary change, and a coordinator's update lists the
 * arrangements they acknowledged it would affect.
 *
 * Each entry names the session it was made on ("Session 2", numbered as the
 * request's session list is), or "All sessions" for a shared-detail change
 * the coordinator applied to every session (entry.session, from
 * app.events.event_log.list_event_logs; absent for a single-session request).
 *
 * Paged PAGE_SIZE entries at a time, newest first (lib/pagination). The
 * whole history is loaded in one call -- it's per request, so it stays small.
 */
import { computed, ref, watch } from 'vue'
import { apiGet } from '../lib/api'
import { describeLogEntry } from '../lib/changeRequests'
import { SIGNIFICANCE_LABELS } from '../lib/eventUpdates'
import { paginate } from '../lib/pagination'

const PAGE_SIZE = 5

const props = defineProps({
  event: { type: Object, required: true },
  // Bump to reload, e.g. after an approval wrote a new entry.
  refreshKey: { type: Number, default: 0 },
})

const entries = ref([])
const loading = ref(true)
const error = ref('')
const page = ref(1)
const pageView = computed(() => paginate(entries.value, page.value, PAGE_SIZE))

function goTo(target) {
  page.value = Math.min(Math.max(1, target), pageView.value.pageCount)
}

function when(value) {
  return value ? new Date(value).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : ''
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    entries.value = await apiGet(`/events/${props.event.id}/logs`)
    page.value = 1 // newest first: a reload (e.g. after a new change) starts at the latest
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
    <template v-else>
      <ol class="log">
        <li v-for="entry in pageView.items" :key="entry.event_log_id" class="entry">
          <div class="entry-header">
            <span class="entry-title" :class="`kind-${entry.kind}`">
              <span v-if="entry.session" class="session" :class="{ 'session-all': !entry.session.id }">
                {{ entry.session.label }}
              </span>
              {{ entry.kind === 'requested' ? 'Change requested by' : 'Changed by' }} {{ entry.profiles?.name || 'unknown user' }}
              <span v-if="entry.significance" class="significance" :class="`significance-${entry.significance}`">
                {{ SIGNIFICANCE_LABELS[entry.significance] ?? entry.significance }}
              </span>
            </span>
            <span class="muted small">{{ when(entry.changed_at) }}</span>
          </div>
          <ul class="changes">
            <li v-for="change in describeLogEntry(entry)" :key="change.field">
              <strong>{{ change.label }}:</strong> {{ change.from }} &rarr; {{ change.to }}
            </li>
          </ul>
          <p v-if="entry.acknowledged_impacts?.length" class="muted small">
            Saved knowing it affects: {{ entry.acknowledged_impacts.map((impact) => impact.title).join(', ') }}.
          </p>
        </li>
      </ol>
      <nav v-if="pageView.pageCount > 1" class="pager" aria-label="Change history pages">
        <button type="button" class="pager-btn" :disabled="pageView.page === 1" @click="goTo(pageView.page - 1)">
          &larr; Newer
        </button>
        <span class="muted small" aria-live="polite">
          {{ pageView.from }}–{{ pageView.to }} of {{ pageView.total }} · Page {{ pageView.page }} of {{ pageView.pageCount }}
        </span>
        <button type="button" class="pager-btn" :disabled="pageView.page === pageView.pageCount" @click="goTo(pageView.page + 1)">
          Older &rarr;
        </button>
      </nav>
    </template>
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
.significance { margin-left: 8px; font-size: 11px; font-weight: 600; border-radius: 8px; padding: 1px 8px; background: #eee; color: #5a5a5a; }
.significance-significant { background: #f7efe1; color: #8a5a12; }
.session { margin-right: 8px; font-size: 11px; font-weight: 700; border-radius: 8px; padding: 1px 8px; background: #e4eefb; color: #1f5a9e; }
.session-all { background: #eef0f3; color: #3f4a57; }
.pager { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; padding-top: 4px; }
.pager-btn {
  min-height: 34px; padding: 0 14px; border: 1px solid #b8b8b8; border-radius: 4px; background: #fff;
  font: inherit; font-size: 13px; font-weight: 600; color: #444; cursor: pointer;
}
.pager-btn:disabled { opacity: .5; cursor: not-allowed; }
.pager-btn:focus-visible { outline: 2px solid #2568e8; outline-offset: 2px; }
.changes { margin: 0; padding-left: 18px; font-size: 13px; color: #2a2a2a; display: flex; flex-direction: column; gap: 4px; overflow-wrap: anywhere; }
</style>
