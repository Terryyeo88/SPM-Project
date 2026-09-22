import { describe, expect, it } from 'vitest'
import { ROLES, ROUTE_ACCESS, NAV_LINKS, hasAnyRole } from './roles'

function visibleLinks(userRoles) {
  return NAV_LINKS.filter((link) => hasAnyRole(userRoles, link.roles)).map((link) => link.routeName)
}

// Routes a role may reach, gated or not -- what router/index.js enforces
// (a superset of visibleLinks(): it also includes inNav:false routes).
function reachableRoutes(userRoles) {
  return ROUTE_ACCESS.filter((entry) => hasAnyRole(userRoles, entry.roles)).map((entry) => entry.routeName)
}

describe('hasAnyRole', () => {
  it('matches a single role against a single-role allow-list', () => {
    expect(hasAnyRole([ROLES.EVENT_ORGANIZER], [ROLES.EVENT_ORGANIZER])).toBe(true)
  })

  it('rejects a role that is not in the allow-list', () => {
    expect(hasAnyRole([ROLES.ATTENDEE], [ROLES.EVENT_ORGANIZER])).toBe(false)
  })

  // -- Boundary/edge cases, not just the happy path --

  it('treats an empty user-roles array as no access, not a crash', () => {
    expect(hasAnyRole([], [ROLES.EVENT_ORGANIZER])).toBe(false)
  })

  it('treats an empty allow-list as no role ever matching', () => {
    expect(hasAnyRole([ROLES.EVENT_ORGANIZER], [])).toBe(false)
  })

  it('does not throw on undefined userRoles (defensive against a not-yet-loaded profile)', () => {
    expect(hasAnyRole(undefined, [ROLES.EVENT_ORGANIZER])).toBe(false)
  })

  it('does not throw on null userRoles', () => {
    expect(hasAnyRole(null, [ROLES.EVENT_ORGANIZER])).toBe(false)
  })

  it('is a UNION check for multi-role users -- matches on ANY held role, not just the first', () => {
    // The exact case Terry flagged: a user with roles[0] that does NOT
    // match must still pass if a LATER role in the array does.
    expect(hasAnyRole([ROLES.ATTENDEE, ROLES.EVENT_COORDINATOR], [ROLES.EVENT_COORDINATOR])).toBe(true)
  })

  it('result is independent of the order roles appear in', () => {
    const a = hasAnyRole([ROLES.EVENT_COORDINATOR, ROLES.VENUE_STAFF], [ROLES.VENUE_STAFF])
    const b = hasAnyRole([ROLES.VENUE_STAFF, ROLES.EVENT_COORDINATOR], [ROLES.VENUE_STAFF])
    expect(a).toBe(b)
    expect(a).toBe(true)
  })

  it('duplicate roles in the user-roles array do not change the outcome', () => {
    expect(hasAnyRole([ROLES.EVENT_ORGANIZER, ROLES.EVENT_ORGANIZER], [ROLES.EVENT_ORGANIZER])).toBe(true)
  })

  it('is case-sensitive -- roles are lowercase per the backend Postgres enum, no fuzzy matching', () => {
    expect(hasAnyRole(['EVENT_ORGANIZER'], [ROLES.EVENT_ORGANIZER])).toBe(false)
  })

  it('an unrecognised role string (e.g. a role added to the backend enum before this file is updated) matches nothing, rather than throwing', () => {
    expect(hasAnyRole(['some_future_role'], [ROLES.EVENT_ORGANIZER])).toBe(false)
    expect(() => hasAnyRole(['some_future_role'], [ROLES.EVENT_ORGANIZER])).not.toThrow()
  })
})

describe('ROUTE_ACCESS / NAV_LINKS structural sanity (hand-maintained tables -- catch a malformed entry at test time, not at runtime)', () => {
  it('every entry has a non-empty routeName, label, roles array and boolean inNav', () => {
    for (const entry of ROUTE_ACCESS) {
      expect(typeof entry.routeName).toBe('string')
      expect(entry.routeName.length).toBeGreaterThan(0)
      expect(typeof entry.label).toBe('string')
      expect(entry.label.length).toBeGreaterThan(0)
      expect(Array.isArray(entry.roles)).toBe(true)
      expect(entry.roles.length).toBeGreaterThan(0)
      expect(typeof entry.inNav).toBe('boolean')
    }
  })

  it('routeName is unique across all entries (a duplicate would silently shadow the other in the router lookup and in v-for :key)', () => {
    const names = ROUTE_ACCESS.map((e) => e.routeName)
    expect(new Set(names).size).toBe(names.length)
  })

  it('no entry lists the same role twice', () => {
    for (const entry of ROUTE_ACCESS) {
      expect(new Set(entry.roles).size).toBe(entry.roles.length)
    }
  })

  it('every role referenced is a real, known ROLES value (catches a typo like "event_oragnizer")', () => {
    const knownRoles = new Set(Object.values(ROLES))
    for (const entry of ROUTE_ACCESS) {
      for (const role of entry.roles) {
        expect(knownRoles.has(role)).toBe(true)
      }
    }
  })

  it('ROUTE_ACCESS, every entry, and every entry\'s roles array are frozen (mutating any of them would silently change what every importer sees)', () => {
    expect(Object.isFrozen(ROUTE_ACCESS)).toBe(true)
    for (const entry of ROUTE_ACCESS) {
      expect(Object.isFrozen(entry)).toBe(true)
      expect(Object.isFrozen(entry.roles)).toBe(true)
    }
    expect(Object.isFrozen(NAV_LINKS)).toBe(true)
  })

  it('a caller cannot mutate the table: pushing onto a roles array throws in strict mode instead of silently widening access', () => {
    expect(() => ROUTE_ACCESS[0].roles.push(ROLES.ATTENDEE)).toThrow(TypeError)
  })

  it('NAV_LINKS is exactly the inNav entries of ROUTE_ACCESS, same objects, same order (so nav and routing can never disagree)', () => {
    expect(NAV_LINKS).toEqual(ROUTE_ACCESS.filter((e) => e.inNav))
    NAV_LINKS.forEach((link, i) => {
      expect(link).toBe(ROUTE_ACCESS.filter((e) => e.inNav)[i])
    })
  })

  it('event-details is role-gated but has no dashboard link (a detail page reached from a list, not the nav)', () => {
    expect(ROUTE_ACCESS.some((e) => e.routeName === 'event-details')).toBe(true)
    expect(NAV_LINKS.some((l) => l.routeName === 'event-details')).toBe(false)
  })
})

