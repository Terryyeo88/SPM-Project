/**
 * Search Venues by Event Requirements (Nawaz, Sprint 2, IS-12). Pure
 * client-side filter over the venue catalogue -- no new backend route:
 * GET /venues already returns every field this searches on (capacity,
 * location, supported_layouts, accessibility_features, facilities), and
 * the catalogue is small enough (seeded with 4 venues; nothing in the
 * AC implies this needs to scale past a department's worth of rooms)
 * that filtering the already-fetched list in the browser is simpler
 * than adding query params the backend would have to validate and
 * index for. If the catalogue ever gets large, this is the one place
 * to swap for a server-side filter -- the criteria shape below is
 * already exactly what such an endpoint's query params would be.
 *
 * AC: "Can apply more than one criterion at once, and results satisfy
 * ALL criteria applied" -- every criterion below is AND'ed together,
 * never OR'ed. An unset criterion (null/empty) imposes no constraint,
 * which is also what lets the caller "clear or change criteria... without
 * re-entering the unchanged" ones: the criteria object only ever holds
 * what the user actually set.
 *
 * "Venues that have been retired or withdrawn... do not appear in
 * results": there is no such concept anywhere in the schema yet (see
 * docs/open-questions.md) -- venues.status is available/occupied/
 * maintenance, none of which means retired. This filter has nothing to
 * exclude on that basis; flagged, not silently assumed away.
 */
export function filterVenues(venues, criteria = {}) {
  const minCapacity = criteria.minCapacity ?? null
  const location = (criteria.location ?? '').trim().toLowerCase()
  const roomLayout = criteria.roomLayout ?? ''
  const accessibilityFeatures = criteria.accessibilityFeatures ?? []
  const facilities = criteria.facilities ?? []

  return (venues ?? []).filter((venue) => {
    if (minCapacity != null && (venue.capacity ?? 0) < minCapacity) return false
    if (location && !(venue.location ?? '').toLowerCase().includes(location)) return false
    if (roomLayout && !(venue.supported_layouts ?? []).includes(roomLayout)) return false
    if (accessibilityFeatures.length) {
      const provided = venue.accessibility_features ?? []
      if (!accessibilityFeatures.every((feature) => provided.includes(feature))) return false
    }
    if (facilities.length) {
      const provided = venue.facilities ?? []
      if (!facilities.every((facility) => provided.includes(facility))) return false
    }
    return true
  })
}

/** True if any criterion is actually set -- distinguishes "browsing
 * everything" from "searched and got zero matches" for the AC's
 * explicit-empty-result requirement. */
export function hasActiveCriteria(criteria = {}) {
  return Boolean(
    criteria.minCapacity ||
      (criteria.location ?? '').trim() ||
      criteria.roomLayout ||
      (criteria.accessibilityFeatures ?? []).length ||
      (criteria.facilities ?? []).length,
  )
}
