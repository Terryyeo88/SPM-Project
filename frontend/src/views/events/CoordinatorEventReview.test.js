import { flushPromises, mount, RouterLinkStub } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('../../lib/api', () => ({ apiGet: vi.fn(), apiPost: vi.fn() }))
vi.mock('../../stores/auth', () => ({ useAuthStore: () => ({ profile: { id: 'coord-1' } }) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))
// The session edit form pulls in room layouts over the API; not under test here.
vi.mock('../../components/EventSessionFields.vue', () => ({ default: { template: '<div />' } }))

import { apiPost } from '../../lib/api'
import CoordinatorEventReview from './CoordinatorEventReview.vue'

function event(status) {
  return {
    id: 'session-1',
    name: 'Annual Tech Symposium',
    status,
    coordinator_id: 'coord-1',
    preferred_start_date: '2099-11-10',
    preferred_end_date: '2099-11-10',
  }
}

function mountWith(status) {
  return mount(CoordinatorEventReview, {
    props: { event: event(status), sessions: [] },
    global: { stubs: { RouterLink: RouterLinkStub } },
  })
}

function cancelButton(wrapper) {
  return wrapper.findAll('button').find((b) => b.text() === 'Cancel Event')
}

// Braces: a function returned from beforeEach is run as teardown.
beforeEach(() => {
  apiPost.mockReset()
})

describe('CoordinatorEventReview -- summary under the title', () => {
  it('shows the description and purpose right under the event name', () => {
    const wrapper = mount(CoordinatorEventReview, {
      props: { event: { ...event('under_review'), description: 'A day of talks.', purpose: 'Knowledge sharing.' }, sessions: [] },
      global: { stubs: { RouterLink: RouterLinkStub } },
    })
    const summary = wrapper.find('.title-row + .event-summary')
    expect(summary.text()).toContain('A day of talks.')
    expect(summary.text()).toContain('Knowledge sharing.')
  })

  it('says when they are missing', () => {
    expect(mountWith('under_review').find('.event-summary').text()).toContain('Not provided')
  })
})

describe('CoordinatorEventReview -- Start Planning', () => {
  function startButton(wrapper) {
    return wrapper.findAll('button').find((b) => b.text() === 'Start Planning')
  }

  it('offers Start Planning only on an approved session', () => {
    expect(startButton(mountWith('approved'))).toBeTruthy()
    for (const status of ['under_review', 'planning', 'confirmed']) {
      expect(startButton(mountWith(status))).toBeUndefined()
    }
  })

  it('moves the session to planning and passes the updated row up', async () => {
    apiPost.mockResolvedValue({ ...event('planning') })
    const wrapper = mountWith('approved')

    await startButton(wrapper).trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/events/session-1/start-planning', {})
    expect(wrapper.emitted('updated')[0][0].status).toBe('planning')
    expect(wrapper.find('[role="status"]').text()).toContain('In Planning')
  })
})

describe('CoordinatorEventReview -- Cancel Event', () => {
  it.each(['approved', 'planning', 'confirmed'])('offers Cancel Event when the session is %s', (status) => {
    expect(cancelButton(mountWith(status))).toBeTruthy()
  })

  it.each(['under_review', 'completed', 'cancelled', 'rejected'])('does not offer it when %s', (status) => {
    expect(cancelButton(mountWith(status))).toBeUndefined()
  })

  it('asks for a reason before cancelling', async () => {
    const wrapper = mountWith('planning')
    await cancelButton(wrapper).trigger('click')
    await wrapper.find('form').trigger('submit')

    expect(apiPost).not.toHaveBeenCalled()
    expect(wrapper.find('[role="alert"]').text()).toContain('reason for cancelling')
  })

  it('cancels with the reason, reports released equipment and passes the update up', async () => {
    const updated = { ...event('cancelled'), released_equipment_units: 3 }
    apiPost.mockResolvedValue(updated)
    const wrapper = mountWith('planning')

    await cancelButton(wrapper).trigger('click')
    await wrapper.find('#cancel-reason').setValue('  No suitable venue  ')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(apiPost).toHaveBeenCalledWith('/events/session-1/cancel', { reason: 'No suitable venue' })
    expect(wrapper.find('[role="status"]').text()).toBe(
      'Session cancelled. 3 reserved equipment units released for other events.',
    )
    expect(wrapper.emitted('updated')[0]).toEqual([updated])
  })

  it('says only that the session was cancelled when no equipment was held', async () => {
    apiPost.mockResolvedValue({ ...event('cancelled'), released_equipment_units: 0 })
    const wrapper = mountWith('approved')

    await cancelButton(wrapper).trigger('click')
    await wrapper.find('#cancel-reason').setValue('Organiser withdrew')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[role="status"]').text()).toBe('Session cancelled.')
  })

  it('shows the error and keeps the panel open if the cancel is refused', async () => {
    apiPost.mockRejectedValue(new Error('This event is no longer Planning'))
    const wrapper = mountWith('planning')

    await cancelButton(wrapper).trigger('click')
    await wrapper.find('#cancel-reason').setValue('No venue')
    await wrapper.find('form').trigger('submit')
    await flushPromises()

    expect(wrapper.find('[role="alert"]').text()).toContain('no longer Planning')
    expect(wrapper.find('#cancel-reason').exists()).toBe(true)
    expect(wrapper.emitted('updated')).toBeUndefined()
  })
})

// -- IS-9 Update Event Information During Planning -------------------------

function plannedEvent(status = 'planning') {
  return {
    ...event(status),
    description: 'A symposium.',
    purpose: 'Learning.',
    preferred_start_time: '09:00:00',
    preferred_end_time: '17:00:00',
    expected_attendance: 100,
    room_layout: 'theatre',
    registration_needs: false,
    equipment_needed: { equipment: [] },
    accessibility_needs: [],
  }
}

function mountForEditing(status = 'planning') {
  return mount(CoordinatorEventReview, {
    props: { event: plannedEvent(status), sessions: [] },
    global: { stubs: { RouterLink: RouterLinkStub } },
  })
}

async function saveEdits(wrapper) {
  await wrapper.findAll('button').find((b) => b.text() === 'Edit Details').trigger('click')
  await wrapper.find('form.edit-form').trigger('submit')
  await flushPromises()
}

function button(wrapper, text) {
  return wrapper.findAll('button').find((b) => b.text() === text)
}

const VENUE_IMPACT = {
  area: 'venue',
  severity: 'conflict',
  title: 'Venue booking: Hall A (confirmed)',
  booking_id: 'booking-1',
  issues: ['150 expected attendees exceeds the venue\'s capacity of 120.'],
}

function previewOf(overrides = {}) {
  return {
    changes: { expected_attendance: { from: 100, to: 150 } },
    significance: 'significant',
    significant_fields: ['expected_attendance'],
    impacts: [],
    reverts_to_planning: false,
    ...overrides,
  }
}

describe('CoordinatorEventReview -- Edit Details (IS-9)', () => {
  it('saves an ordinary change without an extra step', async () => {
    const updated = { ...plannedEvent(), name: 'Renamed' }
    apiPost
      .mockResolvedValueOnce(previewOf({ changes: { name: { from: 'a', to: 'b' } }, significance: 'ordinary', significant_fields: [] }))
      .mockResolvedValueOnce(updated)
    const wrapper = mountForEditing()

    await saveEdits(wrapper)

    expect(apiPost).toHaveBeenNthCalledWith(1, '/events/session-1/update-preview', expect.any(Object))
    expect(apiPost).toHaveBeenNthCalledWith(2, '/events/session-1', expect.objectContaining({ acknowledge_impacts: [] }))
    expect(wrapper.emitted('updated')[0]).toEqual([updated])
    expect(wrapper.find('[role="status"]').text()).toBe('Event details updated.')
  })

  it('shows a significant change for review before saving it', async () => {
    apiPost.mockResolvedValueOnce(previewOf())
    const wrapper = mountForEditing()

    await saveEdits(wrapper)

    expect(apiPost).toHaveBeenCalledTimes(1) // the preview only -- nothing saved yet
    expect(wrapper.text()).toContain('Review before saving')
    expect(wrapper.find('.significance').text()).toBe('Significant change')
    expect(wrapper.text()).toContain('Expected attendance')
    expect(wrapper.text()).toContain('No venue booking, equipment, technical support or registration is affected.')
  })

  it('lists the arrangements the change touches and needs them acknowledged', async () => {
    const updated = { ...plannedEvent(), expected_attendance: 150 }
    apiPost.mockResolvedValueOnce(previewOf({ impacts: [VENUE_IMPACT] })).mockResolvedValueOnce(updated)
    const wrapper = mountForEditing()

    await saveEdits(wrapper)

    expect(wrapper.text()).toContain('Venue booking: Hall A (confirmed)')
    expect(wrapper.text()).toContain('exceeds the venue\'s capacity of 120')
    expect(button(wrapper, 'Confirm and Save').attributes('disabled')).toBeDefined()

    await wrapper.find('.impact input[type="checkbox"]').setValue(true)
    await button(wrapper, 'Confirm and Save').trigger('click')
    await flushPromises()

    expect(apiPost).toHaveBeenLastCalledWith('/events/session-1', expect.objectContaining({
      expected_attendance: 100, // the form's own value, as sent to the preview
      acknowledge_impacts: ['venue'],
    }))
    expect(wrapper.emitted('updated')[0]).toEqual([updated])
  })

  it('warns that a confirmed event goes back to planning, and says so once saved', async () => {
    apiPost
      .mockResolvedValueOnce(previewOf({ significance: 'ordinary', significant_fields: [], reverts_to_planning: true }))
      .mockResolvedValueOnce({ ...plannedEvent('planning') })
    const wrapper = mountForEditing('confirmed')

    await saveEdits(wrapper)
    expect(wrapper.text()).toContain('moves it back to In Planning')

    await button(wrapper, 'Confirm and Save').trigger('click')
    await flushPromises()
    expect(wrapper.find('[role="status"]').text()).toContain('back In Planning')
  })

  it('re-presents the arrangements if a new one turned up before saving', async () => {
    const refused = Object.assign(new Error('This change affects arrangements already made for the event (registration).'), {
      code: 'change_impact_unacknowledged',
    })
    const registration = { area: 'registration', severity: 'conflict', title: 'Attendee registrations', issues: ['1 confirmed attendee(s) registered.'] }
    apiPost
      .mockResolvedValueOnce(previewOf())
      .mockRejectedValueOnce(refused)
      .mockResolvedValueOnce(previewOf({ impacts: [registration] }))
    const wrapper = mountForEditing()

    await saveEdits(wrapper)
    await button(wrapper, 'Confirm and Save').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Attendee registrations')
    expect(wrapper.find('[role="alert"]').text()).toContain('registration')
    expect(wrapper.emitted('updated')).toBeUndefined()
  })

  it('goes back to the form without saving', async () => {
    apiPost.mockResolvedValueOnce(previewOf())
    const wrapper = mountForEditing()

    await saveEdits(wrapper)
    await button(wrapper, 'Back to Editing').trigger('click')

    expect(wrapper.find('form.edit-form').exists()).toBe(true)
    expect(apiPost).toHaveBeenCalledTimes(1)
  })

  it('shows the refusal reason when the update is not allowed', async () => {
    apiPost.mockRejectedValueOnce(new Error('This event is completed, so its details can no longer be updated.'))
    const wrapper = mountForEditing()

    await saveEdits(wrapper)

    expect(wrapper.find('[role="alert"]').text()).toBe('This event is completed, so its details can no longer be updated.')
    expect(wrapper.emitted('updated')).toBeUndefined()
  })

  it.each(['completed', 'cancelled'])('offers no Edit Details once the event is %s', (status) => {
    const wrapper = mountForEditing(status)
    expect(button(wrapper, 'Edit Details')).toBeUndefined()
  })
})

describe('CoordinatorEventReview -- no Reassign (Week 9: only the Lead reassigns)', () => {
  it.each(['under_review', 'approved', 'planning', 'confirmed'])('offers no Reassign Coordinator when %s', (status) => {
    const wrapper = mountWith(status)
    expect(wrapper.findAll('button').some((b) => /reassign/i.test(b.text()))).toBe(false)
    expect(wrapper.find('#reassign-to').exists()).toBe(false)
  })
})
