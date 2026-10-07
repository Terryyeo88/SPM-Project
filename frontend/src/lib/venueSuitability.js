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

/**
 * Flag Unsuitable Venues for an Event (Nawaz, Sprint 2, IS-13). A
 * DIFFERENT function from checkSuitability above, not a reuse of it --
 * that one is Josiah's, for the Venue Staff Booking Review screen, and
 * its tests (venueSuitability.test.js) pin down that a missing
 * requirement is SILENTLY OMITTED from the result. IS-13's own AC
 * explicitly wants the opposite: "Given the event has requirements that
 * have not yet been recorded... the check reports which requirements
 * were not assessed" -- a visible entry, not an omission. Changing
 * checkSuitability itself to do that would break Josiah's screen and
 * its tests for a requirement that screen was never asked to meet, so
 * this is a sibling export instead, used only by the Coordinator-facing
 * "check a candidate before requesting" flow (RequestVenueBookingView.vue).
 *
 * Each check's `status` is one of:
 *   'suitable'     -- the requirement is recorded and the venue meets it
 *   'unsuitable'   -- the requirement is recorded and the venue does not
 *   'not_assessed' -- the requirement isn't recorded on the event (AC's
 *                     own "requirements that have not yet been recorded"
 *                     case), so there's nothing to compare against yet
 *
 * Facilities is ALWAYS 'not_assessed': unlike capacity/layout/
 * accessibility, there is no "required facilities" field anywhere on
 * `events` (only `equipment_needed`, a different, Technical-Support-
 * Staff-facing concept -- see docs/open-questions.md's entry on this).
 * The AC still names facilities as one of the four things to check
 * against, so it's listed here -- honestly, as unassessed -- rather
 * than silently dropped, which is exactly the AC's own escape valve for
 * a requirement the event simply never recorded.
 */
export function checkSuitabilityForEvent(event, venue) {
  const checks = []

  if (event?.expected_attendance != null) {
    const ok = (venue?.capacity ?? 0) >= event.expected_attendance
    checks.push({
      label: 'Capacity',
      status: ok ? 'suitable' : 'unsuitable',
      detail: ok
        ? `Venue holds ${venue?.capacity}, event expects ${event.expected_attendance}.`
        : `Venue holds only ${venue?.capacity ?? 0}, but the event expects ${event.expected_attendance}.`,
    })
  } else {
    checks.push({ label: 'Capacity', status: 'not_assessed', detail: "The event hasn't recorded an expected attendance yet." })
  }

  if (event?.room_layout) {
    const ok = (venue?.supported_layouts ?? []).includes(event.room_layout)
    checks.push({
      label: 'Room layout',
      status: ok ? 'suitable' : 'unsuitable',
      detail: ok
        ? `Venue supports the requested "${event.room_layout}" layout.`
        : `Venue does not list "${event.room_layout}" among its supported layouts.`,
    })
  } else {
    checks.push({ label: 'Room layout', status: 'not_assessed', detail: "The event hasn't recorded a required layout yet." })
  }

  const neededAccessibility = (event?.accessibility_needs ?? []).map((entry) => entry?.item ?? entry)
  if (neededAccessibility.length) {
    const provided = venue?.accessibility_features ?? []
    const missing = neededAccessibility.filter((item) => !provided.includes(item))
    checks.push({
      label: 'Accessibility',
      status: missing.length === 0 ? 'suitable' : 'unsuitable',
      detail: missing.length === 0
        ? 'Venue provides every accessibility feature the event needs.'
        : `Venue is missing: ${missing.join(', ')}.`,
    })
  } else {
    checks.push({
      label: 'Accessibility',
      status: 'not_assessed',
      detail: "The event hasn't recorded any accessibility needs yet.",
    })
  }

  checks.push({
    label: 'Facilities',
    status: 'not_assessed',
    detail: "ConnectSphere doesn't yet record which facilities an event requires (only equipment, which is separate) -- this can't be checked until that's built.",
  })

  return checks
}

/**
 * true if every ASSESSED check passed (not_assessed entries don't count
 * either way) -- the AC's "appearing suitable" / "flagged as unsuitable"
 * summary. A venue with nothing assessed yet (every requirement
 * not_assessed) reports as suitable by this rule -- there's nothing
 * recorded that it fails, which is a defensible reading, but it's also
 * exactly the ambiguity the AC's "not yet recorded" clause anticipates,
 * so the UI always shows the per-check breakdown alongside this summary
 * rather than the summary alone.
 */
export function isSuitableOverall(checks) {
  return checks.every((check) => check.status !== 'unsuitable')
}
