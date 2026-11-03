<script setup>
/**
 * Attendee dashboard, laid out after the Dashboard-Attendee wireframe:
 *
 *   Search bar       -- event name and date. Searching (even with nothing
 *                       typed, to browse everything) swaps the sections
 *                       below for a grid of session cards tagged Open /
 *                       Almost Full / Waitlist Only (or Opens Soon /
 *                       Registration Closed). Each card shows the
 *                       session's confirmed venue(s) (View Event Venue);
 *                       searching by venue is deliberately not built.
 *                       The results hold every confirmed session, with or
 *                       without registration, each labelled "Registration
 *                       required" / "No registration required" (View Events
 *                       Without Registration).
 *   Registered Events / Waiting List -- collapsible, with counts: the
 *                       attendee's own registrations.
 *
 * Everything links to the attendee event page (route `attendee-event`),
 * where Register / Withdraw happen.
 */
import { computed, onMounted, ref } from 'vue'
import { apiGet } from '../../lib/api'
import { formatDateRange } from '../../lib/coordinatorDashboard'
import {
  availabilityTag,
  filterSessions,
  registrationRequirementLabel,
  registrationStatusLabel,
  requiresRegistration,
  sessionWhen,
  venueSummary,
} from '../../lib/registrations'

const sessions = ref([])
const mine = ref([])
const loading = ref(true)
const error = ref('')

const query = ref('')
const date = ref('')
const searched = ref(false)
const applied = ref({ query: '', date: '' })
const registeredOpen = ref(true)
const waitlistOpen = ref(true)

const registered = computed(() => mine.value.filter((r) => r.status === 'confirmed'))
const waitlisted = computed(() => mine.value.filter((r) => r.status === 'waitlisted'))
const results = computed(() => filterSessions(sessions.value, applied.value))

async function load() {
  loading.value = true
  error.value = ''
  try {
    // One after the other, not Promise.all -- concurrent requests can 500
    // on Windows (see LeadDashboard.vue).
    mine.value = await apiGet('/registrations/mine')
    sessions.value = await apiGet('/registrations/open')
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    loading.value = false
  }
}

function search() {
  applied.value = { query: query.value, date: date.value }
  searched.value = true
}

function clearSearch() {
  query.value = ''
  date.value = ''
  applied.value = { query: '', date: '' }
  searched.value = false
}

function eventLink(eventId) {
  return { name: 'attendee-event', params: { eventId } }
}

onMounted(load)
</script>

