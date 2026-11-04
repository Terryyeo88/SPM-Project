/**
 * The clarification thread on an event request (Event Review and Approval).
 *
 * One thread per event request, shared by every session. The assigned
 * coordinator asks (POST .../clarifications/request), the organiser who owns
 * the request answers (POST .../clarifications/reply) -- both only while the
 * request is under review, and the organiser only once the coordinator has
 * asked something. Neither changes the status. Anyone who may read the
 * thread (the organiser and the assigned coordinator) can still read it
 * after the request moves on (GET .../clarifications).
 *
 * The backend enforces every rule here; these helpers only let the page say
 * so before a round trip.
 */
import { apiGet, apiPost } from './api'

export const MAX_MESSAGE_LENGTH = 1000

export const fetchClarifications = (eventId) => apiGet(`/events/${eventId}/clarifications`)
export const sendClarificationRequest = (eventId, message) =>
  apiPost(`/events/${eventId}/clarifications/request`, { message })
export const sendClarificationReply = (eventId, message) =>
  apiPost(`/events/${eventId}/clarifications/reply`, { message })

/** '' when `text` can be sent, otherwise why not (same rules as the API). */
export function messageError(text) {
  const trimmed = (text ?? '').trim()
  if (!trimmed) return 'Enter a message before sending.'
  if (trimmed.length > MAX_MESSAGE_LENGTH) return `A message can't be longer than ${MAX_MESSAGE_LENGTH} characters.`
  return ''
}

/** "Alice Tan (Event Coordinator)" -- the side is the one saved with the
 * message, so a coordinator who has since been reassigned still reads as one. */
export function authorLabel(message) {
  const side = message.author_role === 'coordinator' ? 'Event Coordinator' : 'Event Organiser'
  return message.author_name ? `${message.author_name} (${side})` : side
}

export function coordinatorHasAsked(messages) {
  return (messages ?? []).some((message) => message.author_role === 'coordinator')
}

/** The organiser answers; they never open a thread (Request Change is for that). */
export function canOrganiserReply(event, messages) {
  return event?.status === 'under_review' && coordinatorHasAsked(messages)
}

export function messageTime(value) {
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
}
