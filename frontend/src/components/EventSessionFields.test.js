import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../lib/api', () => ({ apiGet: vi.fn() }))

import { apiGet } from '../lib/api'
import { emptySession } from '../lib/eventSessions'
import EventSessionFields from './EventSessionFields.vue'

async function mountWith(session) {
  const wrapper = mount(EventSessionFields, { props: { session, index: 0, minimumDate: '2099-01-01' } })
  await flushPromises()
  return wrapper
}

function layoutOptions(wrapper) {
  return wrapper
    .findAll('select option')
    .filter((option) => option.attributes('value'))
    .map((option) => option.text())
}

describe('EventSessionFields -- room layout', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiGet.mockResolvedValue([{ name: 'theatre' }, { name: 'u-shape' }])
  })

  it('offers the layouts Venue Staff manage, fetched from the backend', async () => {
    const wrapper = await mountWith(emptySession())

    expect(apiGet).toHaveBeenCalledWith('/room-layouts')
    expect(layoutOptions(wrapper)).toEqual(['theatre', 'u-shape'])
  })

  it("keeps a session's soft-deleted layout selected instead of blanking it", async () => {
    const session = { ...emptySession(), room_layout: 'banquet' }
    const wrapper = await mountWith(session)

    expect(layoutOptions(wrapper)).toEqual(['theatre', 'u-shape', 'banquet (no longer offered)'])
    expect(wrapper.find('select').element.value).toBe('banquet')
  })

  it('stores the chosen layout name on the session', async () => {
    const session = emptySession()
    const wrapper = await mountWith(session)

    await wrapper.find('select').setValue('u-shape')

    expect(session.room_layout).toBe('u-shape')
  })

  it('says so when the layouts could not be loaded', async () => {
    apiGet.mockRejectedValue(new Error('Network down'))

    const wrapper = await mountWith(emptySession())

    expect(wrapper.text()).toContain("Couldn't load room layouts: Network down")
  })
})
