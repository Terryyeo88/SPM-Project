import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'

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

  it('tells the organiser why the layout is empty when Venue Staff removed it', async () => {
    const session = reactive({ ...emptySession(), room_layout: '', room_layout_removed: 'banquet' })
    const wrapper = await mountWith(session)

    expect(wrapper.find('select').element.value).toBe('')
    expect(wrapper.find('[data-test="removed-layout"]').text()).toBe(
      'The room layout "banquet" is no longer available, so it has been removed from this session. Please choose a new room layout.',
    )

    await wrapper.find('select').setValue('u-shape')

    expect(wrapper.find('[data-test="removed-layout"]').exists()).toBe(false)
  })

  it('shows no removed-layout notice for a session that never lost its layout', async () => {
    const wrapper = await mountWith(emptySession())

    expect(wrapper.find('[data-test="removed-layout"]').exists()).toBe(false)
  })

  it('says so when the layouts could not be loaded', async () => {
    apiGet.mockRejectedValue(new Error('Network down'))

    const wrapper = await mountWith(emptySession())

    expect(wrapper.text()).toContain("Couldn't load room layouts: Network down")
  })
})
