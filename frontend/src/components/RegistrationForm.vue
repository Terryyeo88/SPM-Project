<script setup>
/**
 * The registration form behind the attendee event page's Register button
 * (Attendee Registration). Fields follow the Edit Profile wireframe:
 *
 *   Full Name        -- from the profile, shown read-only
 *   Email            -- prefilled from the profile, editable
 *   Phone Number     -- prefilled once profiles have it, editable
 *   Organisation     -- the profile's, read-only; the attendee only chooses
 *                       whether to include it (profiles don't have one yet)
 *   Communication Preferences -- Email notifications / SMS notifications,
 *                       either or both, at least one
 *   Notes            -- optional
 *
 * Emits `registered` with the new registration, or `cancel`.
 */
import { computed, reactive, ref } from 'vue'
import { apiPost } from '../lib/api'
import {
  NOTES_MAX_LENGTH,
  emailError,
  notesError,
  notifyError,
  phoneError,
  prefillFromProfile,
  registrationPayload,
} from '../lib/registrations'
import { useAuthStore } from '../stores/auth'

const props = defineProps({
  session: { type: Object, required: true },
})
const emit = defineEmits(['registered', 'cancel'])

const auth = useAuthStore()
const form = reactive(prefillFromProfile(auth.profile))
const touched = ref(false)
const submitting = ref(false)
const error = ref('')

const errors = computed(() => (touched.value
  ? {
      email: emailError(form.email),
      phone: phoneError(form.phone),
      notify: notifyError(form),
      notes: notesError(form.notes),
    }
  : { email: '', phone: '', notify: '', notes: notesError(form.notes) }))
const full = computed(() => props.session.places_left === 0)

