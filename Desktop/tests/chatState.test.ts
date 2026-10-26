import { describe, expect, it } from 'vitest'
import { addUserMessage, applyEvent, fromHistory, initialChat, toPermissionRequest } from '@/store/chatState'

const run = (events: Parameters<typeof applyEvent>[1][], start = initialChat) => events.reduce(applyEvent, start)

describe('chat event reducer', () => {
  it('streams text deltas into one assistant message', () => {
    const s = run([{ type: 'text_delta', text: 'Hel' }, { type: 'text_delta', text: 'lo' }], addUserMessage(initialChat, 'hi'))
    expect(s.messages.map((m) => m.role)).toEqual(['user', 'assistant'])
    expect(s.messages[1].parts).toEqual([{ type: 'text', text: 'Hello' }])
    expect(s.streaming).toBe(true)
  })

  it('interleaves text and tool calls in order and resolves results by id', () => {
    const s = run([
      { type: 'text_delta', text: 'Reading…' },
      { type: 'tool_call', id: 't1', name: 'read_file', arguments: { path: 'a.py' } },
      { type: 'tool_result', id: 't1', content: 'print(1)', is_error: false },
      { type: 'text_delta', text: 'Done.' }
    ])
    const parts = s.messages[0].parts
    expect(parts.map((p) => p.type)).toEqual(['text', 'tool', 'text'])
    expect(parts[1]).toMatchObject({ id: 't1', status: 'done', result: 'print(1)' })
  })

  it('marks failed tools and ignores results for unknown ids', () => {
    const s = run([{ type: 'tool_call', id: 't1', name: 'bash' }, { type: 'tool_result', id: 't1', content: 'boom', is_error: true }])
    expect(s.messages[0].parts[0]).toMatchObject({ status: 'error', result: 'boom' })
    expect(run([{ type: 'tool_result', id: 'zzz', content: 'x' }])).toEqual(initialChat)
  })

  it('captures permission requests (request_id or id) and clears them on done', () => {
    const s = run([{ type: 'permission_request', request_id: 'r1', tool_name: 'bash', arguments: { command: 'ls' } }])
    expect(s.permission).toEqual({ id: 'r1', toolName: 'bash', arguments: { command: 'ls' } })
    expect(run([{ type: 'permission_request', id: 'r2', name: 'edit_file' }]).permission?.id).toBe('r2')
    expect(applyEvent(s, { type: 'done' }).permission).toBeNull()
    expect(run([{ type: 'permission_request' }]).permission).toBeNull()
  })

  it('stops streaming on done and error, and shows the error', () => {
    const streaming = addUserMessage(initialChat, 'x')
    expect(applyEvent(streaming, { type: 'done', stop_reason: 'end_turn' }).streaming).toBe(false)
    const failed = applyEvent(streaming, { type: 'error', message: 'rate limited' })
    expect(failed.streaming).toBe(false)
    expect(failed.messages[failed.messages.length - 1].parts[0]).toEqual({ type: 'error', message: 'rate limited' })
  })

  it('adds a system note on compaction and ignores unknown events', () => {
    expect(run([{ type: 'compaction' }]).messages[0].role).toBe('system')
    expect(run([{ type: 'skill_creation_check' }])).toEqual(initialChat)
  })

  it('rebuilds history, dropping empty and tool-role entries', () => {
    const msgs = fromHistory([
      { role: 'user', content: 'a' },
      { role: 'tool', content: 'ignored' },
      { role: 'assistant', content: '' },
      { role: 'assistant', content: 'b' }
    ])
    expect(msgs.map((m) => m.role)).toEqual(['user', 'assistant'])
  })
})

describe('toPermissionRequest', () => {
  it('reads main-agent and subagent event shapes', () => {
    expect(toPermissionRequest({ request_id: 'r1', tool_name: 'bash', arguments: { command: 'ls' } })).toEqual({
      id: 'r1', toolName: 'bash', arguments: { command: 'ls' }
    })
    expect(toPermissionRequest({ id: 'r2', name: 'write_file' }, 'subagent')).toEqual({
      id: 'r2', toolName: 'write_file', arguments: {}, source: 'subagent'
    })
  })

  it('rejects malformed events', () => {
    expect(toPermissionRequest({})).toBeNull()
    expect(toPermissionRequest({ request_id: 'x' })).toBeNull()
  })
})
