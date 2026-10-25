/** Types shared by the Electron main process, the preload bridge and the renderer. */

export type RuntimeStatus = 'starting' | 'ready' | 'crashed' | 'stopped'

export interface RuntimeState {
  status: RuntimeStatus
  /** ws://127.0.0.1:<port>/rpc?token=… — present once the runtime is ready. */
  url?: string
  /** Last error / exit reason, for display. */
  detail?: string
}

export interface AnvilBridge {
  platform: string
  getRuntime(): Promise<RuntimeState>
  onRuntimeStatus(cb: (state: RuntimeState) => void): () => void
  restartRuntime(): Promise<RuntimeState>
  notify(title: string, body: string): Promise<void>
  openExternal(url: string): Promise<void>
  chooseDirectory(): Promise<string | null>
}
