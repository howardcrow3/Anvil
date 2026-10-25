import { describe, expect, it } from 'vitest'
import {
  blankEndpoint,
  cleanEndpoint,
  filterSkills,
  groupKanban,
  kanbanActions,
  parseMembers,
  projectProgress,
  readEndpoints,
  skillSlug,
  validateEndpoint,
  type KanbanTask,
  type SkillItem
} from '../src/renderer/src/lib/work'

const ep = (over = {}) => ({ ...blankEndpoint(), name: 'lm', base_url: 'http://localhost:1234/v1', default_model: 'qwen', ...over })

describe('endpoints', () => {
  it('reads only well-formed entries from settings', () => {
    expect(readEndpoints({})).toEqual([])
    expect(readEndpoints({ endpoints: 'nope' })).toEqual([])
    expect(readEndpoints({ endpoints: [null, 3, { name: 'a', base_url: 'http://x' }] })).toEqual([{ name: 'a', base_url: 'http://x', api_key: '', default_model: '' }])
  })
  it('validates required fields, URL scheme and duplicate names', () => {
    expect(validateEndpoint(ep(), [], -1)).toBeNull()
    expect(validateEndpoint(ep({ name: ' ' }), [], -1)).toMatch(/name/)
    expect(validateEndpoint(ep({ base_url: 'localhost:1234' }), [], -1)).toMatch(/URL/)
    expect(validateEndpoint(ep({ base_url: 'ftp://x' }), [], -1)).toMatch(/http/)
    expect(validateEndpoint(ep({ default_model: '' }), [], -1)).toMatch(/model/)
    expect(validateEndpoint(ep({ name: 'LM' }), [ep()], -1)).toMatch(/already/)
    expect(validateEndpoint(ep(), [ep()], 0)).toBeNull() // editing itself is fine
  })
  it('trims and strips trailing slashes', () => {
    expect(cleanEndpoint(ep({ name: ' lm ', base_url: ' http://h/v1// ' })).base_url).toBe('http://h/v1')
  })
})

const task = (id: string, status: KanbanTask['status'], priority = 0, title = id): KanbanTask => ({ id, title, status, priority })

describe('kanban', () => {
  it('groups by column, highest priority first, and hides archived tasks', () => {
    const g = groupKanban([task('a', 'todo', 1), task('b', 'todo', 5), task('c', 'archived'), task('d', 'done')])
    expect(g.todo.map((t) => t.id)).toEqual(['b', 'a'])
    expect(g.done.map((t) => t.id)).toEqual(['d'])
    expect(Object.values(g).flat().some((t) => t.id === 'c')).toBe(false)
  })
  it('offers sensible actions per status', () => {
    expect(kanbanActions('running').map((a) => a.action)).toEqual(['stop', 'complete'])
    expect(kanbanActions('blocked').map((a) => a.action)).toContain('unblock')
    expect(kanbanActions('archived')).toEqual([])
  })
})

describe('projects', () => {
  it('computes progress, including empty projects', () => {
    expect(projectProgress({ id: '1', name: 'p', tasks: [] })).toEqual({ done: 0, total: 0, percent: 0 })
    const p = { id: '1', name: 'p', tasks: [{ id: 'a', title: 'a', status: 'completed' }, { id: 'b', title: 'b', status: 'in_progress' }, { id: 'c', title: 'c', status: 'completed' }] }
    expect(projectProgress(p)).toEqual({ done: 2, total: 3, percent: 67 })
  })
})

describe('skills and teams', () => {
  const skill = (name: string, type: SkillItem['type'], description = ''): SkillItem => ({ id: name, name, description, source: 'user', version: '1', enabled: true, type })
  it('filters by name or description and sorts skills before commands', () => {
    const items = [skill('zeta', 'skill'), skill('help', 'command', 'show Help'), skill('alpha', 'skill', 'does PDFs')]
    expect(filterSkills(items, '').map((s) => s.name)).toEqual(['alpha', 'zeta', 'help'])
    expect(filterSkills(items, 'pdf').map((s) => s.name)).toEqual(['alpha'])
    expect(filterSkills(items, '  HELP ').map((s) => s.name)).toEqual(['help'])
  })
  it('slugs skill names like the runtime does', () => {
    expect(skillSlug('  My Cool  Skill ')).toBe('my-cool-skill')
  })
  it('parses team members', () => {
    expect(parseMembers('a: does x\n\n b \nc:')).toEqual([{ name: 'a', role: 'does x' }, { name: 'b', role: 'member' }, { name: 'c', role: 'member' }])
  })
})
