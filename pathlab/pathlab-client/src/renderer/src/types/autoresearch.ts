export interface StartAutoResearchSessionRequest {
  question: string
  mode?: 'research' | 'code'
  max_iter?: number
  metric?: string
  model?: string
  manual_approval?: boolean
  download_policy?: string | null
  data_paths?: string[]
}

export type AutoResearchSessionStatus = 'queued' | 'running' | 'completed' | 'failed' | 'interrupted'

export interface AutoResearchTrainingProgress {
  run_id?: string
  quick_check?: boolean | null
  run_kind?: string | null
  current_epoch?: number | null
  total_epochs?: number | null
  current_val_auc?: number | null
  current_val_acc?: number | null
  current_val_loss?: number | null
  best_val_auc?: number | null
  best_epoch?: number | null
  current_metrics?: Record<string, number>
  log_path?: string
  updated_at?: number
}

export interface AutoResearchSessionSummary {
  session_id: string
  conversation_id?: string
  title?: string
  title_pending?: boolean
  question: string
  username?: string | null
  model?: string
  status: AutoResearchSessionStatus | string
  stage?: string
  created_at?: number
  updated_at?: number
  workspace_path?: string
  workspace_size_bytes?: number | null
  persistence_dir?: string
  resume_available?: boolean
  event_source_version?: string
  current_iteration?: number | null
  max_iterations?: number | null
  training_progress?: AutoResearchTrainingProgress
  error?: string
}

export interface AutoResearchEvent {
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

export interface AutoResearchSessionDetail extends AutoResearchSessionSummary {
  state?: Record<string, unknown>
  events: AutoResearchEvent[]
}

export interface AutoResearchSessionListResponse {
  items: AutoResearchSessionSummary[]
}

export interface DeleteAutoResearchSessionResponse {
  session_id: string
  conversation_id?: string
  deleted: boolean
  workspace_deleted?: boolean
  workspace_path?: string
  workspace_delete_reason?: string
}
