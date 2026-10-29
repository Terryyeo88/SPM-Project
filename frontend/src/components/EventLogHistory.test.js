import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../lib/api', () => ({ apiGet: vi.fn() }))

import { apiGet } from '../lib/api'
import EventLogHistory from './EventLogHistory.vue'

const event = { id: 'session-1' }

beforeEach(() => apiGet.mockReset())

describe('EventLogHistory', () => {
  it('shows what changed, who changed it and when', async () => {
    apiGet.mockResolvedValue([
      {
        event_log_id: 'log-1',
        shared_event_id: 'group-1',
        changed_by: 'coord-1',
        changed_at: '2026-10-08T01:00:00Z',
        changes: { expected_attendance: { from: 100, to: 150 } },
        profiles: { name: 'Alice Tan' },
        kind: 'changed',
      },
    ])
    const wrapper = mount(EventLogHistory, { props: { event } })
    await flushPromises()

    expect(apiGet).toHaveBeenCalledWith('/events/session-1/logs')
    expect(wrapper.find('.entry-title').text()).toBe('Changed by Alice Tan')
    expect(wrapper.text()).toContain('Expected attendance: 100 → 150')
    expect(wrapper.find('.entry-header .muted').text()).not.toBe('')
  })

  it('labels each entry significant or ordinary, with what was acknowledged (IS-9)', async () => {
    apiGet.mockResolvedValue([
      {
        event_log_id: 'log-2',
        changed_at: '2026-10-09T01:00:00Z',
        changes: { expected_attendance: { from: 100, to: 150 } },
        profiles: { name: 'Alice Tan' },
        kind: 'changed',
        significance: 'significant',
        acknowledged_impacts: [{ area: 'venue', title: 'Venue booking: Hall A (confirmed)' }],
      },
      {
        event_log_id: 'log-1',
        changed_at: '2026-10-08T01:00:00Z',
        changes: { name: { from: 'Old', to: 'New' } },
        profiles: { name: 'Alice Tan' },
        kind: 'changed',
        significance: 'ordinary',
      },
    ])
    const wrapper = mount(EventLogHistory, { props: { event } })
    await flushPromises()

    expect(wrapper.findAll('.significance').map((badge) => badge.text())).toEqual([
      'Significant change',
      'Ordinary change',
    ])
    expect(wrapper.text()).toContain('Saved knowing it affects: Venue booking: Hall A (confirmed).')
  })

  it("labels the organiser's entries as requests, not changes", async () => {
    apiGet.mockResolvedValue([
      {
        event_log_id: 'log-2',
        changed_by: 'org-1',
        changed_at: '2026-10-08T12:34:00Z',
        changes: { preferred_start_date: { from: '2026-10-04', to: '2026-10-12' } },
        profiles: { name: 'Vincent' },
        kind: 'requested',
      },
    ])
    const wrapper = mount(EventLogHistory, { props: { event } })
    await flushPromises()

    expect(wrapper.find('.entry-title').text()).toBe('Change requested by Vincent')
    expect(wrapper.text()).toContain('Start date: 2026-10-04 → 2026-10-12')
  })

  it('copes with a change whose author is unknown', async () => {
    apiGet.mockResolvedValue([
      { event_log_id: 'log-1', changes: { room_layout: { from: 'theatre', to: 'banquet' } }, profiles: null },
    ])
    const wrapper = mount(EventLogHistory, { props: { event } })
    await flushPromises()
    expect(wrapper.find('.entry-title').text()).toBe('Changed by unknown user')
  })

  it('says so when nothing has changed', async () => {
    apiGet.mockResolvedValue([])
    const wrapper = mount(EventLogHistory, { props: { event } })
    await flushPromises()
    expect(wrapper.text()).toContain('No changes have been requested or made')
  })

  it('reloads when the page writes a change', async () => {
    apiGet.mockResolvedValue([])
    const wrapper = mount(EventLogHistory, { props: { event, refreshKey: 0 } })
    await flushPromises()
    await wrapper.setProps({ refreshKey: 1 })
    await flushPromises()
    expect(apiGet).toHaveBeenCalledTimes(2)
  })
})

