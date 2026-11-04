import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../lib/api', () => ({ apiGet: vi.fn(), apiPost: vi.fn() }))

import { apiGet, apiPost } from '../lib/api'
import ClarificationThread from './ClarificationThread.vue'

const QUESTION = {
  clarification_id: 'c1',
  author_role: 'coordinator',
  author_name: 'Alice Tan',
  message: 'Is the date flexible?',
  created_at: '2026-11-04T07:00:00Z',
}
const ANSWER = {
  clarification_id: 'c2',
  author_role: 'organizer',
  author_name: 'Derek Ong',
  message: 'Yes, any weekday works.',
  created_at: '2026-11-04T07:10:00Z',
}

async function render({ status = 'under_review', role = 'organiser', thread = [QUESTION] } = {}) {
  apiGet.mockResolvedValue(thread)
  const wrapper = mount(ClarificationThread, { props: { event: { id: 'session-1', status }, role } })
  await flushPromises()
  return wrapper
}

const sendButton = (wrapper) => wrapper.find('button.send')

beforeEach(() => {
  apiGet.mockReset()
  apiPost.mockReset()
})

describe('ClarificationThread -- showing the thread', () => {
  it('shows every message oldest first, with who sent it', async () => {
    const wrapper = await render({ thread: [QUESTION, ANSWER] })
    expect(apiGet).toHaveBeenCalledWith('/events/session-1/clarifications')
    const items = wrapper.findAll('li.message')
    expect(items).toHaveLength(2)
    expect(items[0].text()).toContain('Alice Tan (Event Coordinator)')
    expect(items[0].text()).toContain('Is the date flexible?')
    // The organiser's own reply is on their side, labelled "You".
    expect(items[1].classes()).toContain('own')
    expect(items[1].text()).toContain('You')
    expect(items[0].classes()).toContain('other')
  })

  it("puts the coordinator's messages on the coordinator's own side when they view it", async () => {
    const wrapper = await render({ role: 'coordinator', thread: [QUESTION, ANSWER] })
    const items = wrapper.findAll('li.message')
    expect(items[0].classes()).toContain('own')
    expect(items[1].classes()).toContain('other')
    expect(items[1].text()).toContain('Derek Ong (Event Organiser)')
  })

  it('shows one day divider per day', async () => {
    const wrapper = await render({ thread: [QUESTION, ANSWER] })
    expect(wrapper.findAll('li.day')).toHaveLength(1)
  })

  it('Enter sends the reply, Shift+Enter does not', async () => {
    const wrapper = await render()
    apiPost.mockResolvedValue(ANSWER)
    const box = wrapper.find('textarea')
    await box.setValue('Yes.')
    await box.trigger('keydown', { key: 'Enter', shiftKey: true })
    expect(apiPost).not.toHaveBeenCalled()
    await box.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(apiPost).toHaveBeenCalledWith('/events/session-1/clarifications/reply', { message: 'Yes.' })
  })

  it("is hidden from the organiser until the coordinator has asked something", async () => {
    const wrapper = await render({ thread: [] })
    expect(wrapper.find('section').exists()).toBe(false)
  })

  it('lets the coordinator write the first question in the box', async () => {
    const wrapper = await render({ role: 'coordinator', thread: [] })
    expect(wrapper.text()).toContain('Write your question for the organiser below')
    apiPost.mockResolvedValue(QUESTION)
    await wrapper.find('textarea').setValue('  Is the date flexible?  ')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/events/session-1/clarifications/request', { message: 'Is the date flexible?' })
    expect(wrapper.findAll('li.message')).toHaveLength(1)
    expect(wrapper.text()).toContain('the request stays Under Review')
  })

  it('lets the coordinator send follow-ups the same way', async () => {
    const wrapper = await render({ role: 'coordinator', thread: [QUESTION, ANSWER] })
    apiPost.mockResolvedValue({ ...QUESTION, clarification_id: 'c3', message: 'Which weekdays?' })
    await wrapper.find('textarea').setValue('Which weekdays?')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(apiPost).toHaveBeenCalledWith('/events/session-1/clarifications/request', { message: 'Which weekdays?' })
    expect(wrapper.findAll('li.message')).toHaveLength(3)
  })

  it('offers the coordinator no box once the request has left under review', async () => {
    const wrapper = await render({ role: 'coordinator', status: 'approved' })
    expect(wrapper.find('textarea').exists()).toBe(false)
    expect(wrapper.text()).toContain('no longer under review')
  })

  it('focusComposer puts the cursor in the message box', async () => {
    apiGet.mockResolvedValue([])
    const wrapper = mount(ClarificationThread, {
      props: { event: { id: 'session-1', status: 'under_review' }, role: 'coordinator' },
      attachTo: document.body,
    })
    await flushPromises()
    Element.prototype.scrollIntoView ??= () => {}
    await wrapper.vm.focusComposer()
    expect(document.activeElement).toBe(wrapper.find('textarea').element)
    wrapper.unmount()
  })

  it('reloads when the parent bumps refreshKey', async () => {
    const wrapper = await render({ role: 'coordinator', thread: [] })
    apiGet.mockResolvedValue([QUESTION])
    await wrapper.setProps({ refreshKey: 1 })
    await flushPromises()
    expect(wrapper.findAll('li.message')).toHaveLength(1)
  })

  it('says so when the thread fails to load', async () => {
    apiGet.mockRejectedValue(new Error('network down'))
    const wrapper = mount(ClarificationThread, { props: { event: { id: 'session-1', status: 'under_review' }, role: 'organiser' } })
    await flushPromises()
    expect(wrapper.text()).toContain("Couldn't load the conversation: network down")
  })
})

describe('ClarificationThread -- the organiser replies', () => {
  it('sends the trimmed reply and adds it to the thread', async () => {
    const wrapper = await render()
    apiPost.mockResolvedValue(ANSWER)
    await wrapper.find('textarea').setValue('  Yes, any weekday works.  ')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/events/session-1/clarifications/reply', { message: 'Yes, any weekday works.' })
    expect(wrapper.findAll('li.message')).toHaveLength(2)
    expect(wrapper.find('textarea').element.value).toBe('')
    expect(wrapper.text()).toContain('Reply sent')
  })

  it("can't send a blank reply", async () => {
    const wrapper = await render()
    await wrapper.find('textarea').setValue('   ')
    expect(sendButton(wrapper).attributes('disabled')).toBeDefined()
  })

  it('shows the error the API gives back', async () => {
    const wrapper = await render()
    apiPost.mockRejectedValue(new Error('Not authorised'))
    await wrapper.find('textarea').setValue('Yes.')
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    expect(wrapper.text()).toContain('Not authorised')
  })

  it('offers no reply box once the request has left under review, but keeps the thread readable', async () => {
    const wrapper = await render({ status: 'approved' })
    expect(wrapper.find('textarea').exists()).toBe(false)
    expect(wrapper.findAll('li.message')).toHaveLength(1)
    expect(wrapper.text()).toContain('no longer under review')
  })
})
