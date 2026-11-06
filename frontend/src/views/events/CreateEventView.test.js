// IS-3 Create an Event Request, AC1/AC2: an incomplete request can't be
// submitted, and the missing information is highlighted. The backend refuses
// it too, naming each missing field (test_event_submission.py::
// test_submission_rejects_each_missing_required_field); this is the page's
// side of the same criterion.
import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../lib/api', () => ({ apiGet: vi.fn(), apiPost: vi.fn() }))
vi.mock('../../stores/auth', () => ({ useAuthStore: () => ({ roles: ['event_organizer'], profile: { id: 'org-1' } }) }))
vi.mock('../../components/AppNavBar.vue', () => ({ default: { template: '<nav />' } }))

import { apiGet, apiPost } from '../../lib/api'
import CreateEventView from './CreateEventView.vue'

async function render() {
  apiGet.mockResolvedValue([])
  const wrapper = mount(CreateEventView)
  await flushPromises()
  return wrapper
}

const submitButton = (wrapper) => wrapper.findAll('button').find((b) => b.text().includes('Submit Request'))

beforeEach(() => {
  apiGet.mockReset()
  apiPost.mockReset()
})

describe('CreateEventView -- an incomplete request is not submitted (IS-3 AC1/AC2)', () => {
  it('keeps Submit Request disabled until the required fields are filled in', async () => {
    const wrapper = await render()
    expect(submitButton(wrapper).attributes('disabled')).toBeDefined()

    await wrapper.find('input[placeholder="e.g. Annual Tech Conference 2026"]').setValue('Annual Tech Symposium')
    expect(submitButton(wrapper).attributes('disabled')).toBeDefined() // description, purpose and the session are still missing
  })

  it('highlights each missing field, and sends nothing, if an incomplete form is submitted', async () => {
    const wrapper = await render()
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(apiPost).not.toHaveBeenCalled()
    const text = wrapper.text()
    expect(text).toContain('Event name is required.')
    expect(text).toContain('Description is required.')
    expect(text).toContain('Purpose is required.')
    expect(text).toContain('Please select a room layout.')
    expect(text).toContain('Expected attendance is required.')
    // The fields themselves are marked, not just listed.
    expect(wrapper.findAll('label.field.invalid').length).toBeGreaterThanOrEqual(3)
  })

  it('clears a highlight as soon as that field is filled in', async () => {
    const wrapper = await render()
    await wrapper.find('form').trigger('submit')
    await flushPromises()
    await wrapper.find('input[placeholder="e.g. Annual Tech Conference 2026"]').setValue('Annual Tech Symposium')
    expect(wrapper.text()).not.toContain('Event name is required.')
    expect(wrapper.text()).toContain('Description is required.')
  })
})
