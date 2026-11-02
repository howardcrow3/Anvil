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

/**
 * Reconciles local entries with `model.list`, which is the runtime's truth: adds entries for models it says are
 * downloading (e.g. after a reconnect; existing entries win) and drops running entries it no longer reports
 * (e.g. the runtime restarted). Failed entries stay until the user retries or removes them.
 */
export function seedFromModels(models: ModelInfo[], now: number, existing: Downloads): Downloads {
  const downloading = new Map(models.filter((m) => m.status === 'downloading').map((m) => [m.id, m]))
  const next: Downloads = {}
  for (const [id, entry] of Object.entries(existing)) if (entry.error || downloading.has(id)) next[id] = entry
  for (const [id, m] of downloading) {
    if (next[id]) continue
    const done = m.progress?.done ?? 0
    next[id] = { done, total: m.progress?.total ?? 0, startedAt: now, startDone: done }
  }
  return next
}
