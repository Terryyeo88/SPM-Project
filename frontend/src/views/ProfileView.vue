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
  <div class="page">
    <AppNavBar />

    <main class="content">
      <div class="container">
        <router-link :to="{ name: 'dashboard' }" class="back">&larr; Back to Dashboard</router-link>

        <section class="card" aria-labelledby="profile-heading">
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
.page { min-height: 100vh; display: flex; flex-direction: column; background: #eeeeee; }
.content { flex: 1 1 auto; padding: 32px 16px; display: flex; justify-content: center; }
.container { width: 100%; max-width: 880px; display: flex; flex-direction: column; align-items: center; gap: 20px; }
.back { align-self: flex-start; font-size: 13px; color: #666666; }
.card {
  width: 100%; max-width: 560px; box-sizing: border-box;
  display: flex; flex-direction: column; gap: 22px;
  background: #ffffff; border: 1px solid #c9c9c9; border-radius: 6px; padding: 40px 44px;
}
h1 { margin: 0 0 4px; font-size: 20px; color: #1f1f1f; }
.muted { margin: 0; font-size: 13px; color: #6f6f6f; }
.photo {
  align-self: center; width: 84px; height: 84px; border-radius: 50%;
  border: 1px solid #b0b0b0; background: #f5f5f5; color: #9a9a9a;
  display: flex; align-items: center; justify-content: center;
}
hr { width: 100%; margin: 0; border: 0; border-top: 1px solid #e2e2e2; }
dl { margin: 0; display: flex; flex-direction: column; gap: 18px; }
.field { display: flex; flex-direction: column; gap: 6px; }
dt { font-size: 11px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: #6f6f6f; }
dd {
  margin: 0; min-height: 44px; box-sizing: border-box; display: flex; align-items: center; flex-wrap: wrap; gap: 8px;
  border: 1px solid #d8d8d8; border-radius: 4px; background: #fafafa; padding: 8px 12px; font-size: 14px; color: #333333;
}
.role {
  font-size: 12px; font-weight: 600; color: #444444; background: #ececec; border-radius: 10px; padding: 3px 10px;
}
.sign-out {
  height: 46px; border: 1px solid #a33f3f; border-radius: 4px; background: #ffffff;
  color: #a33f3f; font: inherit; font-size: 14px; font-weight: 700; cursor: pointer;
}
.sign-out:hover { background: #fbf1f1; }
.sign-out:focus-visible { outline: 2px solid #2568e8; outline-offset: 2px; }
.error { margin: 0; color: #a33f3f; font-size: 13px; }
.contact { display: flex; flex-direction: column; gap: 18px; }
fieldset.field { margin: 0; padding: 0; border: 0; min-width: 0; }
.field > label, legend {
  padding: 0; font-size: 11px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: #6f6f6f;
}
.phone { display: flex; align-items: stretch; }
.prefix {
  display: flex; align-items: center; padding: 0 12px; box-sizing: border-box; height: 44px;
  border: 1px solid #b0b0b0; border-right: 0; border-radius: 4px 0 0 4px; background: #f2f2f2;
  font-size: 14px; color: #555555;
}
.field input:not([type="checkbox"]) {
  height: 44px; box-sizing: border-box; border: 1px solid #b0b0b0; border-radius: 4px; background: #ffffff;
  padding: 0 12px; font: inherit; font-size: 14px; color: #333333;
}
.phone input:not([type="checkbox"]) { flex: 1 1 auto; min-width: 0; border-radius: 0 4px 4px 0; }
.field input[aria-invalid="true"] { border-color: #a33f3f; }
.check { display: flex; align-items: center; gap: 10px; font-size: 13px; color: #444444; }
.check.locked { color: #9a9a9a; }
.check input { width: 16px; height: 16px; margin: 0; }
.field-error { margin: 0; font-size: 12px; color: #a33f3f; }
.saved { margin: 0; font-size: 13px; color: #2f7a3e; }
.save {
  height: 46px; border: 0; border-radius: 4px; background: #2568e8;
  color: #ffffff; font: inherit; font-size: 14px; font-weight: 700; cursor: pointer;
}
.save:disabled { opacity: 0.6; cursor: default; }
.save:focus-visible { outline: 2px solid #2568e8; outline-offset: 2px; }
@media (max-width: 600px) { .card { padding: 24px 20px; } }
</style>
