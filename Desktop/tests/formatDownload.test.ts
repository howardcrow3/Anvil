import { describe, expect, it } from 'vitest'
import { describeProgress, formatGb } from '@/lib/formatDownload'

const GiB = 2 ** 30

describe('download formatting', () => {
  it('formats bytes as GB with one decimal', () => {
    expect(formatGb(1.5 * GiB)).toBe('1.5 GB')
    expect(formatGb(0)).toBe('0.0 GB')
  })

  it('omits speed and ETA during the first two seconds', () => {
    const p = describeProgress({ done: GiB / 10, total: GiB, startedAt: 0, startDone: 0 }, 1000)
    expect(p.label).toBe('0.1 / 1.0 GB')
    expect(p.percent).toBe(10)
  })

  it('reports speed and minutes left once it has data', () => {
    const p = describeProgress({ done: 100 * 2 ** 20, total: GiB, startedAt: 0, startDone: 0 }, 10_000)
    expect(p.label).toBe('0.1 / 1.0 GB · 10 MB/s · 1.5 min left')
  })

  it('measures speed from the resume point, not from byte zero', () => {
    const p = describeProgress({ done: 600 * 2 ** 20, total: GiB, startedAt: 0, startDone: 500 * 2 ** 20 }, 10_000)
    expect(p.label).toContain('10 MB/s')
  })

  it('clamps the percentage and handles an unknown total', () => {
    expect(describeProgress({ done: 5, total: 0, startedAt: 0, startDone: 0 }, 0).percent).toBe(0)
    expect(describeProgress({ done: 200, total: 100, startedAt: 0, startDone: 0 }, 0).percent).toBe(100)
  })
})
