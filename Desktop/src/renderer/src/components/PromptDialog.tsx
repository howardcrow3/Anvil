import { useState } from 'react'
import { Modal } from './Modal'

interface Props {
  title: string
  message?: string
  /** When set, shows a text field and passes its value to onConfirm. */
  inputLabel?: string
  confirmLabel: string
  danger?: boolean
  onConfirm: (value: string) => void
  onClose: () => void
}

/** In-page replacement for window.confirm/prompt (prompt() is not supported in Electron renderers). */
export function PromptDialog({ title, message, inputLabel, confirmLabel, danger, onConfirm, onClose }: Props): React.JSX.Element {
  const [value, setValue] = useState('')
  const needsInput = inputLabel !== undefined
  return (
    <Modal title={title} onClose={onClose} width={440}>
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault()
          if (needsInput && !value.trim()) return
          onConfirm(value.trim())
          onClose()
        }}
      >
        {message && <p className="muted">{message}</p>}
        {needsInput && (
          <label className="field">
            <span>{inputLabel}</span>
            <input value={value} onChange={(e) => setValue(e.target.value)} autoFocus />
          </label>
        )}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className={`btn ${danger ? 'danger' : 'primary'}`} disabled={needsInput && !value.trim()}>{confirmLabel}</button>
        </div>
      </form>
    </Modal>
  )
}
