<script setup>
/**
 * Attendee dashboard, laid out after the Dashboard-Attendee wireframe:
 *
 *   Search bar       -- event name and date. Searching (even with nothing
 *                       typed, to browse everything) swaps the sections
 *                       below for a grid of session cards tagged Open /
 *                       Almost Full / Waitlist Only (or Opens Soon /
 *                       Registration Closed). Location isn't searchable
 *                       yet: no event has a venue until venue booking exists.
 *   Registered Events / Waiting List -- collapsible, with counts: the
 *                       attendee's own registrations.
 *
 * Everything links to the attendee event page (route `attendee-event`),
 * where Register / Withdraw happen.
 */
import { computed, onMounted, ref } from 'vue'
import { apiGet } from '../../lib/api'
import { formatDateRange } from '../../lib/coordinatorDashboard'
import { availabilityTag, filterSessions, registrationStatusLabel, sessionWhen } from '../../lib/registrations'

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
          <span class="card-foot">
            <span class="tag" :class="`tag-${availabilityTag(s).tone}`">{{ availabilityTag(s).label }}</span>
            <span class="view">View &rarr;</span>
          </span>
        </router-link>
      </div>
    </template>
  </section>
</template>

<style scoped>
.attendee-dashboard { display: flex; flex-direction: column; gap: 24px; margin-top: 1.5rem; }
.muted { color: #6b6b6b; }
.small { font-size: 12px; }
.error { color: #a33f3f; }
.empty { margin: 0; padding: 14px 0; font-size: 13px; }

.searchbar {
  display: flex; align-items: stretch; min-height: 72px; background: #fff; border: 1px dashed #9a9a9a;
  border-radius: 10px; overflow: hidden; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}
.search-field {
  flex: 1; min-width: 0; display: flex; align-items: center; gap: 12px; padding: 10px 22px;
  border-right: 1px dashed #e2e2e2;
}
.search-field.grow { flex: 1.3; }
.search-text { display: flex; flex-direction: column; gap: 3px; min-width: 0; flex: 1; }
.search-label { font-size: 11px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: #8a8a8a; }
.search-text input { border: none; outline: none; background: transparent; font: inherit; font-size: 14px; color: #333; padding: 0; width: 100%; }
.search-field:focus-within { box-shadow: inset 0 0 0 2px #2568e8; }
.search-button {
  flex: 0 0 132px; border: none; background: #2568e8; color: #fff; font: inherit; font-size: 14px; font-weight: 700;
  display: flex; align-items: center; justify-content: center; gap: 8px; cursor: pointer;
}
.search-button:focus-visible { outline: 2px solid #1a4fb8; outline-offset: -4px; }

.section { display: flex; flex-direction: column; }
.section-head {
  min-height: 52px; background: #fff; border: 1px dashed #9a9a9a; border-radius: 4px; padding: 0 18px;
  display: flex; align-items: center; justify-content: space-between; font: inherit; text-align: left; cursor: pointer;
}
.section-head.open { border-radius: 4px 4px 0 0; }
.section-head:focus-visible, .row:focus-visible, .card:focus-visible, .link-button:focus-visible {
  outline: 2px solid #2568e8; outline-offset: 2px;
}
.section-title { display: flex; align-items: center; gap: 10px; font-size: 15px; font-weight: 700; color: #222; }
.count { font-size: 11px; font-weight: 600; color: #6a6a6a; background: #f0f0f0; border-radius: 10px; padding: 2px 9px; }
.chevron { font-size: 12px; color: #9a9a9a; transform: rotate(-90deg); transition: transform 0.15s; }
.section-head.open .chevron { transform: rotate(0deg); }
.section-body { background: #fafafa; border: 1px dashed #9a9a9a; border-top: none; border-radius: 0 0 4px 4px; padding: 4px 18px; }
.row {
  display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 14px 0;
  border-bottom: 1px dashed #e2e2e2; color: inherit; text-decoration: none;
}
.row:last-child { border-bottom: none; }
.row:hover .row-name { text-decoration: underline; }
.row-main { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
.row-name { font-size: 14px; font-weight: 600; color: #2a2a2a; }
.badge { font-size: 11px; font-weight: 600; border-radius: 10px; padding: 3px 10px; white-space: nowrap; }
.badge-confirmed { background: #eaf5ec; color: #2f6b3f; }
.badge-waitlisted { background: #f7efe1; color: #8a5a12; }

.results-head { display: flex; align-items: center; justify-content: space-between; }
.link-button { border: none; background: transparent; font: inherit; font-size: 13px; color: #555; text-decoration: underline; cursor: pointer; padding: 0; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 20px; }
.card {
  display: flex; flex-direction: column; gap: 8px; padding: 16px; background: #fff; border: 1px dashed #9a9a9a;
  border-radius: 6px; color: inherit; text-decoration: none; min-height: 120px; box-sizing: border-box;
}
.card:hover .card-name { text-decoration: underline; }
.card-name { font-size: 14px; font-weight: 700; color: #222; line-height: 1.3; }
.card-foot { display: flex; align-items: center; justify-content: space-between; margin-top: auto; padding-top: 8px; }
.view { font-size: 12px; font-weight: 600; color: #333; }
.tag { font-size: 11px; font-weight: 600; border-radius: 10px; padding: 3px 10px; }
.tag-open { background: #eaf5ec; color: #2f6b3f; }
.tag-warn { background: #f7efe1; color: #8a5a12; }
.tag-full { background: #f5e6e6; color: #a33f3f; }
.tag-muted { background: #f0f0f0; color: #5a5a5a; }

@media (max-width: 700px) {
  .searchbar { flex-direction: column; }
  .search-field { border-right: none; border-bottom: 1px dashed #e2e2e2; }
  .search-button { flex: 0 0 48px; }
}
</style>
