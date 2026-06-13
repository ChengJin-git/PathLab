export interface PathScientistSkill {
  id: string
  name: string
  description?: string
}

export interface PathScientistSkillListResponse {
  items: PathScientistSkill[]
}

export interface StartPathScientistSessionRequest {
  question: string
  skill?: string
  mode?: 'research' | 'code'
  max_iter?: number
  metric?: string
  model?: string
  manual_approval?: boolean
  download_policy?: string | null
  data_paths?: string[]
}

export type PathScientistSessionStatus = 'queued' | 'running' | 'completed' | 'failed' | 'interrupted'

export interface PathScientistSessionSummary {
  session_id: string
  conversation_id?: string
  title?: string
  title_pending?: boolean
  question: string
  model: string
  status: PathScientistSessionStatus | string
  stage?: string
  created_at?: number
  updated_at?: number
  workspace_path?: string
  workspace_size_bytes?: number | null
  error?: string
}

export interface PathScientistEvent {
  /** Monotonic per-session sequence number assigned by the backend. */
  seq?: number
  kind: string
  ui_kind?: string
  ts?: number
  status?: string
  stage?: string
  iteration?: number
  severity?: 'info' | 'success' | 'warning' | 'error' | string
  summary?: string
  message?: string
  tool?: string
  exit_code?: number | null
  state?: Record<string, unknown>
  [key: string]: unknown
}

export interface PathScientistSessionDetail extends PathScientistSessionSummary {
  state?: Record<string, unknown>
  events: PathScientistEvent[]
}

export interface PathScientistSessionListResponse {
  items: PathScientistSessionSummary[]
}

export interface DeletePathScientistSessionResponse {
  session_id: string
  conversation_id?: string
  deleted: boolean
  workspace_deleted?: boolean
  workspace_path?: string
  workspace_delete_reason?: string
}
