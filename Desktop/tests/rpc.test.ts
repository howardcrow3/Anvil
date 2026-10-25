import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RpcClient, RpcError, unwrapResult } from '@/lib/rpc'

class FakeSocket {
  static instances: FakeSocket[] = []
  onopen: (() => void) | null = null
  onmessage: ((e: { data: string }) => void) | null = null
  onclose: (() => void) | null = null
  onerror: (() => void) | null = null
  sent: Record<string, unknown>[] = []
  constructor(readonly url: string) {
    FakeSocket.instances.push(this)
  }
  send(data: string): void {
    this.sent.push(JSON.parse(data))
  }
  close(): void {
    this.onclose?.()
  }
  open(): void {
    this.onopen?.()
  }
  push(msg: unknown): void {
    this.onmessage?.({ data: JSON.stringify(msg) })
  }
}

const make = (): RpcClient => new RpcClient(FakeSocket as never, () => 100)
const last = (): FakeSocket => FakeSocket.instances[FakeSocket.instances.length - 1]

beforeEach(() => {
  FakeSocket.instances = []
  vi.useFakeTimers()
})
afterEach(() => vi.useRealTimers())

describe('RpcClient', () => {
  it('rejects requests while disconnected', async () => {
    await expect(make().request('x')).rejects.toThrow('Not connected')
  })

  it('matches responses to requests by id', async () => {
    const rpc = make()
    rpc.connect('ws://x')
    last().open()
    const a = rpc.request('a')
    const b = rpc.request('b', { n: 1 })
    const [first, second] = last().sent
    last().push({ jsonrpc: '2.0', id: second.id, result: 'B' })
    last().push({ jsonrpc: '2.0', id: first.id, result: 'A' })
    expect(await a).toBe('A')
    expect(await b).toBe('B')
    expect(second).toMatchObject({ method: 'b', params: { n: 1 } })
  })

  it('rejects with the server error code and message', async () => {
    const rpc = make()
    rpc.connect('ws://x')
    last().open()
    const p = rpc.request('nope')
    last().push({ jsonrpc: '2.0', id: last().sent[0].id, error: { code: -32601, message: 'Method not found' } })
    await expect(p).rejects.toMatchObject({ message: 'Method not found', code: -32601 })
  })

  it('times out, but not when timeout is 0', async () => {
    const rpc = make()
    rpc.connect('ws://x')
    last().open()
    const slow = rpc.request('slow', {}, 1000)
    const forever = rpc.request('long', {}, 0)
    const settled = vi.fn()
    forever.then(settled, settled)
    vi.advanceTimersByTime(1500)
    await expect(slow).rejects.toThrow('timed out')
    expect(settled).not.toHaveBeenCalled()
  })

  it('dispatches notifications and supports unsubscribe', () => {
    const rpc = make()
    rpc.connect('ws://x')
    last().open()
    const handler = vi.fn()
    const off = rpc.on('chat.event', handler)
    last().push({ jsonrpc: '2.0', method: 'chat.event', params: { type: 'text_delta', text: 'hi' } })
    off()
    last().push({ jsonrpc: '2.0', method: 'chat.event', params: { type: 'done' } })
    expect(handler).toHaveBeenCalledTimes(1)
    expect(handler).toHaveBeenCalledWith({ type: 'text_delta', text: 'hi' })
  })

  it('fails pending requests on close and reconnects with backoff', async () => {
    const rpc = make()
    const states: string[] = []
    rpc.onState((s) => states.push(s))
    rpc.connect('ws://x')
    last().open()
    const pending = rpc.request('x')
    last().close()
    await expect(pending).rejects.toBeInstanceOf(RpcError)
    expect(FakeSocket.instances).toHaveLength(1)
    vi.advanceTimersByTime(150)
    expect(FakeSocket.instances).toHaveLength(2)
    last().open()
    expect(states).toEqual(['connecting', 'open', 'closed', 'connecting', 'open'])
  })

  it('does not reconnect after disconnect()', () => {
    const rpc = make()
    rpc.connect('ws://x')
    last().open()
    rpc.disconnect()
    vi.advanceTimersByTime(60_000)
    expect(FakeSocket.instances).toHaveLength(1)
  })
})

describe('unwrapResult', () => {
  it('throws on runtime { error } results only', () => {
    expect(() => unwrapResult({ error: 'No model' })).toThrow('No model')
    expect(unwrapResult({ ok: false, error: 'x' })).toEqual({ ok: false, error: 'x' })
    expect(unwrapResult([1])).toEqual([1])
    expect(unwrapResult({ status: 'ok' })).toEqual({ status: 'ok' })
  })
})
