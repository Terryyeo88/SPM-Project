import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import DashboardView from '../views/DashboardView.vue'
import CreateEventView from '../views/events/CreateEventView.vue'
import EventDetailsView from '../views/events/EventDetailsView.vue'
import EventsListView from '../views/events/EventsListView.vue'
import ReassignCoordinatorView from '../views/events/ReassignCoordinatorView.vue'
import LoginView from '../views/LoginView.vue'
import VenueCatalogueView from '../views/venues/VenueCatalogueView.vue'
import VenueDetailView from '../views/venues/VenueDetailView.vue'

const routes = [
  { path: '/login', name: 'login', component: LoginView, meta: { public: true } },
  { path: '/', name: 'dashboard', component: DashboardView },
  { path: '/events', name: 'events', component: EventsListView },
  { path: '/events/:eventId', name: 'event-details', component: EventDetailsView },
  { path: '/create-event', name: 'create-event', component: CreateEventView, meta: { roles: ['event_organizer'] } },
  { path: '/events/reassign', name: 'reassign-coordinator', component: ReassignCoordinatorView },
  {
    path: '/venues',
    name: 'venues',
    component: VenueCatalogueView,
    meta: { roles: ['event_coordinator', 'venue_staff'] },
  },
  {
    path: '/venues/:venueId',
    name: 'venue-details',
    component: VenueDetailView,
    meta: { roles: ['event_coordinator', 'venue_staff'] },
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()

  // On a hard refresh, Pinia's state is empty even though Supabase still
  // has a valid session sitting in local storage -- restore it once
  // before making any auth decisions.
  if (!auth.restored) {
    await auth.restoreSession()
  }

  if (!to.meta.public && !auth.isLoggedIn) {
    return { name: 'login' }
  }
  if (to.meta.roles && !to.meta.roles.some((role) => auth.roles.includes(role))) {
    return { name: 'dashboard' }
  }
  if (to.name === 'login' && auth.isLoggedIn) {
    return { name: 'dashboard' }
  }
})

export default router
