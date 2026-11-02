import type { DownloadProgressEvent, ModelInfo } from '@/lib/types'

/** A model download in flight (or failed, awaiting Retry or Cancel). Byte counts are cumulative across files. */
export interface DownloadEntry {
  done: number
  total: number
  startedAt: number
  /** Bytes already on disk when this run began, so speed ignores a resumed partial file. */
  startDone: number
  error?: string
}

export type Downloads = Record<string, DownloadEntry>

const without = (state: Downloads, id: string): Downloads => {
  const { [id]: _removed, ...rest } = state
  return rest
}

export function applyDownloadEvent(state: Downloads, e: DownloadProgressEvent, now: number): Downloads {
  const prev = state[e.model_id]
  if (e.status === 'ready' || e.status === 'cancelled') return without(state, e.model_id)
  if (e.status === 'error') {
    return { ...state, [e.model_id]: { ...(prev ?? { done: 0, total: 0, startedAt: now, startDone: 0 }), error: e.error ?? 'Download failed' } }
  }
  const done = e.done ?? prev?.done ?? 0
  const total = e.total ?? prev?.total ?? 0
  if (!prev || prev.error || prev.total === 0) return { ...state, [e.model_id]: { done, total, startedAt: now, startDone: done } }
  return { ...state, [e.model_id]: { ...prev, done, total } }
}

/** Adds entries for models the runtime says are downloading (e.g. after a reconnect); existing entries win. */
export function seedFromModels(models: ModelInfo[], now: number, existing: Downloads): Downloads {
  const next = { ...existing }
  for (const m of models) {
    if (m.status !== 'downloading' || next[m.id]) continue
    const done = m.progress?.done ?? 0
    next[m.id] = { done, total: m.progress?.total ?? 0, startedAt: now, startDone: done }
  }
  return next
}
