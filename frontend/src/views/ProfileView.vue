<script setup>
/**
 * "My Profile" -- opened from the profile icon in the nav bar. Laid out
 * after the Edit Profile wireframe. Name, email, organisation and roles
 * are read-only (organisation comes from outside the system). Phone
 * Number and Communication Preferences are the user's own to edit
 * (IS-68), saved with PATCH /me/profile -- see lib/profile.js for the
 * rules. Sign out lives here since the header no longer has it.
 */
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppNavBar from '../components/AppNavBar.vue'
import {
  SG_PREFIX,
  preferencesError,
  profileForm,
  profilePayload,
  profilePhoneError,
  saveProfile,
  smsDisabled,
} from '../lib/profile'
import { roleLabel } from '../lib/roles'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()

// IS-68: contact details and preferences, from GET /me (auth.profile).
const contact = reactive(profileForm(auth.profile))
const saving = ref(false)
const saved = ref(false)
const saveError = ref('')

watch(() => auth.profile, (profile) => Object.assign(contact, profileForm(profile)))

const errors = computed(() => ({
  phone: profilePhoneError(contact.phone),
  preferences: preferencesError(contact),
}))
const smsLocked = computed(() => smsDisabled(contact))

async function handleSave() {
  saved.value = false
  saveError.value = ''
  if (Object.values(errors.value).some(Boolean)) return
  saving.value = true
  try {
    const result = await saveProfile(profilePayload(contact))
    // Keep the store in step, so the register form prefills from it too.
    auth.profile = { ...auth.profile, ...result }
    saved.value = true
  } catch (requestError) {
    saveError.value = requestError.message
  } finally {
    saving.value = false
  }
}

async function handleSignOut() {
  // try/finally: local state is already cleared by auth.signOut() even
  // if its Supabase network call failed (see the store's own comment),
  // so the user should still land on /login either way.
  try {
    await auth.signOut()
  } finally {
    router.push({ name: 'login' })
  }
}
</script>

<template>
  <div class="cs-page">
    <AppNavBar />

    <main class="cs-content">
      <div class="cs-container cs-container--narrow centered">
        <router-link :to="{ name: 'dashboard' }" class="back">&larr; Back to Dashboard</router-link>

        <section class="card cs-card" aria-labelledby="profile-heading">
          <div>
            <h1 id="profile-heading">My Profile</h1>
            <p class="muted">Your account details.</p>
          </div>

          <div class="photo" aria-hidden="true">
            <svg width="34" height="34" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"
              stroke-linecap="round" stroke-linejoin="round">
              <circle cx="12" cy="8" r="4" />
              <path d="M4 20c0-4 3.5-7 8-7s8 3 8 7" />
            </svg>
          </div>

          <hr />

          <p v-if="auth.profileLoadError" class="error" role="alert">
            Couldn't load your profile: {{ auth.profileLoadError }} -- try refreshing.
          </p>
          <p v-else-if="!auth.profile" class="muted">Loading your profile...</p>
          <dl v-else>
            <div class="field">
              <dt>Full Name</dt>
              <dd>{{ auth.profile.name }}</dd>
            </div>
            <div class="field">
              <dt>Email</dt>
              <dd>{{ auth.profile.email }}</dd>
            </div>
            <div class="field">
              <dt>Organisation</dt>
              <dd>
                <span v-if="auth.profile.organisation">{{ auth.profile.organisation }}</span>
                <span v-else class="muted">None</span>
              </dd>
            </div>
            <div class="field">
              <dt>{{ auth.profile.roles.length > 1 ? 'Roles' : 'Role' }}</dt>
              <dd>
                <span v-for="role in auth.profile.roles" :key="role" class="role">{{ roleLabel(role) }}</span>
                <span v-if="!auth.profile.roles.length">None</span>
              </dd>
            </div>
          </dl>

          <form v-if="auth.profile" class="contact" novalidate @submit.prevent="handleSave">
            <div class="field">
              <label for="profile-phone">Phone Number (optional)</label>
              <div class="phone">
                <span class="prefix" aria-hidden="true">{{ SG_PREFIX }}</span>
                <input
                  id="profile-phone"
                  v-model="contact.phone"
                  type="tel"
                  inputmode="numeric"
                  autocomplete="tel-national"
                  placeholder="9123 4567"
                  maxlength="9"
                  aria-describedby="profile-phone-hint"
                  :aria-invalid="Boolean(errors.phone)"
                  @input="saved = false"
                />
              </div>
              <p id="profile-phone-hint" class="muted">Singapore number: the 8 digits after +65.</p>
              <p v-if="errors.phone" class="field-error">{{ errors.phone }}</p>
            </div>

            <fieldset class="field">
              <legend>Communication Preferences</legend>
              <label class="check">
                <input id="profile-notify-email" v-model="contact.notify_email" type="checkbox" @change="saved = false" />
                Email notifications
              </label>
              <label class="check" :class="{ locked: smsLocked }">
                <input
                  id="profile-notify-sms"
                  v-model="contact.notify_sms"
                  type="checkbox"
                  :disabled="smsLocked"
                  aria-describedby="profile-sms-hint"
                  @change="saved = false"
                />
                SMS notifications
              </label>
              <p v-if="smsLocked" id="profile-sms-hint" class="muted">Add a phone number to choose SMS.</p>
              <p v-if="errors.preferences" class="field-error">{{ errors.preferences }}</p>
            </fieldset>

            <p v-if="saveError" class="error" role="alert">Couldn't save: {{ saveError }}</p>
            <p v-if="saved" class="saved" role="status">Saved.</p>

            <button type="submit" class="save" :disabled="saving">{{ saving ? 'Saving...' : 'Save' }}</button>
          </form>

          <hr />

          <button type="button" class="sign-out" @click="handleSignOut">Sign out</button>
        </section>
      </div>
    </main>
  </div>
