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
  position: fixed; inset: 0; z-index: 50; background: rgba(0, 0, 0, 0.35);
  display: flex; align-items: flex-start; justify-content: center; padding: 48px 16px; overflow-y: auto;
}
.dialog {
  width: 100%; max-width: 560px; box-sizing: border-box; background: #fff; border-radius: 6px;
  border: 1px solid #b0b0b0; padding: 32px 36px; display: flex; flex-direction: column; gap: 18px;
}
.heading { display: flex; flex-direction: column; gap: 4px; }
h2 { margin: 0; font-size: 20px; color: #1f1f1f; }
.muted { margin: 0; color: #6b6b6b; font-size: 13px; }
.small { font-size: 12px; }
.notice { margin: 6px 0 0; font-size: 13px; color: #8a5a12; background: #fdf6ec; border: 1px solid #e3b877; border-radius: 4px; padding: 8px 10px; }

.field { display: flex; flex-direction: column; gap: 6px; margin: 0; padding: 0; border: none; min-width: 0; }
.field > label, .label { font-size: 11px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: #6a6a6a; padding: 0; }
input:not([type="checkbox"]), textarea {
  height: 44px; box-sizing: border-box; border: 1px solid #b0b0b0; border-radius: 4px; background: #fafafa;
  padding: 0 12px; font: inherit; font-size: 14px; color: #333;
}
textarea { height: auto; padding: 10px 12px; resize: vertical; }
input.readonly { background: #efefef; color: #555; border-color: #d0d0d0; }
input[aria-invalid="true"] { border-color: #a33f3f; }
.check { display: flex; align-items: center; gap: 10px; font-size: 13px; color: #444; }
.check input { width: 16px; height: 16px; margin: 0; }
hr { border: none; border-top: 1px solid #e2e2e2; margin: 0; }
.field-error { margin: 0; font-size: 12px; color: #a33f3f; }

.actions { display: flex; gap: 12px; padding-top: 4px; }
.btn { flex: 1; height: 46px; border-radius: 4px; font: inherit; font-size: 14px; font-weight: 700; cursor: pointer; }
.btn:disabled { opacity: 0.6; cursor: default; }
.btn.primary { background: #2568e8; border: 1px solid #2568e8; color: #fff; }
.btn.neutral { background: #fff; border: 1px solid #b0b0b0; color: #444; font-weight: 600; }
.btn:focus-visible, input:focus-visible, textarea:focus-visible { outline: 2px solid #2568e8; outline-offset: 2px; }
</style>
