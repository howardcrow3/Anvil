import { useState } from 'react'
import { Modal } from '@/components/Modal'
import { PromptDialog } from '@/components/PromptDialog'
import { filterSkills, skillSlug, skillsDelete, skillsImport, skillsList, skillsToggle, type SkillItem } from '@/lib/work'
import { errText, useLoad } from './useLoad'

function ImportSkill({ onClose, onDone }: { onClose: () => void; onDone: () => void }): React.JSX.Element {
  const [name, setName] = useState('')
  const [content, setContent] = useState('')
  const [error, setError] = useState<string | null>(null)
  const submit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault()
    if (!name.trim() || !content.trim()) return setError('Both a name and the skill text are required.')
    try {
      await skillsImport(name, content)
      onDone()
      onClose()
    } catch (err) {
      setError(errText(err))
    }
  }
  return (
    <Modal title="Import skill" onClose={onClose} width={600}>
      <form className="form" onSubmit={(e) => void submit(e)}>
        <label className="field">
          <span>Name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
          {name && <small>Saved as “{skillSlug(name)}”</small>}
        </label>
        <label className="field">
          <span>SKILL.md contents</span>
          <textarea rows={10} value={content} onChange={(e) => setContent(e.target.value)} className="mono" />
        </label>
        {error && <div className="msg-error" role="alert">{error}</div>}
        <div className="modal-actions">
          <button type="button" className="btn" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn primary">Import</button>
        </div>
      </form>
    </Modal>
  )
}

export function SkillsView(): React.JSX.Element {
  const { data, error, reload } = useLoad(skillsList)
  const [query, setQuery] = useState('')
  const [importing, setImporting] = useState(false)
  const [deleting, setDeleting] = useState<SkillItem | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  // Optimistic enabled flags so the checkbox responds at once; rolled back on failure.
  const [override, setOverride] = useState<Record<string, boolean>>({})

  const items = filterSkills(data ?? [], query)

  const toggle = async (s: SkillItem, enabled: boolean): Promise<void> => {
    setOverride((o) => ({ ...o, [s.id]: enabled }))
    try {
      await skillsToggle(s.id, enabled)
      setActionError(null)
      await reload()
    } catch (e) {
      setActionError(errText(e))
    } finally {
      setOverride((o) => {
        const { [s.id]: _drop, ...rest } = o
        return rest
      })
    }
  }
  const remove = async (s: SkillItem): Promise<void> => {
    try {
      await skillsDelete(s.id)
      setActionError(null)
    } catch (e) {
      setActionError(errText(e))
    }
    await reload()
  }

  return (
    <section className="view" aria-label="Skills">
      <header className="view-head">
        <h1>Skills</h1>
        <input className="search" type="search" aria-label="Search skills" placeholder="Search…" value={query} onChange={(e) => setQuery(e.target.value)} />
        <span className="grow" />
        <button className="btn primary" onClick={() => setImporting(true)}>Import skill</button>
      </header>
      {(error || actionError) && <div className="msg-error" role="alert">{error ?? actionError}</div>}
      <ul className="skills">
        {items.length === 0 && <li className="muted pad">{query ? 'No skills match your search.' : 'No skills installed.'}</li>}
        {items.map((s) => (
          <li key={`${s.type}:${s.id}`} className="skill">
            <label className="check">
              <input type="checkbox" aria-label={`Enable ${s.name}`} checked={override[s.id] ?? s.enabled} onChange={(e) => void toggle(s, e.target.checked)} />
            </label>
            <div className="grow">
              <div className="card-title">
                {s.type === 'command' ? `/${s.name}` : s.name} <span className="pill">{s.source}</span>
              </div>
              <div className="small muted">{s.description || 'No description'}</div>
            </div>
            {s.type === 'skill' && s.source === 'user' && (
              <button className="btn ghost" aria-label={`Delete ${s.name}`} onClick={() => setDeleting(s)}>Delete</button>
            )}
          </li>
        ))}
      </ul>
      {deleting && <PromptDialog title="Delete skill?" message={`“${deleting.name}” will be removed.`} confirmLabel="Delete" danger onClose={() => setDeleting(null)} onConfirm={() => void remove(deleting)} />}
      {importing && <ImportSkill onClose={() => setImporting(false)} onDone={() => void reload()} />}
    </section>
  )
}
