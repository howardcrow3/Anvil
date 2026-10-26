import type { ChatEvent, Message, Part, PermissionRequest } from '@/lib/types'

export interface ChatState {
  messages: Message[]
  streaming: boolean
  permission: PermissionRequest | null
}

export const initialChat: ChatState = { messages: [], streaming: false, permission: null }

let counter = 0
export const newId = (prefix = 'm'): string => `${prefix}${Date.now().toString(36)}${(counter++).toString(36)}`

/** Appends text to the last assistant message (creating one if the last message isn't the assistant's). */
function withAssistant(messages: Message[]): [Message[], Message] {
  const last = messages[messages.length - 1]
  if (last?.role === 'assistant') return [messages.slice(0, -1), { ...last, parts: [...last.parts] }]
  return [messages, { id: newId(), role: 'assistant', parts: [] }]
}

export function addUserMessage(state: ChatState, text: string): ChatState {
  return {
    ...state,
    streaming: true,
    messages: [...state.messages, { id: newId(), role: 'user', parts: [{ type: 'text', text }] }]
  }
}

/** Pure reducer for streamed `chat.event`s — everything the chat view renders derives from this. */
/** A permission request from the runtime (main agent or a subagent), or null if it is malformed. */
export function toPermissionRequest(event: Record<string, unknown>, source?: string): PermissionRequest | null {
  const e = event as { request_id?: string; id?: string; tool_name?: string; name?: string; arguments?: Record<string, unknown> }
  const id = e.request_id ?? e.id
  const toolName = e.tool_name ?? e.name
  if (!id || !toolName) return null
  return { id, toolName, arguments: e.arguments ?? {}, ...(source ? { source } : {}) }
}

export function applyEvent(state: ChatState, event: ChatEvent): ChatState {
  switch (event.type) {
    case 'text_delta': {
      const text = (event as { text?: string }).text ?? ''
      if (!text) return state
      const [rest, msg] = withAssistant(state.messages)
      const last = msg.parts[msg.parts.length - 1]
      if (last?.type === 'text') msg.parts[msg.parts.length - 1] = { type: 'text', text: last.text + text }
      else msg.parts.push({ type: 'text', text })
      return { ...state, messages: [...rest, msg] }
    }
    case 'tool_call': {
      const e = event as { id: string; name: string; arguments?: Record<string, unknown> }
      const [rest, msg] = withAssistant(state.messages)
      msg.parts.push({ type: 'tool', id: e.id, name: e.name, arguments: e.arguments ?? {}, status: 'running' })
      return { ...state, messages: [...rest, msg] }
    }
    case 'tool_result': {
      const e = event as { id: string; content?: string; is_error?: boolean }
      for (let m = state.messages.length - 1; m >= 0; m--) {
        const message = state.messages[m]
        const index = message.parts.findIndex((p) => p.type === 'tool' && p.id === e.id)
        if (index < 0) continue
        const parts: Part[] = message.parts.map((p, i) =>
          i === index && p.type === 'tool' ? { ...p, result: e.content ?? '', status: e.is_error ? 'error' : 'done' } : p
        )
        const messages = state.messages.slice()
        messages[m] = { ...message, parts }
        return { ...state, messages }
      }
      return state
    }
    case 'permission_request': {
      const permission = toPermissionRequest(event)
      return permission ? { ...state, permission } : state
    }
    case 'compaction':
      return {
        ...state,
        messages: [
          ...state.messages,
          { id: newId(), role: 'system', parts: [{ type: 'text', text: "Context compacted to stay within the model's window." }] }
        ]
      }
    case 'error': {
      const [rest, msg] = withAssistant(state.messages)
      msg.parts.push({ type: 'error', message: (event as { message?: string }).message ?? 'Unknown error' })
      return { ...state, messages: [...rest, msg], streaming: false, permission: null }
    }
    case 'done':
      return { ...state, streaming: false, permission: null }
    default:
      return state
  }
}

/** Rebuilds display messages from a resumed session's stored `{role, content}` history. */
export function fromHistory(history: { role: string; content: string }[]): Message[] {
  return history
    .filter((m) => (m.role === 'user' || m.role === 'assistant') && m.content)
    .map((m) => ({ id: newId(), role: m.role as 'user' | 'assistant', parts: [{ type: 'text' as const, text: m.content }] }))
}