async function submit() {
  touched.value = true
  if (Object.values(errors.value).some(Boolean)) return
  submitting.value = true
  error.value = ''
  try {
    const registration = await apiPost(`/registrations/${props.session.id}`, registrationPayload(form))
    emit('registered', registration)
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="backdrop" @click.self="emit('cancel')">
    <form
      class="dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby="register-title"
      novalidate
      @submit.prevent="submit"
      @keydown.esc="emit('cancel')"
    >
      <div class="heading">
        <h2 id="register-title">{{ full ? 'Join the Waiting List' : 'Register' }}</h2>
        <p class="muted">{{ session.name }}</p>
        <p v-if="full" class="notice">
          This session is full. You'll be added to the waiting list and moved up, first come first served,
          if a place frees up.
        </p>
      </div>

      <div class="field">
        <label for="reg-name">Full Name</label>
        <input id="reg-name" :value="form.name" type="text" readonly class="readonly" />
      </div>

      <div class="field">
        <label for="reg-email">Email</label>
        <input
          id="reg-email"
          v-model="form.email"
          type="email"
          autocomplete="email"
          :aria-invalid="Boolean(errors.email)"
          @blur="touched = true"
        />
        <p v-if="errors.email" class="field-error">{{ errors.email }}</p>
      </div>

      <div class="field">
        <label for="reg-phone">Phone Number</label>
        <input
          id="reg-phone"
          v-model="form.phone"
          type="tel"
          autocomplete="tel"
          placeholder="e.g. +65 9123 4567"
          :aria-invalid="Boolean(errors.phone)"
          @blur="touched = true"
        />
        <p v-if="errors.phone" class="field-error">{{ errors.phone }}</p>
      </div>

      <div class="field">
        <span class="label">Organisation (optional)</span>
        <template v-if="form.organisation">
          <input :value="form.organisation" type="text" readonly class="readonly" aria-label="Organisation" />
          <label class="check">
            <input v-model="form.include_organisation" type="checkbox" />
            Include my organisation in this registration
          </label>
        </template>
        <p v-else class="muted small">No organisation on your profile.</p>
      </div>

      <hr />

      <fieldset class="field">
        <legend class="label">Communication Preferences</legend>
        <label class="check">
          <input v-model="form.notify_email" type="checkbox" />
          Email notifications
        </label>
        <label class="check">
          <input v-model="form.notify_sms" type="checkbox" />
          SMS notifications
        </label>
        <p v-if="errors.notify" class="field-error">{{ errors.notify }}</p>
      </fieldset>

      <div class="field">
        <label for="reg-notes">Notes (optional)</label>
        <textarea
          id="reg-notes"
          v-model="form.notes"
          rows="2"
          :maxlength="NOTES_MAX_LENGTH"
          placeholder="Dietary or accessibility needs, anything the organiser should know"
        />
        <p v-if="errors.notes" class="field-error">{{ errors.notes }}</p>
      </div>

      <p v-if="error" class="field-error" role="alert">{{ error }}</p>

      <div class="actions">
        <button type="button" class="btn neutral" :disabled="submitting" @click="emit('cancel')">Cancel</button>
        <button type="submit" class="btn primary" :disabled="submitting">
          {{ submitting ? 'Submitting...' : full ? 'Join Waiting List' : 'Confirm Registration' }}
        </button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.backdrop {
  position: fixed; inset: 0; z-index: 50; background: rgba(0, 0, 0, 0.5);
  display: flex; align-items: flex-start; justify-content: center; padding: 48px 16px; overflow-y: auto;
}
.dialog {
  width: 100%; max-width: 560px; box-sizing: border-box; background: var(--cs-surface); border-radius: var(--cs-radius-md);
  border: 1px solid var(--cs-line); padding: var(--cs-space-6) var(--cs-space-7); display: flex; flex-direction: column; gap: var(--cs-space-4);
}
.heading { display: flex; flex-direction: column; gap: 4px; }
h2 { margin: 0; font-size: var(--cs-text-xl); font-family: var(--cs-font-display); color: var(--cs-ink); }
.muted { margin: 0; color: var(--cs-ink-soft); font-size: var(--cs-text-sm); }
.small { font-size: var(--cs-text-xs); }
.notice { margin: 6px 0 0; font-size: var(--cs-text-sm); color: var(--cs-pending); background: var(--cs-pending-tint); border: 1px solid var(--cs-pending); border-radius: var(--cs-radius-sm); padding: var(--cs-space-2) var(--cs-space-3); }

.field { display: flex; flex-direction: column; gap: 6px; margin: 0; padding: 0; border: none; min-width: 0; }
.field > label, .label { font-size: var(--cs-text-xs); font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--cs-ink-soft); padding: 0; }
input:not([type="checkbox"]), textarea {
  height: 44px; box-sizing: border-box; border: 1px solid var(--cs-line-strong); border-radius: var(--cs-radius-sm); background: var(--cs-surface);
  padding: 0 var(--cs-space-3); font: inherit; font-size: var(--cs-text-base); color: var(--cs-ink);
}
textarea { height: auto; padding: var(--cs-space-3); resize: vertical; }
input.readonly { background: var(--cs-neutral-tint); color: var(--cs-ink-soft); border-color: var(--cs-line); }
input[aria-invalid="true"] { border-color: var(--cs-occupied); }
.check { display: flex; align-items: center; gap: var(--cs-space-2); font-size: var(--cs-text-sm); color: var(--cs-ink); }
.check input { width: 16px; height: 16px; margin: 0; accent-color: var(--cs-signal); }
hr { border: none; border-top: 1px solid var(--cs-line); margin: 0; }
.field-error { margin: 0; font-size: var(--cs-text-xs); color: var(--cs-occupied); }

.actions { display: flex; gap: var(--cs-space-3); padding-top: 4px; }
.btn { flex: 1; height: 46px; border-radius: var(--cs-radius-sm); font: inherit; font-size: var(--cs-text-base); font-weight: 700; cursor: pointer; }
.btn:disabled { opacity: 0.6; cursor: default; }
.btn.primary { background: var(--cs-signal); border: 1px solid var(--cs-signal); color: #fff; }
.btn.primary:hover:not(:disabled) { background: var(--cs-signal-strong); border-color: var(--cs-signal-strong); }
.btn.neutral { background: var(--cs-surface); border: 1px solid var(--cs-line-strong); color: var(--cs-ink); font-weight: 600; }
.btn:focus-visible, input:focus-visible, textarea:focus-visible { outline: 2px solid var(--cs-signal); outline-offset: 2px; }
</style>
