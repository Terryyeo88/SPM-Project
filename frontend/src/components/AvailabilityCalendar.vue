<script setup>
// The month grid / day-and-week list / legend of an availability
// calendar, extracted from VenueCalendarView.vue (IS-11, Nawaz) so the
// equipment calendar can render the same way. Presentational only: the
// caller fetches the entries and owns the selected view and range (see
// useCalendarRange in lib/calendar.js).
//
// `states` maps each entry state to how it is shown, in legend order:
//   { confirmed: { label: 'Confirmed', color: '#…', background: '#…' }, … }
// `entryLabel(entry)` is the text inside an entry, which is domain
// specific (an event name, a block reason, …).
// `spanDays` marks a multi-day entry on every day it covers in the month
// grid, instead of only its first day (see monthCells in lib/calendar.js).
import { computed } from 'vue'
import { WEEKDAY_HEADERS, monthCells, sortedByStart, timeLabel } from '../lib/calendar'

const props = defineProps({
  view: { type: String, required: true },
  range: { type: Object, required: true },
  entries: { type: Array, required: true },
  states: { type: Object, required: true },
  entryLabel: { type: Function, required: true },
  emptyMessage: { type: String, default: 'Nothing in this range.' },
  spanDays: { type: Boolean, default: false },
})

const cells = computed(() => (props.view === 'month' ? monthCells(props.range, props.entries, { spanDays: props.spanDays }) : []))
const listEntries = computed(() => (props.view === 'month' ? [] : sortedByStart(props.entries)))

function pillStyle(state) {
  const look = props.states[state]
  return look ? { color: look.color, background: look.background } : {}
}
function dotStyle(state) {
  const look = props.states[state]
  return look ? { background: look.color } : {}
}
</script>

<template>
  <div v-if="view === 'month'" class="month-grid">
    <div v-for="d in WEEKDAY_HEADERS" :key="d" class="day-header">{{ d }}</div>
    <div v-for="(cell, i) in cells" :key="i" class="day-cell" :class="{ blank: cell.blank }">
      <template v-if="!cell.blank">
        <span class="day-number">{{ cell.day }}</span>
        <span
          v-for="(entry, j) in cell.entries"
          :key="j"
          class="entry-pill"
          :class="`state-${entry.state}`"
          :style="pillStyle(entry.state)"
        >
          {{ entryLabel(entry) }}
        </span>
      </template>
    </div>
  </div>

  <div v-else class="list">
    <p v-if="listEntries.length === 0" class="message">{{ emptyMessage }}</p>
    <div v-for="(entry, i) in listEntries" :key="i" class="list-row">
      <span class="entry-pill" :class="`state-${entry.state}`" :style="pillStyle(entry.state)">{{
        states[entry.state]?.label
      }}</span>
      <span class="list-main">{{ entryLabel(entry) }}</span>
      <span class="list-time">{{ timeLabel(entry.start) }} – {{ timeLabel(entry.end) }}</span>
    </div>
  </div>

  <div class="legend">
    <span v-for="(look, state) in states" :key="state" class="legend-item"
      ><span class="dot" :class="`state-${state}`" :style="dotStyle(state)"></span>{{ look.label }}</span
    >
  </div>
</template>

<style scoped>
.message { margin: 0; padding: 16px 0; font-size: 14px; color: #8a8a8a; }

.month-grid {
  display: grid; grid-template-columns: repeat(7, 1fr); gap: 1px; background: #e6e6e6; border: 1px solid #e6e6e6;
  border-radius: 4px; overflow: hidden;
}
.day-header { background: #f7f7f7; padding: 6px 8px; font-size: 10px; font-weight: 700; color: #9a9a9a; text-align: center; }
.day-cell { background: #ffffff; min-height: 62px; padding: 6px 8px; box-sizing: border-box; display: flex; flex-direction: column; gap: 3px; }
.day-cell.blank { background: #f9f9f9; }
.day-number { font-size: 11px; color: #555555; }

.entry-pill {
  font-size: 9px; font-weight: 600; border-radius: 6px; padding: 1px 4px; display: inline-block; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis;
}

.list { background: #ffffff; border: 1px dashed #9a9a9a; border-radius: 6px; padding: 4px 18px; box-sizing: border-box; }
.list-row { display: flex; align-items: center; gap: 12px; padding: 12px 0; border-bottom: 1px dashed #e2e2e2; font-size: 13px; }
.list-row:last-child { border-bottom: none; }
.list-main { flex: 1 1 auto; color: #2a2a2a; font-weight: 600; }
.list-time { color: #8a8a8a; }

.legend { display: flex; align-items: center; gap: 16px; font-size: 11px; color: #8a8a8a; }
.legend-item { display: flex; align-items: center; gap: 4px; }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
</style>