</template>

<style scoped>
.centered { align-items: center; }
.back { align-self: flex-start; font-size: var(--cs-text-sm); color: var(--cs-ink-soft); }
.card {
  width: 100%; max-width: 560px; box-sizing: border-box;
  display: flex; flex-direction: column; gap: var(--cs-space-5);
  padding: var(--cs-space-7) var(--cs-space-7);
}
h1 { margin: 0 0 4px; font-size: var(--cs-text-xl); color: var(--cs-ink); }
.muted { margin: 0; font-size: var(--cs-text-sm); color: var(--cs-ink-soft); }
.photo {
  align-self: center; width: 84px; height: 84px; border-radius: 50%;
  border: 1px solid var(--cs-line-strong); background: var(--cs-neutral-tint); color: var(--cs-ink-soft);
  display: flex; align-items: center; justify-content: center;
}
hr { width: 100%; margin: 0; border: 0; border-top: 1px solid var(--cs-line); }
dl { margin: 0; display: flex; flex-direction: column; gap: var(--cs-space-5); }
.field { display: flex; flex-direction: column; gap: 6px; }
dt { font-size: var(--cs-text-xs); font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--cs-ink-soft); }
dd {
  margin: 0; min-height: 44px; box-sizing: border-box; display: flex; align-items: center; flex-wrap: wrap; gap: var(--cs-space-2);
  border: 1px solid var(--cs-line); border-radius: var(--cs-radius-sm); background: var(--cs-paper); padding: var(--cs-space-2) var(--cs-space-3); font-size: var(--cs-text-base); color: var(--cs-ink);
}
.role {
  font-size: var(--cs-text-xs); font-weight: 600; color: var(--cs-ink); background: var(--cs-neutral-tint); border-radius: var(--cs-radius-full); padding: 3px 10px;
}
.sign-out {
  height: 46px; border: 1px solid var(--cs-occupied); border-radius: var(--cs-radius-sm); background: var(--cs-surface);
  color: var(--cs-occupied); font: inherit; font-size: var(--cs-text-base); font-weight: 700; cursor: pointer;
}
.sign-out:hover { background: var(--cs-occupied-tint); }
.sign-out:focus-visible { outline: 2px solid var(--cs-signal); outline-offset: 2px; }
.error { margin: 0; color: var(--cs-occupied); font-size: var(--cs-text-sm); }
.contact { display: flex; flex-direction: column; gap: var(--cs-space-5); }
fieldset.field { margin: 0; padding: 0; border: 0; min-width: 0; }
.field > label, legend {
  padding: 0; font-size: var(--cs-text-xs); font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--cs-ink-soft);
}
.phone { display: flex; align-items: stretch; }
.prefix {
  display: flex; align-items: center; padding: 0 var(--cs-space-3); box-sizing: border-box; height: 44px;
  border: 1px solid var(--cs-line-strong); border-right: 0; border-radius: var(--cs-radius-sm) 0 0 var(--cs-radius-sm); background: var(--cs-neutral-tint);
  font-size: var(--cs-text-base); color: var(--cs-ink-soft);
}
.field input:not([type="checkbox"]) {
  height: 44px; box-sizing: border-box; border: 1px solid var(--cs-line-strong); border-radius: var(--cs-radius-sm); background: var(--cs-surface);
  padding: 0 var(--cs-space-3); font: inherit; font-size: var(--cs-text-base); color: var(--cs-ink);
}
.phone input:not([type="checkbox"]) { flex: 1 1 auto; min-width: 0; border-radius: 0 var(--cs-radius-sm) var(--cs-radius-sm) 0; }
.field input[aria-invalid="true"] { border-color: var(--cs-occupied); }
.check { display: flex; align-items: center; gap: var(--cs-space-3); font-size: var(--cs-text-sm); color: var(--cs-ink); }
.check.locked { color: var(--cs-ink-soft); }
.check input { width: 16px; height: 16px; margin: 0; }
.field-error { margin: 0; font-size: var(--cs-text-xs); color: var(--cs-occupied); }
.saved { margin: 0; font-size: var(--cs-text-sm); color: var(--cs-available); }
.save {
  height: 46px; border: 0; border-radius: var(--cs-radius-sm); background: var(--cs-signal);
  color: #ffffff; font: inherit; font-size: var(--cs-text-base); font-weight: 700; cursor: pointer;
}
.save:hover:not(:disabled) { background: var(--cs-signal-strong); }
.save:disabled { opacity: 0.6; cursor: default; }
.save:focus-visible { outline: 2px solid var(--cs-signal); outline-offset: 2px; }
@media (max-width: 600px) { .card { padding: var(--cs-space-5) var(--cs-space-4); } }
</style>
