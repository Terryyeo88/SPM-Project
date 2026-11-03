<script setup>
/**
 * Equipment Booking section on the event details page (View Reserved
 * Equipment, Justin, Sprint 3). A sibling of VenueBookingStatus, shown
 * below it in the assigned coordinator's view of EventDetailsView.vue.
 *
 * Lists every equipment request for this event session (newest first)
 * with what was asked for, the total quantity, when it is needed and its
 * status. Once a request is confirmed, the units reserved for it are
 * listed below the table, grouped by equipment type, with each unit's
 * asset tag -- "so that I know exactly what's allocated to the event".
 * A cancelled event's confirmed requests read "Released" and list no
 * units (lib/equipment.js eventRequestStatus / allocatedEquipment).
 *
 * Managing a request (EquipmentChangeRequests): under each pending or
 * confirmed request the coordinator can cancel it -- freeing its equipment so
 * they can ask again for a different date and time -- and, once confirmed,
 * ask Technical Support to change a line's quantity (IS-43).
 *
 * Data: GET /events/<id>/equipment-requests
 * (app.equipment.equipment_service.list_requests_for_event).
 */
import { computed, onMounted, ref, watch } from 'vue'
import { apiGet } from '../lib/api'
import EquipmentChangeRequests from './EquipmentChangeRequests.vue'
import {
  CANCELLABLE_REQUEST_STATUSES,
  CHANGEABLE_EVENT_STATUSES,
  allocatedEquipment,
  equipmentTypeLabel,
  eventRequestStatus,
  formatPeriod,
  summariseItems,
} from '../lib/equipment'

const props = defineProps({
  event: { type: Object, required: true },
})

const requests = ref([])
const loading = ref(true)
const error = ref('')

const allocated = computed(() => allocatedEquipment(requests.value, props.event.status))
// Same status precondition as rule_equipment_request_create: a request
// can only be raised once the event is in planning -- an approved event is
// moved there first with Start Planning (Record Equipment Request, IS-17).
// Same preconditions as rule_equipment_change_create (IS-43): a confirmed
// request, while the event is still live.
const canChange = computed(() => CHANGEABLE_EVENT_STATUSES.includes(props.event.status))
// Requests that can still be managed: asked-for changes (confirmed only) and
// cancelling (pending or confirmed).
const manageableRequests = computed(() =>
  requests.value.filter((request) => CANCELLABLE_REQUEST_STATUSES.includes(request.status)),
)

const canRequest = computed(() => props.event.status === 'planning')

const isReleased = computed(
  () => props.event.status === 'cancelled' && requests.value.some((request) => request.status === 'confirmed'),
)

async function load() {
  loading.value = true
  error.value = ''
  try {
    requests.value = await apiGet(`/events/${props.event.id}/equipment-requests`)
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    loading.value = false
  }
}

onMounted(load)
watch(() => [props.event.id, props.event.status], load)
</script>

