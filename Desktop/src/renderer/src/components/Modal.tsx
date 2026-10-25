import { useEffect, useRef } from 'react'

interface Props {
  title: string
  onClose: () => void
  width?: number
  children: React.ReactNode
}

/** Accessible modal: Esc closes, focus moves in and returns to the opener, background is inert to clicks. */
export function Modal({ title, onClose, width = 560, children }: Props): React.JSX.Element {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    ref.current?.querySelector<HTMLElement>('[autofocus], input, select, textarea, button')?.focus()
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('keydown', onKey)
      previous?.focus?.()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
  return (
    <div className="backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} style={{ width }} ref={ref}>
        <h2>{title}</h2>
        {children}
      </div>
    </div>
  )
}
