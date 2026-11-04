<script setup>
/**
 * The clarification thread on the event page (lib/clarifications), laid out
 * as a chat box: a header, a scrolling list of message bubbles (the
 * viewer's own side on the right, the other side on the left), and the
 * reply box along the bottom.
 *
 *   role="coordinator" -- writes in the box while the request is under
 *                         review (POST .../clarifications/request). The
 *                         "Request Clarification" button in
 *                         CoordinatorEventReview's decision row just calls
 *                         focusComposer() to bring the box into view.
 *   role="organiser"   -- reads the coordinator's questions and answers them
 *                         while the request is under review (POST
 *                         .../clarifications/reply). The box is hidden until
 *                         the coordinator has asked something: the organiser
 *                         can't open a thread (to change details they use
 *                         Request a Change).
 *
 * "Own side" goes by the side saved with each message, not by who is
 * signed in now, so after a reassignment the previous coordinator's
 * messages still sit on the coordinator's side. Messages are shown oldest
 * first, grouped by day, with who sent them and when; they can't be edited
 * or deleted.
 */
import { computed, nextTick, ref, watch } from 'vue'
import {
  MAX_MESSAGE_LENGTH,
  authorLabel,
  canOrganiserReply,
  fetchClarifications,
  messageError,
  sendClarificationReply,
  sendClarificationRequest,
} from '../lib/clarifications'

const props = defineProps({
  event: { type: Object, required: true },
  role: { type: String, required: true, validator: (value) => ['organiser', 'coordinator'].includes(value) },
  // Bumped by the parent after it posts a message, to reload the thread.
  refreshKey: { type: Number, default: 0 },
})

const messages = ref([])
const loading = ref(true)
const loadError = ref('')
const reply = ref('')
const busy = ref(false)
const error = ref('')
const success = ref('')
const scroller = ref(null)
const composer = ref(null)

// The side the viewer posts as, in the API's spelling.
const ownSide = computed(() => (props.role === 'coordinator' ? 'coordinator' : 'organizer'))
const otherParty = computed(() => (props.role === 'coordinator' ? 'the Event Organiser' : 'your Event Coordinator'))
const isUnderReview = computed(() => props.event.status === 'under_review')
// The coordinator can always write while under review; the organiser only answers.
const canReply = computed(() =>
  props.role === 'coordinator' ? isUnderReview.value : canOrganiserReply(props.event, messages.value),
)
const replyLength = computed(() => reply.value.trim().length)
const replyProblem = computed(() => messageError(reply.value))
// The organiser only sees the box once there is something to answer.
const hidden = computed(() => props.role === 'organiser' && !loading.value && !loadError.value && !messages.value.length)

function dayLabel(value) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' })
}

function timeLabel(value) {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
}

function initials(message) {
  const name = (message.author_name || '').trim()
  if (!name) return message.author_role === 'coordinator' ? 'EC' : 'EO'
  return name.split(/\s+/).slice(0, 2).map((part) => part[0].toUpperCase()).join('')
}

// Each message, plus whether a day divider goes above it.
const rows = computed(() =>
  messages.value.map((message, index) => {
    const day = dayLabel(message.created_at)
    const previous = messages.value[index - 1]
    return {
      message,
      own: message.author_role === ownSide.value,
      day: !previous || dayLabel(previous.created_at) !== day ? day : '',
    }
  }),
)

async function scrollToLatest() {
  await nextTick()
  if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight
}

async function load() {
  loadError.value = ''
  try {
    const loaded = await fetchClarifications(props.event.id)
    messages.value = Array.isArray(loaded) ? loaded : []
  } catch (requestError) {
    loadError.value = `Couldn't load the conversation: ${requestError.message}`
  } finally {
    loading.value = false
  }
  scrollToLatest()
}

async function sendReply() {
  error.value = ''
  success.value = ''
  if (replyProblem.value) {
    error.value = replyProblem.value
    return
  }
  busy.value = true
  try {
    const send = props.role === 'coordinator' ? sendClarificationRequest : sendClarificationReply
    const created = await send(props.event.id, reply.value.trim())
    messages.value = [...messages.value, created]
    reply.value = ''
    success.value = props.role === 'coordinator'
      ? 'Sent. The organiser has been notified; the request stays Under Review.'
      : 'Reply sent. The coordinator has been notified.'
    scrollToLatest()
  } catch (requestError) {
    error.value = requestError.message
  } finally {
    busy.value = false
  }
}

