/**
 * Room layouts come from the backend (GET /room-layouts), where Venue Staff
 * add, rename and delete them -- they're no longer a fixed list here. Also
 * the calls behind the Room Layouts page.
 */
import { apiDelete, apiGet, apiPost } from './api'

let inFlight = null

/**
 * Names of the active room layouts. Calls made while one is already in
 * flight (several session cards mounting on one page) share it; each new
 * form fetches afresh, so a layout Venue Staff just added shows up.
 */
export function fetchRoomLayouts() {
  if (!inFlight) {
    inFlight = apiGet('/room-layouts')
      .then((rows) => (rows ?? []).map((row) => row.name))
      .finally(() => {
        inFlight = null
      })
  }
  return inFlight
}

/**
 * Options for a session's layout picker, as [{ value, label, retired }]:
 * the active layouts, plus `kept` -- the layout the session already had --
 * if it has since been soft-deleted. The backend lets a session keep that
 * layout, so the picker mustn't silently blank it.
 */
export function roomLayoutOptions(active, kept) {
  const options = active.map((name) => ({ value: name, label: name, retired: false }))
  if (kept && !active.includes(kept)) {
    options.push({ value: kept, label: `${kept} (no longer offered)`, retired: true })
  }
  return options
}

// -- Venue Staff: managing layouts (RoomLayoutsView) ------------------------

/** Every layout, soft-deleted ones included ({room_layout_id, name, is_active}). */
export const listAllRoomLayouts = () => apiGet('/room-layouts?include_inactive=true')
export const createRoomLayout = (name) => apiPost('/room-layouts', { name })
export const renameRoomLayout = (id, name) => apiPost(`/room-layouts/${id}`, { name })
export const softDeleteRoomLayout = (id) => apiDelete(`/room-layouts/${id}`)
export const restoreRoomLayout = (id) => apiPost(`/room-layouts/${id}/restore`, {})
/** Refused (409) unless soft-deleted and every event using it is completed or cancelled. */
export const deleteRoomLayout = (id) => apiDelete(`/room-layouts/${id}/permanent`)
