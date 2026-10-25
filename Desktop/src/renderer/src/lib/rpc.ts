/** JSON-RPC 2.0 client over a WebSocket, with reconnect, per-request timeouts and notification fan-out. */

export type ConnectionState = 'connecting' | 'open' | 'closed'
export type NotificationHandler = (params: Record<string, unknown>) => void

export class RpcError extends Error {
  constructor(
    message: string,
    readonly code = -1
  ) {
    super(message)
    this.name = 'RpcError'
  }
}

interface Pending {
  resolve: (value: unknown) => void
  reject: (error: Error) => void
  timer: ReturnType<typeof setTimeout> | null
}

type WebSocketCtor = new (url: string) => WebSocket

export class RpcClient {
  state: ConnectionState = 'closed'
  private ws: WebSocket | null = null
  private url: string | null = null
  private nextId = 1
  private retries = 0
  private wantOpen = false
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private readonly pending = new Map<number, Pending>()
  private readonly handlers = new Map<string, Set<NotificationHandler>>()
  private readonly stateListeners = new Set<(state: ConnectionState) => void>()

  constructor(
    private readonly WS: WebSocketCtor = WebSocket as unknown as WebSocketCtor,
    private readonly backoffMs = (attempt: number): number => Math.min(500 * 2 ** attempt, 8000)
  ) {}

  connect(url: string): void {
    this.url = url
    this.wantOpen = true
    this.retries = 0
    this.open()
  }

  disconnect(): void {
    this.wantOpen = false
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
    this.ws?.close()
  }

  /** Raw request: resolves with the JSON-RPC `result`. `timeoutMs` 0 disables the timeout. */
  request<T = unknown>(method: string, params: Record<string, unknown> = {}, timeoutMs = 60_000): Promise<T> {
    if (this.state !== 'open' || !this.ws) return Promise.reject(new RpcError('Not connected to the agent runtime'))
    const id = this.nextId++
    return new Promise<T>((resolve, reject) => {
      const timer =
        timeoutMs > 0
          ? setTimeout(() => {
              this.pending.delete(id)
              reject(new RpcError(`${method} timed out after ${Math.round(timeoutMs / 1000)}s`))
            }, timeoutMs)
          : null
      this.pending.set(id, { resolve: resolve as (v: unknown) => void, reject, timer })
      this.ws!.send(JSON.stringify({ jsonrpc: '2.0', id, method, params }))
    })
  }

  on(method: string, handler: NotificationHandler): () => void {
    let set = this.handlers.get(method)
    if (!set) this.handlers.set(method, (set = new Set()))
    set.add(handler)
    return () => set.delete(handler)
  }

  onState(cb: (state: ConnectionState) => void): () => void {
    this.stateListeners.add(cb)
    return () => this.stateListeners.delete(cb)
  }

  private setState(state: ConnectionState): void {
    if (this.state === state) return
    this.state = state
    this.stateListeners.forEach((cb) => cb(state))
  }

  private open(): void {
    if (!this.url) return
    this.setState('connecting')
    const ws = new this.WS(this.url)
    this.ws = ws
    ws.onopen = () => {
      this.retries = 0
      this.setState('open')
    }
    ws.onmessage = (event) => this.receive(String(event.data))
    ws.onclose = () => {
      if (this.ws !== ws) return
      this.ws = null
      this.setState('closed')
      this.failAll(new RpcError('Connection to the agent runtime closed'))
      if (this.wantOpen) {
        this.reconnectTimer = setTimeout(() => this.open(), this.backoffMs(this.retries++))
      }
    }
    ws.onerror = () => {
      /* onclose follows and handles recovery */
    }
  }

  private receive(text: string): void {
    let msg: { id?: number; method?: string; params?: Record<string, unknown>; result?: unknown; error?: { code: number; message: string } }
    try {
      msg = JSON.parse(text)
    } catch {
      return
    }
    if (typeof msg.id === 'number') {
      const pending = this.pending.get(msg.id)
      if (!pending) return
      this.pending.delete(msg.id)
      if (pending.timer) clearTimeout(pending.timer)
      if (msg.error) pending.reject(new RpcError(msg.error.message, msg.error.code))
      else pending.resolve(msg.result)
    } else if (msg.method) {
      this.handlers.get(msg.method)?.forEach((handler) => handler(msg.params ?? {}))
    }
  }

  private failAll(error: Error): void {
    for (const pending of this.pending.values()) {
      if (pending.timer) clearTimeout(pending.timer)
      pending.reject(error)
    }
    this.pending.clear()
  }
}

/**
 * The runtime reports some failures as a result of just `{ "error": "…" }` rather than a JSON-RPC error.
 * `call` turns those into thrown RpcErrors so callers can use plain try/catch.
 */
export function unwrapResult<T>(result: unknown): T {
  if (result && typeof result === 'object' && !Array.isArray(result)) {
    const keys = Object.keys(result)
    if (keys.length === 1 && keys[0] === 'error' && typeof (result as { error: unknown }).error === 'string') {
      throw new RpcError((result as { error: string }).error)
    }
  }
  return result as T
}