describe('visible links per role (integration of hasAnyRole + NAV_LINKS, mirroring DashboardView.vue and router/index.js)', () => {
  it('event_organizer sees Events and Create event, and nothing else', () => {
    expect(visibleLinks([ROLES.EVENT_ORGANIZER]).sort()).toEqual(['create-event', 'events'].sort())
  })

  it('event_coordinator sees the sections built for them, but NOT Create event (organiser-only)', () => {
    expect(visibleLinks([ROLES.EVENT_COORDINATOR]).sort()).toEqual(
      ['events', 'reassign-coordinator', 'venues'].sort(),
    )
    expect(visibleLinks([ROLES.EVENT_COORDINATOR])).not.toContain('create-event')
  })

  it('create-event is reachable by event_organizer ONLY -- every other role is denied', () => {
    const others = Object.values(ROLES).filter((r) => r !== ROLES.EVENT_ORGANIZER)
    expect(reachableRoutes([ROLES.EVENT_ORGANIZER])).toContain('create-event')
    for (const role of others) {
      expect(reachableRoutes([role])).not.toContain('create-event')
    }
  })

  it('event-details is reachable by organiser and coordinator, and denied to venue_staff, technical_support_staff and attendee', () => {
    expect(reachableRoutes([ROLES.EVENT_ORGANIZER])).toContain('event-details')
    expect(reachableRoutes([ROLES.EVENT_COORDINATOR])).toContain('event-details')
    for (const role of [ROLES.VENUE_STAFF, ROLES.TECHNICAL_SUPPORT_STAFF, ROLES.ATTENDEE]) {
      expect(reachableRoutes([role])).not.toContain('event-details')
    }
  })

  it('a hidden (inNav:false) route is reachable even though it never shows in visibleLinks()', () => {
    expect(visibleLinks([ROLES.EVENT_ORGANIZER])).not.toContain('event-details')
    expect(reachableRoutes([ROLES.EVENT_ORGANIZER])).toContain('event-details')
  })

  it('venue_staff sees only Venues', () => {
    expect(visibleLinks([ROLES.VENUE_STAFF])).toEqual(['venues'])
  })

  it('attendee sees nothing (Attendee Registration is explicitly deferred, not a bug)', () => {
    expect(visibleLinks([ROLES.ATTENDEE])).toEqual([])
  })

  it('technical_support_staff sees nothing (Equipment features explicitly deferred)', () => {
    expect(visibleLinks([ROLES.TECHNICAL_SUPPORT_STAFF])).toEqual([])
  })

  it('a multi-role user (coordinator + venue_staff) sees the UNION, not just one role\'s links', () => {
    expect(visibleLinks([ROLES.EVENT_COORDINATOR, ROLES.VENUE_STAFF]).sort()).toEqual(
      ['events', 'reassign-coordinator', 'venues'].sort(),
    )
  })

  it('a multi-role user with no overlapping single link still gets the full union (organizer + venue_staff)', () => {
    expect(visibleLinks([ROLES.EVENT_ORGANIZER, ROLES.VENUE_STAFF]).sort()).toEqual(
      ['create-event', 'events', 'venues'].sort(),
    )
  })

  it('a user who is BOTH organiser and coordinator gets Create event AND Reassign Coordinator (union across the two roles)', () => {
    expect(visibleLinks([ROLES.EVENT_ORGANIZER, ROLES.EVENT_COORDINATOR]).sort()).toEqual(
      ['create-event', 'events', 'reassign-coordinator', 'venues'].sort(),
    )
  })

  it('holding every role at once yields the union of everything, each link exactly once', () => {
    const all = visibleLinks(Object.values(ROLES))
    expect(all.sort()).toEqual(['create-event', 'events', 'reassign-coordinator', 'venues'].sort())
    expect(new Set(all).size).toBe(all.length)
  })

  it('an empty roles array sees nothing', () => {
    expect(visibleLinks([])).toEqual([])
  })
})
