import type { DownloadEntry } from '@/store/downloadState'

const GIB = 2 ** 30
const MIB = 2 ** 20

export const formatGb = (bytes: number): string => `${(bytes / GIB).toFixed(1)} GB`

const formatEta = (seconds: number): string => {
  if (seconds < 90) return `${Math.max(1, Math.round(seconds))} s left`
  if (seconds < 90 * 60) return `${Math.round((seconds / 60) * 10) / 10} min left`
  return `${Math.round((seconds / 3600) * 10) / 10} h left`
}

/** Percent complete and a one-line label such as "1.5 / 4.7 GB · 12 MB/s · 4 min left". */
export function describeProgress(e: DownloadEntry, now: number): { percent: number; label: string } {
  const percent = e.total > 0 ? Math.min(100, Math.max(0, Math.round((e.done / e.total) * 100))) : 0
  let label = `${(e.done / GIB).toFixed(1)} / ${formatGb(e.total)}`
  const elapsed = (now - e.startedAt) / 1000
  const fetched = e.done - e.startDone
  if (elapsed >= 2 && fetched > 0) {
    const speed = fetched / elapsed
    label += ` · ${Math.round(speed / MIB)} MB/s`
    if (e.total > e.done) label += ` · ${formatEta((e.total - e.done) / speed)}`
  }
  return { percent, label }
}
