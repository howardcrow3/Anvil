import type { AnvilBridge, RuntimeState } from '../../../shared/types'

declare global {
  interface Window {
    anvil?: AnvilBridge
  }
}

export const bridge = (): AnvilBridge | undefined => window.anvil

/**
 * Where the runtime is. In Electron the main process owns it. In a plain browser (dev server, Playwright)
 * pass `?runtime=ws://127.0.0.1:PORT/rpc?token=…` — URL-encoded — to attach to one started by hand.
 */
export async function resolveRuntime(search = window.location.search): Promise<RuntimeState> {
  const b = bridge()
  if (b) return b.getRuntime()
  const url = new URLSearchParams(search).get('runtime')
  return url ? { status: 'ready', url } : { status: 'stopped', detail: 'No runtime URL. Open with ?runtime=ws://…' }
}

export function watchRuntime(cb: (state: RuntimeState) => void): () => void {
  return bridge()?.onRuntimeStatus(cb) ?? (() => {})
}

export function openExternal(url: string): void {
  const b = bridge()
  if (b) void b.openExternal(url)
  else window.open(url, '_blank', 'noopener,noreferrer')
}
