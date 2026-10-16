import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import AvailabilityCalendar from './AvailabilityCalendar.vue'
import { rangeFor } from '../lib/calendar'

const STATES = {
  held: { label: 'Held', color: '#111111', background: '#eeeeee' },
  free: { label: 'Free', color: '#222222', background: '#dddddd' },
}
const ENTRY = { state: 'held', name: 'Gala', start: new Date(2026, 9, 20, 10).toISOString(), end: new Date(2026, 9, 20, 12).toISOString() }

function mountCalendar(props) {
  return mount(AvailabilityCalendar, {
    props: { range: rangeFor(props.view, new Date(2026, 9, 20)), states: STATES, entryLabel: (e) => e.name, ...props },
  })
}

describe('AvailabilityCalendar', () => {
  it('month view puts the entry in its day, labelled and coloured by the caller', () => {
    const wrapper = mountCalendar({ view: 'month', entries: [ENTRY] })

    const pill = wrapper.find('.entry-pill')
    expect(pill.text()).toBe('Gala')
    expect(pill.attributes('style')).toContain('color: rgb(17, 17, 17)')
    expect(pill.element.closest('.day-cell').querySelector('.day-number').textContent).toBe('20')
  })

  it('list view shows the state label and the empty message the caller gives', () => {
    expect(mountCalendar({ view: 'week', entries: [ENTRY] }).find('.entry-pill').text()).toBe('Held')
    expect(mountCalendar({ view: 'day', entries: [], emptyMessage: 'Nothing booked.' }).text()).toContain(
      'Nothing booked.',
    )
  })

  it('legend lists every state in the order given', () => {
    const legend = mountCalendar({ view: 'month', entries: [] }).findAll('.legend-item')
    expect(legend.map((item) => item.text())).toEqual(['Held', 'Free'])
  })
})
