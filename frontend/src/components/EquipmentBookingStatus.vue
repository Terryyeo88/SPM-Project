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
 * Quantity changes (IS-43): under a confirmed request, the coordinator can
 * ask Technical Support to change a line's quantity (EquipmentChangeRequests).
 *
 * Data: GET /events/<id>/equipment-requests
 * (app.equipment.equipment_service.list_requests_for_event).
 */
import { computed, onMounted, ref, watch } from 'vue'
import { apiGet } from '../lib/api'
import EquipmentChangeRequests from './EquipmentChangeRequests.vue'
import {
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
const confirmedRequests = computed(() => requests.value.filter((request) => request.status === 'confirmed'))

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
                <span class="status" :class="`status-${eventRequestStatus(request, event.status).key}`">
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
        v-for="request in confirmedRequests"
        :key="`changes-${request.id}`"
        :request="request"
        :can-change="canChange"
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
.equipment-booking { display: flex; flex-direction: column; gap: 10px; padding-top: 16px; border-top: 1px solid #dcdcdc; }
h2 { margin: 0; font-size: 15px; color: #222; }
h3 { margin: 0; font-size: 14px; color: #222; }
.muted { color: #6b6b6b; }
.small { font-size: 13px; margin: 0; }
.error { color: #a33f3f; margin: 0; }

.table-wrap { overflow-x: auto; background: #fff; border: 1px solid #dcdcdc; border-radius: 6px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; font-size: 11px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: #6b6b6b; padding: 10px 14px; border-bottom: 1px solid #e6e6e6; }
td { padding: 10px 14px; border-bottom: 1px solid #f0f0f0; color: #2a2a2a; vertical-align: middle; }
tbody tr:last-child td { border-bottom: none; }
.num { text-align: right; }

.status { font-size: 12px; font-weight: 600; border-radius: 10px; padding: 4px 12px; background: #eee; color: #5a5a5a; white-space: nowrap; }
.rejection { margin: 6px 0 0; font-size: 12px; color: #a33f3f; white-space: pre-wrap; }
.status-pending { background: #f7efe1; color: #8a5a12; }
.status-confirmed { background: #eaf5ec; color: #2f6b3f; }
.status-rejected { background: #f5e6e6; color: #a33f3f; }
.status-released { background: #eeeeee; color: #5a5a5a; }

.btn.small.primary {
  align-self: flex-start; min-height: 38px; padding: 0 16px; border: none; border-radius: 4px;
  background: #2568e8; color: #fff; font: inherit; font-size: 13px; font-weight: 700;
  text-decoration: none; display: inline-flex; align-items: center;
}

.allocated { display: flex; flex-direction: column; gap: 8px; background: #fff; border: 1px solid #dcdcdc; border-radius: 6px; padding: 14px 16px; }
.groups { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.group { display: flex; flex-direction: column; gap: 6px; padding: 10px 0; border-bottom: 1px solid #f0f0f0; }
.group:last-child { border-bottom: none; padding-bottom: 0; }
.group-head { display: flex; align-items: baseline; gap: 8px; font-size: 13px; }
.group-type { font-weight: 700; color: #222; }
.group-qty { color: #6b6b6b; }
.units { list-style: none; margin: 0; padding: 0; display: flex; flex-wrap: wrap; gap: 6px; }
.unit { font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; background: #f3f3f3; border-radius: 4px; padding: 3px 8px; color: #333; }
</style>
