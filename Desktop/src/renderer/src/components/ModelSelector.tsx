import { useApp } from '@/store/app'

const GROUPS: { provider: 'cloud' | 'local' | 'custom'; label: string }[] = [
  { provider: 'cloud', label: 'Cloud' },
  { provider: 'local', label: 'Local' },
  { provider: 'custom', label: 'Custom endpoints' }
]

export function ModelSelector(): React.JSX.Element {
  const models = useApp((s) => s.models)
  const select = useApp((s) => s.selectModel)
  const openSettings = useApp((s) => s.openSettings)
  const active = models.find((m) => m.active)

  return (
    <label className="model-select">
      <span className="sr-only">Model</span>
      <select
        value={active?.id ?? ''}
        onChange={(e) => {
          const model = models.find((m) => m.id === e.target.value)
          if (model?.status === 'needs_key') openSettings('apikey')
          else if (model) void select(model.id)
        }}
      >
        {!active && <option value="">Select a model…</option>}
        {GROUPS.map(({ provider, label }) => {
          const group = models.filter((m) => m.provider === provider)
          return group.length ? (
            <optgroup key={provider} label={label}>
              {group.map((m) => (
                <option key={m.id} value={m.id} disabled={m.status === 'downloadable'}>
                  {m.name}
                  {m.size ? ` · ${m.size}` : ''}
                  {m.status === 'needs_key' ? ' (needs API key)' : m.status === 'downloadable' ? ' (not downloaded)' : ''}
                </option>
              ))}
            </optgroup>
          ) : null
        })}
      </select>
    </label>
  )
}
