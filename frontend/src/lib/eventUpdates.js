/**
 * Pure helpers behind IS-9 Update Event Information During Planning
 * (views/events/CoordinatorEventReview.vue's Edit Details), kept out of the
 * component so they can be unit-tested without mounting anything.
 *
 * Saving is two steps. POST /events/<id>/update-preview runs every check
 * and writes nothing; it answers
 *   { changes: { field: { from, to } }, significance, significant_fields,
 *     impacts: [{ area, severity, title, issues }],
 *     arrangements: [{ area, id, title, status, fields }], impacts_checked,
 *     reverts_to_planning }
 * (app.events.event_update.preview_event_update). If the update is
 * significant, touches arrangements already made (`arrangements`: every
 * venue booking, equipment request and the registrations it touches,
 * conflict or not; `impacts`: the conflicts among them), or would send a confirmed
 * event back to planning, the coordinator reviews that first; then
 * POST /events/<id> saves it, naming the impact areas they acknowledged.
 * Before planning (under review, approved) impacts aren't checked
 * (impacts_checked: false), so a significant change alone saves straight
 * away -- the coordinator edits freely.
 */
import { FIELD_LABELS, describeValue } from './changeRequests'

export const SIGNIFICANCE_LABELS = Object.freeze({
  significant: 'Significant change',
  ordinary: 'Ordinary change',
})

/** true if the preview found nothing to change. */
export function isNoChange(preview) {
  return Object.keys(preview?.changes ?? {}).length === 0
}

/** true if the coordinator should review the update before it's saved. */
export function needsReview(preview) {
  if (isNoChange(preview)) return false
  const checked = preview.impacts_checked !== false
  return (checked && preview.significance === 'significant')
    || impactsOfPreview(preview).length > 0
    || arrangementsOfPreview(preview).length > 0
    || Boolean(preview.reverts_to_planning)
}

export function impactsOfPreview(preview) {
  return Array.isArray(preview?.impacts) ? preview.impacts : []
}

export const ARRANGEMENT_AREA_LABELS = Object.freeze({
  venue: 'Venue',
  equipment: 'Equipment',
  registration: 'Registration',
})

/**
 * The arrangements already made that the update touches, ready to show:
 * [{ key, area, areaLabel, title, status, fields: 'Start date, ...', conflict }].
 * `conflict` is true when the preview's impacts flag a problem with it (a
 * venue impact names its booking; equipment and registration impacts cover
 * the whole area), so the coordinator can tell "touched" from "broken".
 */
export function arrangementsOfPreview(preview) {
  const arrangements = Array.isArray(preview?.arrangements) ? preview.arrangements : []
  const impacts = impactsOfPreview(preview)
  return arrangements.map((arrangement) => ({
    key: `${arrangement.area}:${arrangement.id ?? ''}`,
    area: arrangement.area,
    areaLabel: ARRANGEMENT_AREA_LABELS[arrangement.area] ?? arrangement.area,
    title: arrangement.title,
    status: arrangement.status ?? null,
    fields: (arrangement.fields ?? []).map((field) => FIELD_LABELS[field] ?? field).join(', '),
    conflict: impacts.some((impact) => impact.area === arrangement.area
      && (arrangement.area !== 'venue' || !impact.booking_id || impact.booking_id === arrangement.id)),
  }))
}

/** The distinct impact areas to acknowledge -- what the backend checks. */
export function previewImpactAreas(preview) {
  return [...new Set(impactsOfPreview(preview).map((impact) => impact.area))]
}

/** [{ field, label, from, to, significant }] in FIELD_LABELS order. */
export function describePreviewChanges(preview) {
  const changes = preview?.changes ?? {}
  const significant = new Set(preview?.significant_fields ?? [])
  return Object.keys(FIELD_LABELS)
    .filter((field) => field in changes)
    .map((field) => ({
      field,
      label: FIELD_LABELS[field],
      from: describeValue(field, changes[field]?.from),
      to: describeValue(field, changes[field]?.to),
      significant: significant.has(field),
    }))
}

/** The message shown once an update is saved. */
export function savedMessage(previousStatus, updated) {
  if (previousStatus === 'confirmed' && updated?.status === 'planning') {
    return 'Event details updated. The event was confirmed, so it is back In Planning until you confirm it again.'
  }
  return 'Event details updated.'
}
