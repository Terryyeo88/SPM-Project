/**
 * Pure helpers behind the profile page's contact details and
 * communication preferences (IS-68).
 *
 * Agreed acceptance criteria (31 Oct):
 *   - only phone and the two preferences are editable; name, email and
 *     organisation are shown read-only
 *   - phone is optional; when given it is +65 followed by 8 digits
 *   - email is selected by default and at least one preference stays on
 *   - SMS can only be selected when there is a phone number
 *
 * The values come from GET /me (auth.profile) and are saved with
 * PATCH /me/profile -- the caller's own profile, never one named by id.
 * The page shows "+65" as a fixed prefix and the user types the 8 digits;
 * the backend stores "+6591234567". The backend checks every rule here
 * again (app/me/profile_service.py), so these only give earlier feedback.
 */
import { apiPatch } from './api'

export const SG_PREFIX = '+65'

// The two preference messages match the backend's word for word. The phone
// message is worded for the input beside the fixed "+65".
export const PHONE_FORMAT_MESSAGE = 'Enter the 8 digits after +65, e.g. 9123 4567.'
export const AT_LEAST_ONE_MESSAGE = 'Choose at least one way to be contacted: email or SMS.'
export const SMS_NEEDS_PHONE_MESSAGE = 'Add a phone number to turn on SMS notifications.'

const LOCAL_DIGITS = /^[0-9]{8}$/

/** "9123 4567" / "9123-4567" -> "91234567". */
function digitsOnly(value) {
  return (value ?? '').replace(/[\s-]/g, '')
}

/** "+6591234567" (as stored) -> "9123 4567" for the input beside "+65". */
export function localPart(phone) {
  const digits = digitsOnly(phone)
  const local = digits.startsWith(SG_PREFIX) ? digits.slice(SG_PREFIX.length) : digits
  return LOCAL_DIGITS.test(local) ? `${local.slice(0, 4)} ${local.slice(4)}` : local
}

/** Is a phone number filled in on the form (valid or not)? */
export function hasPhone(form) {
  return digitsOnly(form.phone) !== ''
}

/** The form's starting values from the signed-in user's profile. A
 * profile that has never been edited has the column defaults (email on,
 * SMS off); a missing value falls back to the same. */
export function profileForm(profile) {
  return {
    phone: localPart(profile?.phone),
    notify_email: typeof profile?.notify_email === 'boolean' ? profile.notify_email : true,
    notify_sms: typeof profile?.notify_sms === 'boolean' ? profile.notify_sms : false,
  }
}

/** The PATCH /me/profile body. Always all three; a blank phone is null,
 * so clearing it works. Never id, email or organisation. */
export function profilePayload(form) {
  const digits = digitsOnly(form.phone)
  return {
    phone: digits ? `${SG_PREFIX}${digits}` : null,
    notify_email: Boolean(form.notify_email),
    notify_sms: Boolean(form.notify_sms),
  }
}

/** Error for the phone field, or ''. Blank is fine: it's optional. */
export function profilePhoneError(phone) {
  const digits = digitsOnly(phone)
  return !digits || LOCAL_DIGITS.test(digits) ? '' : PHONE_FORMAT_MESSAGE
}

/** Error for the communication preferences, or ''. */
export function preferencesError(form) {
  if (!form.notify_email && !form.notify_sms) return AT_LEAST_ONE_MESSAGE
  if (form.notify_sms && !hasPhone(form)) return SMS_NEEDS_PHONE_MESSAGE
  return ''
}

/** Whether the SMS checkbox is disabled: only while it is unticked and
 * there is no phone. Once ticked it stays usable, so a user who clears
 * the phone can still untick SMS (the save is refused until they do). */
export function smsDisabled(form) {
  return !form.notify_sms && !hasPhone(form)
}

/** Saves the caller's own profile; resolves to the four fields as saved. */
export function saveProfile(payload) {
  return apiPatch('/me/profile', payload)
}
