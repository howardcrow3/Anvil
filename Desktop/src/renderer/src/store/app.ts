import { create } from 'zustand'
import type { RuntimeState } from '../../../shared/types'
import { call, rpc } from '@/lib/api'
import { bridge, resolveRuntime, watchRuntime } from '@/lib/bridge'
import type { ConnectionState } from '@/lib/rpc'
import type { ChatEvent, ModelInfo, SessionMeta } from '@/lib/types'
import { addUserMessage, applyEvent, fromHistory, initialChat, type ChatState } from './chatState'

export type SettingsTab = 'general' | 'apikey' | 'permissions' | 'mcp'
export type Theme = 'system' | 'light' | 'dark'

interface AppStore {
  connection: ConnectionState
  runtime: RuntimeState
  sessions: SessionMeta[]
  currentSessionId: string | null
  models: ModelInfo[]
  settings: Record<string, unknown>
  planning: boolean
  chat: ChatState
  notice: string | null
  settingsOpen: boolean
  settingsTab: SettingsTab
  theme: Theme

  init(): () => void
  refreshSessions(): Promise<void>
  refreshModels(): Promise<void>
  refreshSettings(): Promise<void>
  setSetting(key: string, value: unknown): Promise<void>
  selectModel(id: string): Promise<void>
  newChat(): void
  openSession(id: string): Promise<void>
  send(text: string): Promise<void>
  cancel(): Promise<void>
  togglePlanning(): Promise<void>
  respondPermission(approved: boolean): Promise<void>
  openSettings(tab?: SettingsTab): void
  closeSettings(): void
  setTheme(theme: Theme): void
  setNotice(message: string | null): void
}

const THEME_KEY = 'anvil.theme'
const readTheme = (): Theme => {
  try {
    const v = localStorage.getItem(THEME_KEY)
    return v === 'light' || v === 'dark' ? v : 'system'
  } catch {
    return 'system'
  }
}
export const applyTheme = (theme: Theme): void => {
  if (theme === 'system') document.documentElement.removeAttribute('data-theme')
  else document.documentElement.setAttribute('data-theme', theme)
}

const message = (e: unknown): string => (e instanceof Error ? e.message : String(e))

export const useApp = create<AppStore>((set, get) => ({
  connection: 'closed',
  runtime: { status: 'starting' },
  sessions: [],
  currentSessionId: null,
  models: [],
  settings: {},
  planning: false,
  chat: initialChat,
  notice: null,
  settingsOpen: false,
  settingsTab: 'general',
  theme: readTheme(),

  init() {
    applyTheme(get().theme)
    const offs: (() => void)[] = []

    const connect = (runtime: RuntimeState): void => {
      set({ runtime })
      if (runtime.status === 'ready' && runtime.url) rpc.connect(runtime.url)
      else if (runtime.status !== 'starting') rpc.disconnect()
    }

    offs.push(
      rpc.onState((connection) => {
        set({ connection })
        if (connection === 'open') {
          void get().refreshSessions()
          void get().refreshModels()
          void get().refreshSettings()
        } else if (connection === 'closed') {
          // A dropped connection ends any in-flight turn.
          set((s) => ({ chat: { ...s.chat, streaming: false, permission: null } }))
        }
      }),
      rpc.on('chat.event', (params) => {
        const event = params as unknown as ChatEvent
        set((s) => ({ chat: applyEvent(s.chat, event) }))
        if (event.type === 'done') {
          void get().refreshSessions()
          if (!document.hasFocus()) void bridge()?.notify('Anvil', 'Response ready')
        }
      }),
      watchRuntime(connect)
    )
    void resolveRuntime().then(connect)
    return () => {
      offs.forEach((off) => off())
      rpc.disconnect()
    }
  },

  async refreshSessions() {
    try {
      const sessions = await call<SessionMeta[]>('session.list')
      set({ sessions: [...sessions].sort((a, b) => (b.created_at ?? '').localeCompare(a.created_at ?? '')) })
    } catch (e) {
      set({ notice: `Couldn't load sessions: ${message(e)}` })
    }
  },

  async refreshModels() {
    try {
      set({ models: await call<ModelInfo[]>('model.list') })
    } catch (e) {
      set({ notice: `Couldn't load models: ${message(e)}` })
    }
  },

  async refreshSettings() {
    try {
      set({ settings: await call<Record<string, unknown>>('settings.get') })
    } catch (e) {
      set({ notice: `Couldn't load settings: ${message(e)}` })
    }
  },

  async setSetting(key, value) {
    // Optimistic: controls reflect the change at once and roll back if the runtime refuses it.
    const previous = get().settings[key]
    set((s) => ({ settings: { ...s.settings, [key]: value } }))
    try {
      await call('settings.set', { key, value })
    } catch (e) {
      set((s) => ({ settings: { ...s.settings, [key]: previous } }))
      throw e
    }
    if (key === 'api_key') await get().refreshModels()
  },

  async selectModel(id) {
    try {
      await call('model.select', { model_id: id })
      await get().refreshModels()
    } catch (e) {
      set({ notice: message(e) })
    }
  },

  newChat() {
    if (get().chat.streaming) return
    set({ currentSessionId: null, chat: initialChat, planning: false })
  },

  async openSession(id) {
    if (get().chat.streaming) return
    try {
      const result = await call<{ messages: { role: string; content: string }[] }>('session.resume', { session_id: id })
      set({ currentSessionId: id, chat: { ...initialChat, messages: fromHistory(result.messages ?? []) } })
    } catch (e) {
      set({ notice: `Couldn't open that session: ${message(e)}` })
    }
  },

  async send(text) {
    const trimmed = text.trim()
    if (!trimmed || get().chat.streaming) return
    set((s) => ({ chat: addUserMessage(s.chat, trimmed) }))
    try {
      let sessionId = get().currentSessionId
      if (!sessionId) {
        sessionId = crypto.randomUUID()
        await call('session.create', { session_id: sessionId })
        set({ currentSessionId: sessionId })
      }
      // chat.send resolves when the turn ends; the content arrives as chat.event notifications meanwhile.
      await call('chat.send', { message: trimmed, session_id: sessionId }, 0)
    } catch (e) {
      set((s) => ({ chat: applyEvent(s.chat, { type: 'error', message: message(e) }) }))
    }
  },

  async cancel() {
    try {
      await call('chat.cancel')
    } catch (e) {
      set({ notice: message(e) })
    }
  },

  async togglePlanning() {
    const next = !get().planning
    try {
      await call(next ? 'planning.start' : 'planning.stop')
      set({ planning: next })
    } catch (e) {
      set({ notice: message(e) })
    }
  },

  async respondPermission(approved) {
    const request = get().chat.permission
    if (!request) return
    set((s) => ({ chat: { ...s.chat, permission: null } }))
    try {
      await call('permission.respond', { request_id: request.id, approved })
    } catch (e) {
      set({ notice: message(e) })
    }
  },

  openSettings: (tab) => set({ settingsOpen: true, settingsTab: tab ?? get().settingsTab }),
  closeSettings: () => set({ settingsOpen: false }),
  setTheme(theme) {
    try {
      localStorage.setItem(THEME_KEY, theme)
    } catch {
      /* storage unavailable: the theme just won't persist */
    }
    applyTheme(theme)
    set({ theme })
  },
  setNotice: (notice) => set({ notice })
}))