<template>
  <section class="equipment-booking" aria-labelledby="equipment-booking-heading">
    <h2 id="equipment-booking-heading">Equipment Booking</h2>

    <p v-if="loading" class="muted small">Loading equipment requests...</p>
    <p v-else-if="error" class="error" role="alert">Couldn't load equipment requests: {{ error }}</p>

    <template v-else>
      <p v-if="requests.length === 0" class="muted small">No equipment has been requested for this session yet.</p>

      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th scope="col">Requested</th>
              <th scope="col" class="num">Total qty</th>
              <th scope="col">Needed</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="request in requests" :key="request.id">
              <td>{{ summariseItems(request.items) }}</td>
              <td class="num">{{ request.total_quantity }}</td>
              <td>{{ formatPeriod(request.needed_start, request.needed_end) }}</td>
              <td>
                <span class="status cs-pill" :class="[`status-${eventRequestStatus(request, event.status).key}`, `cs-status-${eventRequestStatus(request, event.status).key}`]">
                  {{ eventRequestStatus(request, event.status).label }}
                </span>
                <p v-if="request.status === 'rejected'" class="rejection">
                  Reason: {{ request.rejection_reason ?? 'No reason was recorded.' }}
                </p>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <div v-if="allocated.length" class="allocated">
        <h3>Allocated Equipment</h3>
        <ul class="groups">
          <li v-for="group in allocated" :key="group.type" class="group">
            <div class="group-head">
              <span class="group-type">{{ equipmentTypeLabel(group.type) }}</span>
              <span class="group-qty">× {{ group.quantity }}</span>
            </div>
            <ul class="units">
              <li v-for="unit in group.units" :key="unit.id" class="unit">{{ unit.asset_tag }}</li>
            </ul>
          </li>
        </ul>
      </div>
      <p v-else-if="isReleased" class="muted small">
        This event was cancelled, so its reserved equipment has been released.
      </p>

      <EquipmentChangeRequests
        v-for="request in manageableRequests"
        :key="`changes-${request.id}`"
        :request="request"
        :can-change="canChange"
        @cancelled="load"
      />

      <p v-if="event.status === 'approved'" class="muted small">
        Start planning (under Your Decision) to request equipment.
      </p>
      <router-link
        v-if="canRequest"
        :to="{ name: 'request-equipment', params: { eventId: event.id } }"
        class="btn small primary"
      >
        {{ requests.length ? 'Request more equipment' : 'Request Equipment' }}
      </router-link>
    </template>
  </section>
</template>

<style scoped>
.equipment-booking { display: flex; flex-direction: column; gap: var(--cs-space-2); padding-top: var(--cs-space-4); border-top: 1px solid var(--cs-line); }
h2 { margin: 0; font-size: var(--cs-text-sm); font-family: var(--cs-font-display); color: var(--cs-ink); }
h3 { margin: 0; font-size: var(--cs-text-base); font-family: var(--cs-font-display); color: var(--cs-ink); }
.muted { color: var(--cs-ink-soft); }
.small { font-size: var(--cs-text-sm); margin: 0; }
.error { color: var(--cs-occupied); margin: 0; }

.table-wrap { overflow-x: auto; background: var(--cs-surface); border: 1px solid var(--cs-line); border-radius: var(--cs-radius-md); }
table { width: 100%; border-collapse: collapse; font-size: var(--cs-text-sm); }
th { text-align: left; font-size: var(--cs-text-xs); font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--cs-ink-soft); padding: var(--cs-space-3) var(--cs-space-4); border-bottom: 1px solid var(--cs-line); }
td { padding: var(--cs-space-3) var(--cs-space-4); border-bottom: 1px solid var(--cs-line); color: var(--cs-ink); vertical-align: middle; }
tbody tr:last-child td { border-bottom: none; }
.num { text-align: right; }

.rejection { margin: 6px 0 0; font-size: var(--cs-text-xs); color: var(--cs-occupied); white-space: pre-wrap; }

.btn.small.primary {
  align-self: flex-start; min-height: 38px; padding: 0 var(--cs-space-4); border: none; border-radius: var(--cs-radius-sm);
  background: var(--cs-signal); color: #fff; font: inherit; font-size: var(--cs-text-sm); font-weight: 700;
  text-decoration: none; display: inline-flex; align-items: center;
}
.btn.small.primary:hover { background: var(--cs-signal-strong); }

.allocated { display: flex; flex-direction: column; gap: var(--cs-space-2); background: var(--cs-surface); border: 1px solid var(--cs-line); border-radius: var(--cs-radius-md); padding: var(--cs-space-4); }
.groups { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.group { display: flex; flex-direction: column; gap: 6px; padding: var(--cs-space-3) 0; border-bottom: 1px solid var(--cs-line); }
.group:last-child { border-bottom: none; padding-bottom: 0; }
.group-head { display: flex; align-items: baseline; gap: var(--cs-space-2); font-size: var(--cs-text-sm); }
.group-type { font-weight: 700; color: var(--cs-ink); }
.group-qty { color: var(--cs-ink-soft); }
.units { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 6px; }
.unit { font-size: var(--cs-text-xs); font-family: var(--cs-font-mono); background: var(--cs-neutral-tint); border-radius: var(--cs-radius-sm); padding: 3px 8px; color: var(--cs-ink); }
</style>