<template>
  <section class="attendee-dashboard" aria-label="My events">
    <form class="searchbar" role="search" @submit.prevent="search">
      <div class="search-field grow">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#9a9a9a" stroke-width="2"
          stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        <span class="search-text">
          <label for="attendee-search" class="search-label">Event</label>
          <input id="attendee-search" v-model="query" type="search" placeholder="Search by event name" />
        </span>
      </div>
      <div class="search-field">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#9a9a9a" stroke-width="2"
          stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <rect x="3" y="4" width="18" height="18" rx="2" /><line x1="16" y1="2" x2="16" y2="6" />
          <line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" />
        </svg>
        <span class="search-text">
          <label for="attendee-date" class="search-label">Date</label>
          <input id="attendee-date" v-model="date" type="date" />
        </span>
      </div>
      <button type="submit" class="search-button">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"
          stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <circle cx="11" cy="11" r="7" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
        </svg>
        Search
      </button>
    </form>

    <p v-if="loading" class="muted">Loading your events...</p>
    <p v-else-if="error" class="error" role="alert">Couldn't load events: {{ error }}</p>

    <template v-else-if="!searched">
      <div class="section">
        <button type="button" class="section-head" :class="{ open: registeredOpen }" :aria-expanded="registeredOpen"
          @click="registeredOpen = !registeredOpen">
          <span class="section-title">Registered Events <span class="count">{{ registered.length }}</span></span>
          <span class="chevron" aria-hidden="true">&#9662;</span>
        </button>
        <div v-if="registeredOpen" class="section-body">
          <p v-if="!registered.length" class="muted empty">
            You haven't registered for any events yet. Search above to find one.
          </p>
          <router-link v-for="r in registered" :key="r.id" :to="eventLink(r.event_id)" class="row">
            <span class="row-main">
              <span class="row-name">{{ r.session?.name || 'Event' }}</span>
              <span class="muted small">{{ sessionWhen(r.session, formatDateRange) }}</span>
            </span>
            <span class="badge badge-confirmed">{{ registrationStatusLabel(r) }}</span>
          </router-link>
        </div>
      </div>

      <div class="section">
        <button type="button" class="section-head" :class="{ open: waitlistOpen }" :aria-expanded="waitlistOpen"
          @click="waitlistOpen = !waitlistOpen">
          <span class="section-title">Waiting List <span class="count">{{ waitlisted.length }}</span></span>
          <span class="chevron" aria-hidden="true">&#9662;</span>
        </button>
        <div v-if="waitlistOpen" class="section-body">
          <p v-if="!waitlisted.length" class="muted empty">You're not on any waiting lists.</p>
          <router-link v-for="r in waitlisted" :key="r.id" :to="eventLink(r.event_id)" class="row">
            <span class="row-main">
              <span class="row-name">{{ r.session?.name || 'Event' }}</span>
              <span class="muted small">{{ sessionWhen(r.session, formatDateRange) }}</span>
            </span>
            <span class="badge badge-waitlisted">{{ registrationStatusLabel(r) }}</span>
          </router-link>
        </div>
      </div>
    </template>

    <template v-else>
      <div class="results-head">
        <span class="section-title">Search Results <span class="muted small">{{ results.length }} found</span></span>
        <button type="button" class="link-button" @click="clearSearch">&#10005; Clear search</button>
      </div>
      <p v-if="!results.length" class="muted">No events match your search.</p>
      <div class="grid">
        <router-link v-for="s in results" :key="s.id" :to="eventLink(s.id)" class="card">
          <span class="card-name">{{ s.name }}</span>
          <span class="muted small">{{ sessionWhen(s, formatDateRange) }}</span>
          <span class="venue small">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#9a9a9a" stroke-width="2"
              stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <path d="M21 10c0 7-9 13-9 13S3 17 3 10a9 9 0 0 1 18 0z" /><circle cx="12" cy="10" r="3" />
            </svg>
            {{ venueSummary(s) }}
          </span>
          <span class="requirement" :class="{ 'requirement-none': !requiresRegistration(s) }">
            {{ registrationRequirementLabel(s) }}
          </span>
          <span class="card-foot">
            <span v-if="availabilityTag(s)" class="tag" :class="`tag-${availabilityTag(s).tone}`">
              {{ availabilityTag(s).label }}
            </span>
            <span v-else />
            <span class="view">View &rarr;</span>
          </span>
        </router-link>
      </div>
    </template>
  </section>
</template>

<style scoped>
.attendee-dashboard { display: flex; flex-direction: column; gap: var(--cs-space-6); margin-top: 1.5rem; }
.muted { color: var(--cs-ink-soft); }
.small { font-size: var(--cs-text-xs); }
.error { color: var(--cs-occupied); }
.empty { margin: 0; padding: var(--cs-space-4) 0; font-size: var(--cs-text-sm); }

.searchbar {
  display: flex; align-items: stretch; min-height: 72px; background: var(--cs-surface); border: 1px solid var(--cs-line);
  border-radius: var(--cs-radius-md); overflow: hidden; box-shadow: var(--cs-shadow-sm);
}
.search-field {
  flex: 1; min-width: 0; display: flex; align-items: center; gap: var(--cs-space-3); padding: var(--cs-space-3) var(--cs-space-5);
  border-right: 1px solid var(--cs-line);
}
.search-field.grow { flex: 1.3; }
.search-text { display: flex; flex-direction: column; gap: 3px; min-width: 0; flex: 1; }
.search-label { font-size: var(--cs-text-xs); font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: var(--cs-ink-soft); }
.search-text input { border: none; outline: none; background: transparent; font: inherit; font-size: var(--cs-text-base); color: var(--cs-ink); padding: 0; width: 100%; }
.search-field:focus-within { box-shadow: inset 0 0 0 2px var(--cs-signal); }
.search-button {
  flex: 0 0 132px; border: none; background: var(--cs-signal); color: #fff; font: inherit; font-size: var(--cs-text-base); font-weight: 700;
  display: flex; align-items: center; justify-content: center; gap: var(--cs-space-2); cursor: pointer;
}
.search-button:hover { background: var(--cs-signal-strong); }
.search-button:focus-visible { outline: 2px solid var(--cs-signal-strong); outline-offset: -4px; }

