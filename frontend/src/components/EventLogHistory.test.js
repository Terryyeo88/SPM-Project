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
