import { useCallback, useEffect, useState } from 'react'
import { useApp } from '@/store/app'

/** Load data when the runtime connection opens and on demand; errors become a message instead of a crash. */
export function useLoad<T>(fetcher: () => Promise<T>): { data: T | null; error: string | null; loading: boolean; reload: () => Promise<void> } {
  const connection = useApp((s) => s.connection)
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      setData(await fetcher())
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (connection === 'open') void reload()
  }, [connection, reload])

  return { data, error, loading, reload }
}

export const errText = (e: unknown): string => (e instanceof Error ? e.message : String(e))
