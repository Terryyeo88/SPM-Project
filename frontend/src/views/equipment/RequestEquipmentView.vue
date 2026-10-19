<script setup>
/**
 * Record Equipment Request for Event (Nawaz, Sprint 3, IS-17) -- the
 * assigned coordinator lists the equipment a session needs: one or more
 * lines, each with an equipment type, a quantity and optional free-text
 * technical requirements (POST /events/<eventId>/equipment-requests).
 *
 * Reached from the Equipment Booking section of the event page, which only
 * offers it while the event is in planning (same rule as the venue
 * request, enforced by the backend as well). The needed date and time are
 * the session's own, so they are shown here but not entered.
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { apiGet, apiPost } from '../../lib/api'
import AppNavBar from '../../components/AppNavBar.vue'
import { buildRequestPayload, equipmentTypeLabel, newRequestLine, validateRequestLines } from '../../lib/equipment'

const route = useRoute()
const router = useRouter()

const event = ref(null)
const types = ref([])
const lines = ref([newRequestLine()])
const loading = ref(true)
const loadError = ref('')
const submitting = ref(false)
const error = ref('')
const submitted = ref(false)

const check = computed(() => validateRequestLines(lines.value))
const canRequest = computed(() => event.value?.status === 'planning')

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [loadedEvent, loadedTypes] = await Promise.all([
      apiGet(`/events/${route.params.eventId}`),
      apiGet('/equipment/types'),
    ])
    event.value = loadedEvent
    types.value = loadedTypes
  } catch (requestError) {
    loadError.value = requestError.message
  } finally {
    loading.value = false
  }
}

function addLine() {
  lines.value.push(newRequestLine())
}

function removeLine(index) {
  lines.value.splice(index, 1)
}

// A type already chosen on another line is not offered again.
function optionDisabled(typeId, index) {
  return lines.value.some((line, i) => i !== index && line.equipment_type_id === typeId)
}

async function submit() {
  submitted.value = true
  error.value = ''
  if (!check.value.valid) return
  submitting.value = true
  try {
    await apiPost(`/events/${route.params.eventId}/equipment-requests`, buildRequestPayload(lines.value))
    router.push({ name: 'event-details', params: { eventId: route.params.eventId } })
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    submitting.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="page">
    <AppNavBar />
    <main class="content">
      <div class="container">
        <router-link :to="{ name: 'event-details', params: { eventId: route.params.eventId } }" class="back-link">
          &larr; Back to event
        </router-link>

        <p v-if="loading" class="message">Loading...</p>
        <p v-else-if="loadError" class="message error" role="alert">{{ loadError }}</p>

        <template v-else>
          <div class="page-heading">
            <h1 class="page-title">Request Equipment</h1>
            <span class="page-subtitle">{{ event.name }}</span>
          </div>

          <p v-if="!canRequest" class="message" role="status">
            Equipment can only be requested while the event is in planning. Start planning from the event page first.
          </p>

          <form v-else class="card" novalidate @submit.prevent="submit">
            <h2 class="card-title">Equipment needed</h2>
            <p class="hint">
              The equipment is needed for this session's date and time
              ({{ event.preferred_start_date }}<template v-if="event.preferred_start_time">, {{ event.preferred_start_time }}<template v-if="event.preferred_end_time"> to {{ event.preferred_end_time }}</template></template>).
              Technical Support will see the request as Pending.
            </p>

            <p v-if="submitted && check.formError" class="field-error" role="alert">{{ check.formError }}</p>

            <fieldset v-for="(line, index) in lines" :key="line.key" class="line">
              <legend class="line-legend">Item {{ index + 1 }}</legend>

              <div class="line-grid">
                <label class="field" :class="{ invalid: submitted && check.lineErrors[index].type }">
                  <span class="field-label">Equipment type</span>
                  <select v-model="line.equipment_type_id" class="input" :aria-label="`Equipment type for item ${index + 1}`">
                    <option value="" disabled>Select a type</option>
                    <option
                      v-for="type in types"
                      :key="type.id"
                      :value="type.id"
                      :disabled="optionDisabled(type.id, index)"
                    >
                      {{ equipmentTypeLabel(type.name) }}
                    </option>
                  </select>
                  <span v-if="submitted && check.lineErrors[index].type" class="field-error">
                    {{ check.lineErrors[index].type }}
                  </span>
                </label>

                <label class="field" :class="{ invalid: submitted && check.lineErrors[index].quantity }">
                  <span class="field-label">Quantity</span>
                  <input
                    v-model="line.quantity"
                    class="input small"
                    type="number"
                    min="1"
                    step="1"
                    inputmode="numeric"
                    :aria-label="`Quantity for item ${index + 1}`"
                  />
                  <span v-if="submitted && check.lineErrors[index].quantity" class="field-error">
                    {{ check.lineErrors[index].quantity }}
                  </span>
                </label>
              </div>

              <label class="field">
                <span class="field-label">Technical requirements (optional)</span>
                <textarea
                  v-model="line.technical_requirements"
                  class="input"
                  maxlength="2000"
                  placeholder="Specifications or setup notes, e.g. HDMI input, wireless handheld"
                  :aria-label="`Technical requirements for item ${index + 1}`"
                ></textarea>
              </label>

              <button v-if="lines.length > 1" type="button" class="link-btn" @click="removeLine(index)">
                Remove item {{ index + 1 }}
              </button>
            </fieldset>

            <button type="button" class="link-btn add" @click="addLine">+ Add another item</button>

            <p v-if="error" class="message error" role="alert">{{ error }}</p>

            <div class="form-footer">
              <button type="submit" class="btn btn-primary" :disabled="submitting">
                {{ submitting ? 'Submitting...' : 'Submit Request' }}
              </button>
            </div>
          </form>
        </template>
      </div>
    </main>
  </div>
</template>

<style scoped src="../../styles/event-form.css"></style>
<style scoped>
.hint { margin: 0 0 12px; font-size: 13px; color: #6b6b6b; }
.line { display: flex; flex-direction: column; gap: 12px; border: 1px solid #e3e3e3; border-radius: 6px; padding: 14px 16px; margin: 0 0 14px; }
.line-legend { font-size: 12px; font-weight: 700; color: #6b6b6b; padding: 0 6px; text-transform: uppercase; letter-spacing: 0.04em; }
.line-grid { display: grid; grid-template-columns: minmax(180px, 2fr) minmax(120px, 1fr); gap: 16px; align-items: start; }
.link-btn { align-self: flex-start; border: none; background: none; color: #1f5fae; font-size: 13px; font-weight: 600; cursor: pointer; padding: 0; }
.link-btn.add { margin-bottom: 8px; }
@media (max-width: 520px) { .line-grid { grid-template-columns: 1fr; } }
</style>
