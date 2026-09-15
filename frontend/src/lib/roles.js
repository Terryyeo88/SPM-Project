/**
 * Role constants and the role -> nav-link mapping used by DashboardView.
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
 * Which nav links each role can see, and why. This mapping is a
 * judgement call: the acceptance criteria say access should depend on
 * role, but never say which role owns which of these three placeholder
 * sections. Reasoning used per link, so it can be checked/disputed:
 *
 *   Events              -- Event Request Creation is organiser-only, and
 *                           View Assigned Event Requests is
 *                           coordinator-only (both named in the Week 4
 *                           instructions), so both roles get this entry
 *                           point.
 *   Venues              -- Week 4 instructions, Venue Catalogue: "needed
 *                           by Event Coordinators and Venue Staff when
 *                           planning events" -- quoted directly, not
 *                           inferred.
 *   Reassign Coordinator -- app/authz/rules.py::
 *                           rule_event_reassign_coordinator only ever
 *                           allows the currently-assigned coordinator;
 *                           showing this link to a role that could never
 *                           pass that check would be misleading, so it's
 *                           gated to event_coordinator here too. The
 *                           backend still re-checks per-event -- this is
 *                           belt-and-braces, not the real enforcement.
 *
 * Attendee and Technical Support Staff intentionally unlock nothing yet:
 * Attendee Registration and Equipment features aren't built this sprint
 * (see docs/traceability.md, "Explicitly deferred"). That's correct for
 * now, not a bug -- DashboardView shows a fallback message rather than a
 * blank/broken-looking nav for these roles.
 */
export const NAV_LINKS = Object.freeze([
  {
    to: '/events',
    routeName: 'events',
    label: 'Events',
    roles: [ROLES.EVENT_ORGANIZER, ROLES.EVENT_COORDINATOR],
  },
  {
    to: '/venues',
    routeName: 'venues',
    label: 'Venues',
    roles: [ROLES.EVENT_COORDINATOR, ROLES.VENUE_STAFF],
  },
  {
    to: '/events/reassign',
    routeName: 'reassign-coordinator',
    label: 'Reassign Coordinator',
    roles: [ROLES.EVENT_COORDINATOR],
  },
])
