/**
 * Pure helpers behind the profile page's contact details and
 * communication preferences (IS-68), after the Edit Profile wireframe:
 * Phone Number, Organisation (optional), Communication Preferences
 * (Email notifications / SMS notifications).
 *
 * The values come from GET /me (auth.profile) and are saved with
 * PATCH /me/profile -- the caller's own profile, never one named by id.
 * Each is null until given; blank text is sent as null.
 *
 * The two preferences start from the same values the register form
 * starts from (lib/registrations.js prefillFromProfile), so the profile
 * page shows what a new registration will default to. While the profile
 * has never saved a preference they stay null: they are only sent once
 * the user changes one (see profilePayload).
 */
import { apiPatch } from './api'
import { phoneError, prefillFromProfile } from './registrations'

/** Same limit as backend profile_service.ORGANISATION_MAX_LENGTH. */
export const ORGANISATION_MAX_LENGTH = 200

/** The form's starting values from the signed-in user's profile. */
export function profileForm(profile) {
  const prefill = prefillFromProfile(profile)
  return {
    phone: profile?.phone ?? '',
    organisation: profile?.organisation ?? '',
    notify_email: prefill.notify_email,
    notify_sms: prefill.notify_sms,
  }
}

/** Has this profile ever saved a communication preference? */
export function hasSavedPreferences(profile) {
  return typeof profile?.notify_email === 'boolean' || typeof profile?.notify_sms === 'boolean'
}

/**
 * The PATCH /me/profile body. Phone and organisation are always sent
 * (blank -> null, so clearing one works). The preferences are sent when
 * the profile already has them, or when the user changed one -- so saving
 * just a phone number doesn't turn "never chosen" into a choice.
 */
export function profilePayload(form, profile) {
  const payload = {
    phone: form.phone.trim() || null,
    organisation: form.organisation.trim() || null,
  }
  const start = profileForm(profile)
  const changed = form.notify_email !== start.notify_email || form.notify_sms !== start.notify_sms
  if (hasSavedPreferences(profile) || changed) {
    payload.notify_email = Boolean(form.notify_email)
    payload.notify_sms = Boolean(form.notify_sms)
  }
  return payload
}

/** Error for the phone field, or ''. Blank is fine: it's optional here. */
export function profilePhoneError(phone) {
  return (phone ?? '').trim() ? phoneError(phone) : ''
}

/** Error for the organisation field, or ''. */
export function organisationError(organisation) {
  return (organisation ?? '').trim().length > ORGANISATION_MAX_LENGTH
    ? `Organisation can be at most ${ORGANISATION_MAX_LENGTH} characters.`
    : ''
}

/** Saves the caller's own profile; resolves to the four fields as saved. */
export function saveProfile(payload) {
  return apiPatch('/me/profile', payload)
}
