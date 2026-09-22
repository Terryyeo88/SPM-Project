/**
 * Role constants and the route -> roles table (ROUTE_ACCESS) used by both
 * DashboardView.vue (which links to show, via its NAV_LINKS subset) and
 * router/index.js (which routes to allow) -- a single shared table so
 * the two can never drift apart from each other (see router/index.js's
 * own comment on why it imports ROUTE_ACCESS rather than declaring its
 * own role list).
 *
 * Role strings MUST match the backend's `app_role` enum exactly (see
 * supabase/migrations/20260911120000_init_users_events.sql) -- these are
 * compared directly against what GET /me returns in `roles`, never
 * re-mapped or translated anywhere else.
 *
 * IS-27's "routed to a view appropriate to their role" criterion is
 * implemented as: everyone lands on the same Dashboard route, and the
 * dashboard's own content (which nav links it shows) adapts to the
 * caller's roles -- there is no separate per-role page/route. This was a
 * deliberate choice, not an assumption slipped in silently: Events and
 * Venues are still placeholders that belong to Aaralyn's and Nawaz's own
 * stories, so inventing new routes/pages here would mean guessing at
 * pages that are someone else's to design. Logged in
 * docs/open-questions.md for customer/instructor confirmation, following
 * the same pattern Terry used for event.cancel's status range.
 *
 * A user can hold MULTIPLE roles at once (confirmed in the schema
 * migration's own comment, and flagged again by Terry -- GET /me returns
 * `roles` as an array). `hasAnyRole` is therefore a UNION check: true if
 * the caller holds ANY of a link's allowed roles. This is the one place
 * that logic lives, so nothing importing this module can get it wrong by
 * checking only `roles[0]`.
 */

export const ROLES = Object.freeze({
  EVENT_ORGANIZER: 'event_organizer',
  EVENT_COORDINATOR: 'event_coordinator',
  VENUE_STAFF: 'venue_staff',
  TECHNICAL_SUPPORT_STAFF: 'technical_support_staff',
  ATTENDEE: 'attendee',
})

/**
 * true if `userRoles` (the array GET /me returns) contains AT LEAST ONE
 * of `allowedRoles`. Multi-role union check -- never assume a single
 * role, never index into userRoles.
 */
export function hasAnyRole(userRoles, allowedRoles) {
  return (userRoles ?? []).some((role) => allowedRoles.includes(role))
}

/**
 * Which route each role can reach, and why -- the ONE table behind both
 * route-level gating (router/index.js reads `roles` into each route's
 * `meta.roles`) and nav-link visibility (DashboardView.vue reads
 * NAV_LINKS, the `inNav` subset below). Reading both from the same array
 * is what stops them drifting apart: they did once, when a teammate's
 * new /create-event route got its own inline `meta.roles` plus a
 * hardcoded nav `v-if`, a second copy of the same decision.
 *
 * `routeName` is the ONLY pointer to the route -- deliberately NOT also
 * carrying the route's `path`, which would be a second,
 * independently-maintainable copy of what router/index.js's own route
 * table already owns and could silently go stale against (e.g. a
 * renamed path). Both consumers resolve the actual path from
 * vue-router's live route table instead. router/index.test.js asserts
 * every routeName here really is a registered route.
 *
 * `inNav: false` is for routes that need a role gate but no dashboard
 * link (a detail page reached from a list, not from the nav).
 *
 * This mapping itself is a judgement call: the acceptance criteria say
 * access should depend on role, but never say which role owns which
 * section. Reasoning used per route, so it can be checked/disputed:
 *
 *   events              -- Event Request Creation is organiser-only, and
 *                           View Assigned Event Requests is
 *                           coordinator-only (both named in the Week 4
 *                           instructions), so both roles get this entry
 *                           point.
 *   venues              -- Week 4 instructions, Venue Catalogue: "needed
 *                           by Event Coordinators and Venue Staff when
 *                           planning events" -- quoted directly, not
 *                           inferred.
 *   reassign-coordinator -- app/authz/rules.py::
 *                           rule_event_reassign_coordinator only ever
 *                           allows the currently-assigned coordinator;
 *                           showing/serving this to a role that could
 *                           never pass that check would be misleading,
 *                           so it's gated to event_coordinator here too.
 *                           The backend still re-checks per-event -- the
 *                           gate here (both the nav link AND, via
 *                           router/index.js, the route itself) is
 *                           belt-and-braces, not the real enforcement.
 *   create-event        -- Create Event Request story: "As an Event
 *                           Organizer, I can create an event request";
 *                           app/authz/rules.py::rule_event_create allows
 *                           event_organizer only.
 *   event-details       -- app/authz/rules.py::rule_event_view allows the
 *                           owning organiser and the ASSIGNED
 *                           coordinator. Only the role half of that is
 *                           checked here (the frontend can't know
 *                           ownership or assignment ahead of the fetch);
 *                           the per-event relationship stays the
 *                           backend's job, and a non-owner still gets a
 *                           404 from GET /events/<id>. Not a nav link:
 *                           it's reached from the events list and after
 *                           creating an event.
 *
 * Attendee and Technical Support Staff intentionally unlock nothing yet:
 * Attendee Registration and Equipment features aren't built this sprint
 * (see docs/traceability.md, "Explicitly deferred"). That's correct for
 * now, not a bug -- DashboardView shows a fallback message rather than a
 * blank/broken-looking nav for these roles.
 */
export const ROUTE_ACCESS = Object.freeze(
  [
    {
      routeName: 'events',
      label: 'Events',
      roles: [ROLES.EVENT_ORGANIZER, ROLES.EVENT_COORDINATOR],
      inNav: true,
    },
    {
      routeName: 'create-event',
      label: 'Create event',
      roles: [ROLES.EVENT_ORGANIZER],
      inNav: true,
    },
    {
      routeName: 'venues',
      label: 'Venues',
      roles: [ROLES.EVENT_COORDINATOR, ROLES.VENUE_STAFF],
      inNav: true,
    },
    {
      routeName: 'reassign-coordinator',
      label: 'Reassign Coordinator',
      roles: [ROLES.EVENT_COORDINATOR],
      inNav: true,
    },
    {
      routeName: 'event-details',
      label: 'Event details',
      roles: [ROLES.EVENT_ORGANIZER, ROLES.EVENT_COORDINATOR],
      inNav: false,
    },
    // Object.freeze() on the outer array is shallow -- it stops entries
    // being added/removed/reordered, but without also freezing (and
    // freezing each entry's own `roles` array) each element, a caller
    // could still mutate e.g. ROUTE_ACCESS[0].roles.push(...) and
    // silently change what any importer sees.
  ].map((entry) => Object.freeze({ ...entry, roles: Object.freeze(entry.roles) })),
)

/** The dashboard-link subset of ROUTE_ACCESS, in the same order. */
export const NAV_LINKS = Object.freeze(ROUTE_ACCESS.filter((entry) => entry.inNav))
