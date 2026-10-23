import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const apiGet = vi.fn()
const apiPost = vi.fn()
const apiDelete = vi.fn()
vi.mock('../../lib/api', () => ({
  apiGet: (...args) => apiGet(...args),
  apiPost: (...args) => apiPost(...args),
  apiDelete: (...args) => apiDelete(...args),
}))
// AppNavBar pulls in the auth store and the Supabase client -- irrelevant here.
vi.mock('../../components/AppNavBar.vue', () => ({ default: { template: '<div />' } }))

import RoomLayoutsView from './RoomLayoutsView.vue'

const LAYOUTS = [
  { room_layout_id: 't', name: 'theatre', is_active: true },
  { room_layout_id: 'b', name: 'banquet', is_active: false },
]

async function mountView() {
  const wrapper = mount(RoomLayoutsView)
  await flushPromises()
  return wrapper
}

function rowNamed(wrapper, name) {
  return wrapper.findAll('li').find((row) => row.text().includes(name))
}

function button(row, label) {
  return row.findAll('button').find((b) => b.text() === label)
}

describe('RoomLayoutsView', () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPost.mockReset()
    apiDelete.mockReset()
    apiGet.mockResolvedValue(LAYOUTS)
    apiPost.mockResolvedValue({})
    apiDelete.mockResolvedValue(null)
  })
  afterEach(() => vi.restoreAllMocks())

  it('lists active and deleted layouts separately, soft-deleted ones included', async () => {
    const wrapper = await mountView()

    expect(apiGet).toHaveBeenCalledWith('/room-layouts?include_inactive=true')
    const names = (selector) => wrapper.findAll(selector).map((row) => row.find('.layout-name').text())
    expect(names('[data-test="active-layout"]')).toEqual(['theatre'])
    expect(names('[data-test="deleted-layout"]')).toEqual(['banquet'])
  })

  it('adds a layout and reloads the list', async () => {
    const wrapper = await mountView()

    await wrapper.find('form input').setValue('  U-shape ')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/room-layouts', { name: 'U-shape' })
    expect(apiGet).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('Added "U-shape".')
  })

  it('asks for a name rather than sending an empty one', async () => {
    const wrapper = await mountView()

    await wrapper.find('form').trigger('submit')

    expect(apiPost).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Enter a name for the room layout.')
  })

  it('renames a layout inline', async () => {
    const wrapper = await mountView()

    await button(rowNamed(wrapper, 'theatre'), 'Rename').trigger('click')
    const editRow = wrapper.find('[data-test="active-layout"]')
    await editRow.find('input').setValue('theatre style')
    await button(editRow, 'Save').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/room-layouts/t', { name: 'theatre style' })
  })

  it('soft-deletes an active layout and restores a deleted one', async () => {
    const wrapper = await mountView()

    await button(rowNamed(wrapper, 'theatre'), 'Delete').trigger('click')
    await flushPromises()
    expect(apiDelete).toHaveBeenCalledWith('/room-layouts/t')

    await button(rowNamed(wrapper, 'banquet'), 'Restore').trigger('click')
    await flushPromises()
    expect(apiPost).toHaveBeenCalledWith('/room-layouts/b/restore', {})
  })

  it('permanently deletes only after confirming', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const wrapper = await mountView()

    await button(rowNamed(wrapper, 'banquet'), 'Delete permanently').trigger('click')
    expect(confirm).toHaveBeenCalled()
    expect(apiDelete).not.toHaveBeenCalled()

    confirm.mockReturnValue(true)
    await button(rowNamed(wrapper, 'banquet'), 'Delete permanently').trigger('click')
    await flushPromises()
    expect(apiDelete).toHaveBeenCalledWith('/room-layouts/b/permanent')
  })

  it("shows the backend's reason when a permanent delete is refused", async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const refused = new Error('Room layout "banquet" is still used by 2 event(s) that are not completed, cancelled or rejected.')
    apiDelete.mockRejectedValueOnce(refused)
    const wrapper = await mountView()

    await button(rowNamed(wrapper, 'banquet'), 'Delete permanently').trigger('click')
    await flushPromises()

    expect(wrapper.find('[role="alert"]').text()).toContain('still used by 2 event(s)')
    expect(wrapper.findAll('[data-test="deleted-layout"]')).toHaveLength(1)
  })
})