/** Brings the box into view and puts the cursor in it (Request Clarification). */
async function focusComposer() {
  await nextTick()
  scroller.value?.closest('section')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  composer.value?.focus()
}
defineExpose({ focusComposer })

// Enter sends, Shift+Enter starts a new line -- as in most chat boxes.
function onReplyKeydown(keyEvent) {
  if (keyEvent.key === 'Enter' && !keyEvent.shiftKey && !keyEvent.isComposing) {
    keyEvent.preventDefault()
    if (!busy.value && !replyProblem.value) sendReply()
  }
}

watch(() => [props.event.id, props.refreshKey], () => {
  reply.value = ''
  error.value = ''
  success.value = ''
  load()
}, { immediate: true })
</script>

<template>
  <section v-if="!hidden" class="chat" aria-labelledby="conversation-heading">
    <header class="chat-header">
      <div class="header-icon" aria-hidden="true">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
          stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
        </svg>
      </div>
      <div>
        <h2 id="conversation-heading">Conversation</h2>
        <p class="header-sub">Clarification with {{ otherParty }} · the status stays Under Review</p>
      </div>
    </header>

    <div ref="scroller" class="chat-body">
      <p v-if="loading" class="placeholder">Loading conversation...</p>
      <p v-else-if="loadError" class="placeholder error" role="alert">{{ loadError }}</p>
      <p v-else-if="!messages.length" class="placeholder">
        <template v-if="isUnderReview">No messages yet. Write your question for the organiser below.</template>
        <template v-else>No clarification was requested.</template>
      </p>
      <ol v-else class="messages">
        <template v-for="row in rows" :key="row.message.clarification_id">
          <li v-if="row.day" class="day" aria-hidden="true"><span>{{ row.day }}</span></li>
          <li class="message" :class="[row.own ? 'own' : 'other', `from-${row.message.author_role}`]">
            <span v-if="!row.own" class="avatar" aria-hidden="true">{{ initials(row.message) }}</span>
            <div class="bubble-wrap">
              <span class="meta">
                <span class="author">{{ row.own ? 'You' : authorLabel(row.message) }}</span>
                <time :datetime="row.message.created_at">{{ timeLabel(row.message.created_at) }}</time>
              </span>
              <p class="bubble">{{ row.message.message }}</p>
            </div>
          </li>
        </template>
      </ol>
    </div>

    <footer v-if="!loading && !loadError" class="chat-footer">
      <form v-if="canReply" class="composer" novalidate @submit.prevent="sendReply">
        <label for="clarification-message" class="visually-hidden">
          {{ role === 'coordinator' ? 'Your message to the organiser' : 'Your reply' }}
        </label>
        <textarea
          id="clarification-message"
          ref="composer"
          v-model="reply"
          rows="2"
          :maxlength="MAX_MESSAGE_LENGTH"
          :placeholder="role === 'coordinator' ? 'Ask the organiser something...' : 'Write a reply...'"
          @keydown="onReplyKeydown"
        />
        <button type="submit" class="send" :disabled="busy || Boolean(replyProblem)">
          {{ busy ? 'Sending...' : 'Send' }}
        </button>
      </form>
      <p v-if="canReply" class="counter" aria-live="polite">
        Enter to send · Shift+Enter for a new line · {{ replyLength }} / {{ MAX_MESSAGE_LENGTH }}
      </p>
      <p v-else-if="!isUnderReview" class="footer-note">
        This request is no longer under review, so no new messages can be sent.
      </p>

      <p v-if="error" class="footer-note error" role="alert">{{ error }}</p>
      <p v-if="success" class="footer-note success" role="status">{{ success }}</p>
    </footer>
  </section>
</template>

<style scoped>
.chat {
  display: flex; flex-direction: column; overflow: hidden;
  background: var(--cs-surface); border: 1px solid var(--cs-line); border-radius: 14px; box-shadow: var(--cs-shadow-md);
}

