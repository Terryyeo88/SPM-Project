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
.muted { color: var(--cs-ink-soft); }
.small { font-size: var(--cs-text-sm); margin: 0; }
.message { margin: 0; font-size: var(--cs-text-base); }
.error { color: var(--cs-occupied); }
.log { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--cs-space-3); }
.entry { border-left: 3px solid var(--cs-line-strong); padding: 4px 0 4px var(--cs-space-3); display: flex; flex-direction: column; gap: 6px; }
.entry-header { display: flex; justify-content: space-between; gap: var(--cs-space-3); flex-wrap: wrap; }
.entry-title { font-size: var(--cs-text-sm); font-weight: 600; color: var(--cs-ink); }
.entry:has(.kind-requested) { border-left-color: var(--cs-pending); }
.kind-requested { color: var(--cs-pending); }
.significance { margin-left: var(--cs-space-2); font-size: var(--cs-text-xs); font-weight: 600; border-radius: var(--cs-radius-full); padding: 1px 8px; background: var(--cs-neutral-tint); color: var(--cs-neutral); }
.significance-significant { background: var(--cs-pending-tint); color: var(--cs-pending); }
.session { margin-right: var(--cs-space-2); font-size: var(--cs-text-xs); font-weight: 700; border-radius: var(--cs-radius-full); padding: 1px 8px; background: var(--cs-available-tint); color: var(--cs-available); }
.session-all { background: var(--cs-neutral-tint); color: var(--cs-neutral); }
.pager { display: flex; align-items: center; justify-content: space-between; gap: var(--cs-space-3); flex-wrap: wrap; padding-top: 4px; }
.pager-btn {
  min-height: 34px; padding: 0 var(--cs-space-4); border: 1px solid var(--cs-line-strong); border-radius: var(--cs-radius-sm); background: var(--cs-surface);
  font: inherit; font-size: var(--cs-text-sm); font-weight: 600; color: var(--cs-ink); cursor: pointer;
}
.pager-btn:disabled { opacity: .5; cursor: not-allowed; }
.pager-btn:focus-visible { outline: 2px solid var(--cs-signal); outline-offset: 2px; }
.changes { margin: 0; padding-left: 18px; font-size: var(--cs-text-sm); color: var(--cs-ink); display: flex; flex-direction: column; gap: 4px; overflow-wrap: anywhere; }
</style>
