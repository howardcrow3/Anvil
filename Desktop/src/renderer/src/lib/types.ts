export interface SessionMeta {
  id: string
  name: string
  created_at?: string
  updated_at?: string
  message_count?: number
}

export interface ModelInfo {
  id: string
  name: string
  provider: 'cloud' | 'local' | 'custom'
  status: string
  size?: string
  active: boolean
}

export type ToolStatus = 'running' | 'done' | 'error'

export type Part =
  | { type: 'text'; text: string }
  | { type: 'tool'; id: string; name: string; arguments: Record<string, unknown>; result?: string; status: ToolStatus }
  | { type: 'error'; message: string }

export interface Message {
  id: string
  role: 'user' | 'assistant' | 'system'
  parts: Part[]
}

export interface PermissionRequest {
  id: string
  toolName: string
  arguments: Record<string, unknown>
}

/** Events the runtime streams as `chat.event` notifications. */
export type ChatEvent =
  | { type: 'text_delta'; text: string }
  | { type: 'tool_call'; id: string; name: string; arguments?: Record<string, unknown> }
  | { type: 'tool_result'; id: string; content?: string; is_error?: boolean }
  | { type: 'permission_request'; request_id?: string; id?: string; tool_name?: string; name?: string; arguments?: Record<string, unknown> }
  | { type: 'compaction' }
  | { type: 'done'; stop_reason?: string; message?: string }
  | { type: 'error'; message?: string }
  | { type: string; [key: string]: unknown }

export type McpTransport = 'stdio' | 'http' | 'sse'
export type McpState = 'connected' | 'failed' | 'disabled' | 'stopped'

export interface KeyValue {
  id: string
  key: string
  value: string
}

export interface McpTool {
  name: string
  description: string
}

export interface McpServer {
  id: string
  name: string
  transport: McpTransport
  enabled: boolean
  command: string
  args: string[]
  cwd: string
  env: KeyValue[]
  url: string
  headers: KeyValue[]
  timeout: number
  status: McpState
  error: string
  tools: McpTool[]
}