function logEntries(count, overrides = () => ({})) {
  return Array.from({ length: count }, (_, index) => ({
    event_log_id: `log-${index + 1}`,
    changed_at: '2026-10-09T01:00:00Z',
    changes: { expected_attendance: { from: 100, to: 100 + index + 1 } },
    profiles: { name: 'Alice Tan' },
    kind: 'changed',
    ...overrides(index),
  }))
}

async function mountWith(entries) {
  apiGet.mockResolvedValue(entries)
  const wrapper = mount(EventLogHistory, { props: { event } })
  await flushPromises()
  return wrapper
}

function pagerButton(wrapper, text) {
  return wrapper.findAll('.pager button').find((b) => b.text().includes(text))
}

describe('EventLogHistory -- which session each change is about', () => {
  it('names the session each entry was made on', async () => {
    const wrapper = await mountWith(logEntries(2, (index) => ({
      session: { id: `session-${index + 1}`, number: index + 1, label: `Session ${index + 1}` },
    })))
    expect(wrapper.findAll('.session').map((badge) => badge.text())).toEqual(['Session 1', 'Session 2'])
  })

  it('marks a shared-detail change as applying to all sessions', async () => {
    const wrapper = await mountWith(logEntries(1, () => ({
      changes: { name: { from: 'Old', to: 'New' } },
      session: { id: null, number: null, label: 'All sessions' },
    })))
    const badge = wrapper.find('.session')
    expect(badge.text()).toBe('All sessions')
    expect(badge.classes()).toContain('session-all')
  })

  it('says when an older entry on a multi-session request has no session recorded', async () => {
    const wrapper = await mountWith(logEntries(1, () => ({
      session: { id: null, number: null, label: 'Session not recorded' },
    })))
    expect(wrapper.find('.session').text()).toBe('Session not recorded')
  })

  it('shows no session badge for a single-session request', async () => {
    const wrapper = await mountWith(logEntries(1, () => ({ session: null })))
    expect(wrapper.find('.session').exists()).toBe(false)
    expect(wrapper.find('.entry-title').text()).toBe('Changed by Alice Tan')
  })
})

describe('EventLogHistory -- pagination', () => {
  it('shows no pager when everything fits on one page', async () => {
    const wrapper = await mountWith(logEntries(5))
    expect(wrapper.findAll('li.entry')).toHaveLength(5)
    expect(wrapper.find('.pager').exists()).toBe(false)
  })

  it('shows the newest five first, with the page position', async () => {
    const wrapper = await mountWith(logEntries(12))
    expect(wrapper.findAll('li.entry')).toHaveLength(5)
    expect(wrapper.text()).toContain('Expected attendance: 100 → 101')
    expect(wrapper.text()).not.toContain('100 → 106')
    expect(wrapper.find('.pager').text()).toContain('1–5 of 12 · Page 1 of 3')
    expect(pagerButton(wrapper, 'Newer').attributes('disabled')).toBeDefined()
  })

  it('pages through older entries and back', async () => {
    const wrapper = await mountWith(logEntries(12))

    await pagerButton(wrapper, 'Older').trigger('click')
    expect(wrapper.find('.pager').text()).toContain('6–10 of 12 · Page 2 of 3')
    expect(wrapper.text()).toContain('100 → 106')

    await pagerButton(wrapper, 'Older').trigger('click')
    expect(wrapper.findAll('li.entry')).toHaveLength(2)
    expect(pagerButton(wrapper, 'Older').attributes('disabled')).toBeDefined()

    await pagerButton(wrapper, 'Newer').trigger('click')
    expect(wrapper.find('.pager').text()).toContain('Page 2 of 3')
  })

  it('goes back to the newest page when the history reloads', async () => {
    const wrapper = await mountWith(logEntries(12))
    await pagerButton(wrapper, 'Older').trigger('click')

    await wrapper.setProps({ refreshKey: 1 })
    await flushPromises()

    expect(wrapper.find('.pager').text()).toContain('Page 1 of 3')
  })
})
