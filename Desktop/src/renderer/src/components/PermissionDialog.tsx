import { useApp } from '@/store/app'
import { Modal } from './Modal'

export function PermissionDialog(): React.JSX.Element | null {
  const request = useApp((s) => s.chat.permission)
  const respond = useApp((s) => s.respondPermission)
  if (!request) return null
  return (
    <Modal title="Allow this action?" onClose={() => void respond(false)} width={520}>
      {request.source && <p className="muted small">Requested by a {request.source}</p>}
      <p>
        Anvil wants to run <strong>{request.toolName}</strong>:
      </p>
      <pre className="perm-args">{JSON.stringify(request.arguments, null, 2)}</pre>
      <div className="modal-actions">
        <button className="btn" onClick={() => void respond(false)}>
          Deny
        </button>
        <button className="btn primary" autoFocus onClick={() => void respond(true)}>
          Allow
        </button>
      </div>
    </Modal>
  )
}
