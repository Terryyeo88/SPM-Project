import { describe, expect, it } from 'vitest'
import { ROLES, NAV_LINKS, hasAnyRole } from './roles'

function visibleLinks(userRoles) {
  return NAV_LINKS.filter((link) => hasAnyRole(userRoles, link.roles)).map((link) => link.routeName)
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

describe('NAV_LINKS structural sanity (this is a hand-maintained table -- catch a malformed entry at test time, not at runtime)', () => {
  it('every entry has a non-empty routeName, label, and roles array', () => {
    for (const link of NAV_LINKS) {
      expect(typeof link.routeName).toBe('string')
      expect(link.routeName.length).toBeGreaterThan(0)
      expect(typeof link.label).toBe('string')
      expect(link.label.length).toBeGreaterThan(0)
      expect(Array.isArray(link.roles)).toBe(true)
      expect(link.roles.length).toBeGreaterThan(0)
    }
  })

  it('routeName is unique across all links (no two links silently collapse into one v-for :key)', () => {
    const names = NAV_LINKS.map((l) => l.routeName)
    expect(new Set(names).size).toBe(names.length)
  })

  it('every role referenced in NAV_LINKS is a real, known ROLES value (catches a typo like "event_oragnizer")', () => {
    const knownRoles = new Set(Object.values(ROLES))
    for (const link of NAV_LINKS) {
      for (const role of link.roles) {
        expect(knownRoles.has(role)).toBe(true)
      }
    }
  })

  it('NAV_LINKS and its entries are frozen (accidental mutation from a caller would be a silent, hard-to-trace bug)', () => {
    expect(Object.isFrozen(NAV_LINKS)).toBe(true)
    for (const link of NAV_LINKS) {
      expect(Object.isFrozen(link)).toBe(true)
    }
  })
})

describe('visible links per role (integration of hasAnyRole + NAV_LINKS, mirroring DashboardView.vue and router/index.js)', () => {
  it('event_organizer sees exactly Events', () => {
    expect(visibleLinks([ROLES.EVENT_ORGANIZER])).toEqual(['events'])
  })

  it('event_coordinator sees all three sections built so far', () => {
    expect(visibleLinks([ROLES.EVENT_COORDINATOR]).sort()).toEqual(
      ['events', 'reassign-coordinator', 'venues'].sort(),
    )
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
    expect(visibleLinks([ROLES.EVENT_ORGANIZER, ROLES.VENUE_STAFF]).sort()).toEqual(['events', 'venues'].sort())
  })

  it('holding every role at once is still bounded by what actually exists -- not every role unlocks Reassign Coordinator', () => {
    expect(visibleLinks(Object.values(ROLES)).sort()).toEqual(['events', 'reassign-coordinator', 'venues'].sort())
  })

  it('an empty roles array sees nothing', () => {
    expect(visibleLinks([])).toEqual([])
  })
})