.chat-header {
  display: flex; align-items: center; gap: var(--cs-space-3);
  padding: var(--cs-space-4) var(--cs-space-5); background: var(--cs-paper); border-bottom: 1px solid var(--cs-line);
}
.header-icon {
  display: grid; place-items: center; width: 38px; height: 38px; flex: none;
  border-radius: var(--cs-radius-full); background: var(--cs-signal-tint); color: var(--cs-signal);
}
h2 { margin: 0; font-size: var(--cs-text-md); font-family: var(--cs-font-display); color: var(--cs-ink); }
.header-sub { margin: 2px 0 0; font-size: var(--cs-text-xs); color: var(--cs-ink-soft); }

.chat-body { max-height: 420px; min-height: 120px; overflow-y: auto; padding: var(--cs-space-4) var(--cs-space-5); }
.placeholder { margin: var(--cs-space-5) 0; text-align: center; font-size: var(--cs-text-sm); color: var(--cs-ink-soft); }

.messages { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: var(--cs-space-3); }
.day { display: flex; justify-content: center; margin: var(--cs-space-2) 0; }
.day span { font-size: var(--cs-text-xs); color: var(--cs-ink-soft); }

.message { display: flex; align-items: flex-end; gap: var(--cs-space-2); max-width: 80%; }
.message.own { align-self: flex-end; flex-direction: row-reverse; }
.message.other { align-self: flex-start; }

.avatar {
  display: grid; place-items: center; width: 32px; height: 32px; flex: none;
  border-radius: var(--cs-radius-full); background: var(--cs-neutral-tint); border: 1px solid var(--cs-line);
  font-size: var(--cs-text-xs); font-weight: 700; color: var(--cs-ink-soft);
}

.bubble-wrap { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.own .bubble-wrap { align-items: flex-end; }
.meta { display: flex; gap: var(--cs-space-2); align-items: baseline; padding: 0 6px; font-size: var(--cs-text-xs); color: var(--cs-ink-soft); }
.author { font-weight: 600; color: var(--cs-ink); }

.bubble {
  margin: 0; padding: 10px 14px; border-radius: 18px;
  font-size: var(--cs-text-base); line-height: 1.45; white-space: pre-line; overflow-wrap: anywhere;
}
.other .bubble { background: var(--cs-neutral-tint); color: var(--cs-ink); border-bottom-left-radius: 6px; }
.own .bubble { background: var(--cs-signal); color: #fff; border-bottom-right-radius: 6px; }

.chat-footer { display: flex; flex-direction: column; gap: 6px; padding: var(--cs-space-3) var(--cs-space-5) var(--cs-space-4); border-top: 1px solid var(--cs-line); }
.composer { display: flex; align-items: flex-end; gap: var(--cs-space-2); }
.composer textarea {
  flex: 1; box-sizing: border-box; min-height: 44px; max-height: 160px; padding: 10px 14px;
  border: 1px solid var(--cs-line-strong); border-radius: 22px; background: var(--cs-surface);
  font: inherit; font-size: var(--cs-text-base); resize: vertical;
}
.composer textarea:focus-visible { outline: 2px solid var(--cs-signal); outline-offset: 1px; }
.send {
  min-height: 44px; padding: 0 var(--cs-space-5); border: none; border-radius: var(--cs-radius-full);
  background: var(--cs-signal); color: #fff; font: inherit; font-size: var(--cs-text-sm); font-weight: 700; cursor: pointer;
}
.send:disabled { opacity: .5; cursor: not-allowed; }
.send:focus-visible { outline: 2px solid var(--cs-signal-strong); outline-offset: 2px; }
.counter { margin: 0; text-align: right; font-size: var(--cs-text-xs); color: var(--cs-ink-soft); }
.footer-note { margin: 0; font-size: var(--cs-text-sm); color: var(--cs-ink-soft); }
.error { color: var(--cs-occupied); }
.success { color: var(--cs-available); }

.visually-hidden {
  position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden;
  clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0;
}

@media (max-width: 600px) {
  .chat-header, .chat-body, .chat-footer { padding-left: var(--cs-space-4); padding-right: var(--cs-space-4); }
  .message { max-width: 92%; }
}
</style>
