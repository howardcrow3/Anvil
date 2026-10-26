import { Modal } from '@/components/Modal'
import { useApp, type SettingsTab } from '@/store/app'
import { ApiKeySettings } from './ApiKeySettings'
import { EndpointSettings } from './EndpointSettings'
import { GeneralSettings } from './GeneralSettings'
import { McpSettings } from './McpSettings'
import { PermissionSettings } from './PermissionSettings'

const TABS: { id: SettingsTab; label: string }[] = [
  { id: 'general', label: 'General' },
  { id: 'apikey', label: 'API Key' },
  { id: 'endpoints', label: 'Endpoints' },
  { id: 'permissions', label: 'Permissions' },
  { id: 'mcp', label: 'MCP' }
]

export function SettingsDialog(): React.JSX.Element {
  const tab = useApp((s) => s.settingsTab)
  const open = useApp((s) => s.openSettings)
  const close = useApp((s) => s.closeSettings)
  return (
    <Modal title="Settings" onClose={close} width={760}>
      <div className="settings">
        <div className="tabs" role="tablist" aria-orientation="vertical">
          {TABS.map((t) => (
            <button key={t.id} role="tab" aria-selected={tab === t.id} className={`tab ${tab === t.id ? 'active' : ''}`} onClick={() => open(t.id)}>
              {t.label}
            </button>
          ))}
        </div>
        <div className="tab-panel" role="tabpanel">
          {tab === 'general' && <GeneralSettings />}
          {tab === 'apikey' && <ApiKeySettings />}
          {tab === 'endpoints' && <EndpointSettings />}
          {tab === 'permissions' && <PermissionSettings />}
          {tab === 'mcp' && <McpSettings />}
        </div>
      </div>
      <div className="modal-actions">
        <button className="btn" onClick={close}>
          Done
        </button>
      </div>
    </Modal>
  )
}
