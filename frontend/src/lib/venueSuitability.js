/**
 * Pure comparison between an event session's requirements and a venue's
 * capabilities -- the wireframe's "Suitability Check" panel on the
 * Booking Review screen. Independent of Terry's unbuilt Equipment
 * story, and independent of the turnaround-conflict half of that same
 * panel: conflict detection needs cross-booking knowledge (another
 * booking's span) that only the backend has, so it's server-computed
 * instead (see app.venues.booking_service.get_booking's `conflict`
 * field, read directly by the component -- not duplicated here).
 *
 * Each check is skipped (not reported as failing) when the event simply
 * doesn't record that requirement -- e.g. no accessibility_needs means
 * nothing to check, not an automatic pass or fail.
 */
export function checkSuitability(event, venue) {
  const checks = []

  if (event?.expected_attendance != null && venue?.capacity != null) {
    const ok = venue.capacity >= event.expected_attendance
    checks.push({
      label: 'Capacity',
      ok,
      detail: ok
        ? `Venue holds ${venue.capacity}, event expects ${event.expected_attendance}.`
        : `Venue holds only ${venue.capacity}, but the event expects ${event.expected_attendance}.`,
    })
  }

  if (event?.room_layout) {
    const ok = (venue?.supported_layouts ?? []).includes(event.room_layout)
    checks.push({
      label: 'Room layout',
      ok,
      detail: ok
        ? `Venue supports the requested "${event.room_layout}" layout.`
        : `Venue does not list "${event.room_layout}" among its supported layouts.`,
    })
  }

  const neededAccessibility = (event?.accessibility_needs ?? []).map((entry) => entry?.item ?? entry)
  if (neededAccessibility.length) {
    const provided = venue?.accessibility_features ?? []
    const missing = neededAccessibility.filter((item) => !provided.includes(item))
    checks.push({
      label: 'Accessibility',
      ok: missing.length === 0,
      detail: missing.length === 0
        ? 'Venue provides every accessibility feature the event needs.'
        : `Venue is missing: ${missing.join(', ')}.`,
    })
  }

  return checks
}
