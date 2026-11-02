import { describe, expect, it } from 'vitest'
import { applyDownloadEvent, seedFromModels, type Downloads } from '@/store/downloadState'
import type { ModelInfo } from '@/lib/types'

const progress = (done: number, total = 100) => ({ model_id: 'm', file: 'a.gguf', done, total })

describe('download state reducer', () => {
  it('accumulates progress and keeps the first startedAt', () => {
    let s: Downloads = {}
    s = applyDownloadEvent(s, progress(10), 1000)
    s = applyDownloadEvent(s, progress(40), 5000)
    expect(s.m).toEqual({ done: 40, total: 100, startedAt: 1000, startDone: 10 })
  })

  it('removes the entry when the download is ready or cancelled', () => {
    const s = applyDownloadEvent({}, progress(10), 0)
    expect(applyDownloadEvent(s, { model_id: 'm', status: 'ready' }, 1)).toEqual({})
    expect(applyDownloadEvent(s, { model_id: 'm', status: 'cancelled' }, 1)).toEqual({})
  })

  it('keeps the entry with its message on error, and a retry starts a fresh clock', () => {
    let s = applyDownloadEvent({}, progress(10), 0)
    s = applyDownloadEvent(s, { model_id: 'm', status: 'error', error: 'network down' }, 1)
    expect(s.m).toMatchObject({ error: 'network down', done: 10 })
    s = applyDownloadEvent(s, progress(30), 9000)
    expect(s.m).toEqual({ done: 30, total: 100, startedAt: 9000, startDone: 30 })
  })

  it('seeds entries for downloading models only, without overwriting existing ones', () => {
    const models = [
      { id: 'a', name: 'A', provider: 'local', status: 'downloading', active: false, progress: { done: 5, total: 10 } },
      { id: 'b', name: 'B', provider: 'local', status: 'downloadable', active: false },
      { id: 'c', name: 'C', provider: 'local', status: 'downloading', active: false }
    ] as ModelInfo[]
    const existing: Downloads = { c: { done: 9, total: 10, startedAt: 1, startDone: 0 } }
    expect(seedFromModels(models, 77, existing)).toEqual({
      a: { done: 5, total: 10, startedAt: 77, startDone: 5 },
      c: existing.c
    })
  })

  it('drops running entries the runtime no longer reports as downloading, but keeps failed ones', () => {
    const models = [
      { id: 'a', name: 'A', provider: 'local', status: 'downloadable', active: false },
      { id: 'b', name: 'B', provider: 'local', status: 'downloadable', active: false }
    ] as ModelInfo[]
    const existing: Downloads = {
      a: { done: 5, total: 10, startedAt: 1, startDone: 0 }, // runtime restarted: stale
      b: { done: 5, total: 10, startedAt: 1, startDone: 0, error: 'network down' },
      gone: { done: 1, total: 10, startedAt: 1, startDone: 0 } // model no longer listed at all
    }
    expect(Object.keys(seedFromModels(models, 0, existing))).toEqual(['b'])
  })
})

describe('placeholder entries', () => {
  it('the first real progress event after the placeholder sets the speed baseline (resumed downloads)', () => {
    let s = applyDownloadEvent({}, { model_id: 'm', done: 0, total: 0 }, 0)
    s = applyDownloadEvent(s, progress(60), 1000)
    expect(s.m).toEqual({ done: 60, total: 100, startedAt: 1000, startDone: 60 })
  })
})