.section { display: flex; flex-direction: column; }
.section-head {
  min-height: 52px; background: var(--cs-surface); border: 1px solid var(--cs-line); border-radius: var(--cs-radius-sm); padding: 0 var(--cs-space-5);
  display: flex; align-items: center; justify-content: space-between; font: inherit; text-align: left; cursor: pointer;
}
.section-head.open { border-radius: var(--cs-radius-sm) var(--cs-radius-sm) 0 0; }
.section-head:focus-visible, .row:focus-visible, .card:focus-visible, .link-button:focus-visible {
  outline: 2px solid var(--cs-signal); outline-offset: 2px;
}
.section-title { display: flex; align-items: center; gap: var(--cs-space-3); font-size: var(--cs-text-md); font-weight: 700; color: var(--cs-ink); }
.count { font-size: var(--cs-text-xs); font-weight: 600; color: var(--cs-ink-soft); background: var(--cs-neutral-tint); border-radius: var(--cs-radius-full); padding: 2px 9px; }
.chevron { font-size: var(--cs-text-xs); color: var(--cs-ink-soft); transform: rotate(-90deg); transition: transform 0.15s; }
.section-head.open .chevron { transform: rotate(0deg); }
.section-body { background: var(--cs-paper); border: 1px solid var(--cs-line); border-top: none; border-radius: 0 0 var(--cs-radius-sm) var(--cs-radius-sm); padding: 4px var(--cs-space-5); }
.row {
  display: flex; align-items: center; justify-content: space-between; gap: var(--cs-space-3); padding: var(--cs-space-4) 0;
  border-bottom: 1px solid var(--cs-line); color: inherit; text-decoration: none;
}
.row:last-child { border-bottom: none; }
.row:hover .row-name { text-decoration: underline; }
.row-main { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.row-name { font-size: var(--cs-text-sm); font-weight: 600; color: var(--cs-ink); }
.badge { font-size: var(--cs-text-xs); font-weight: 600; border-radius: var(--cs-radius-full); padding: 3px 10px; white-space: nowrap; }
.badge-confirmed { background: var(--cs-available-tint); color: var(--cs-available); }
.badge-waitlisted { background: var(--cs-pending-tint); color: var(--cs-pending); }

.results-head { display: flex; align-items: center; justify-content: space-between; }
.link-button { border: none; background: transparent; font: inherit; font-size: var(--cs-text-sm); color: var(--cs-ink-soft); text-decoration: underline; cursor: pointer; padding: 0; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: var(--cs-space-5); }
.card {
  display: flex; flex-direction: column; gap: var(--cs-space-2); padding: var(--cs-space-4); background: var(--cs-surface); border: 1px solid var(--cs-line);
  border-radius: var(--cs-radius-md); color: inherit; text-decoration: none; min-height: 120px; box-sizing: border-box;
}
.card:hover { border-color: var(--cs-line-strong); }
.card:hover .card-name { text-decoration: underline; }
.card-name { font-size: var(--cs-text-sm); font-weight: 700; color: var(--cs-ink); line-height: 1.3; }
.card-foot { display: flex; align-items: center; justify-content: space-between; margin-top: auto; padding-top: var(--cs-space-2); }
.view { font-size: var(--cs-text-xs); font-weight: 600; color: var(--cs-ink); }
.venue { display: flex; align-items: center; gap: 5px; color: var(--cs-ink-soft); }
.requirement { font-size: var(--cs-text-xs); font-weight: 600; color: var(--cs-signal-strong); }
.requirement-none { color: var(--cs-ink-soft); }
.tag { font-size: var(--cs-text-xs); font-weight: 600; border-radius: var(--cs-radius-full); padding: 3px 10px; }
.tag-open { background: var(--cs-available-tint); color: var(--cs-available); }
.tag-warn { background: var(--cs-pending-tint); color: var(--cs-pending); }
.tag-full { background: var(--cs-occupied-tint); color: var(--cs-occupied); }
.tag-muted { background: var(--cs-neutral-tint); color: var(--cs-neutral); }

@media (max-width: 700px) {
  .searchbar { flex-direction: column; }
  .search-field { border-right: none; border-bottom: 1px solid var(--cs-line); }
  .search-button { flex: 0 0 48px; }
}
</style>
