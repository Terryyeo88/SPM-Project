/**
 * Venue Staff's venue-management API calls (Josiah, Sprint 3):
 * editing a venue's own timing settings ("Request Venue Booking with
 * Setup and Turnaround Time") and blocking a venue
 * ("Venue Becomes Unavailable After Booking"). Thin wrappers only -- see
 * backend/app/venues/venue_service.py::update_venue_settings and
 * backend/app/venues/block_service.py for the actual validation/logic.
 */
import { apiGet, apiPost } from './api'

export const updateVenueSettings = (venueId, fields) => apiPost(`/venues/${venueId}/settings`, fields)

export const listVenueBlocks = (venueId) => apiGet(`/venues/${venueId}/blocks`)

export const createVenueBlock = (venueId, body) => apiPost(`/venues/${venueId}/blocks`, body)

/** Mirrors the backend's venue_block_reason enum
 * (20261007000000_venue_calendar.sql) -- a closed set, not free text. */
export const VENUE_BLOCK_REASONS = Object.freeze([
  'maintenance',
  'renovation',
  'safety_issue',
  'internal_activity',
  'other',
])

/** "safety_issue" -> "Safety issue" */
export function blockReasonLabel(reason) {
  const text = (reason ?? '').replaceAll('_', ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}
