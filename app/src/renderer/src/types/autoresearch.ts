export type ResearchEffort = 'low' | 'medium' | 'high'

export interface ResearchSkill {
  name: string
  content: string
  source_url?: string | null
  package_id?: string | null
  entrypoint?: string
}

export interface ResearchSkillImport {
  skills: ResearchSkill[]
  files: { path: string; size: number }[]
  total_bytes: number
  warnings: string[]
}

export interface ResearchBudget {
  max_experiments: number
  time_budget_seconds: number
}

export interface AdvancedResearchSettings {
  max_experiments?: number
  time_budget_seconds?: number
  skills?: ResearchSkill[]
}

export interface StartAutoResearchSessionRequest {
  question: string
  language?: import('../i18n').SupportedLanguage
  dataset_ids?: string[]
  workspace_id?: string
  effort?: ResearchEffort
  advanced?: AdvancedResearchSettings
  allow_downloads?: boolean
  source_conversation_id?: string
  chat_request_id?: string
  selected_skill?: string
  library_skill_id?: string
  references?: import('../api/workbench').ResourceReference[]
  task_kind?: 'auto' | 'analysis' | 'experiment' | 'document'
  report_policy?: 'auto' | 'summary' | 'manuscript'
  research_standard?: 'standard' | 'scientific'
  enabled_connectors?: ('web_search' | 'articles')[]
}

export interface ContinueResearchRequest {
  text: string
  dataset_ids?: string[]
  additional_experiments?: number
  additional_time_seconds?: number
  replace_datasets?: boolean
  baseline_run_id?: string
  references?: import('../api/workbench').ResourceReference[]
}

export interface ResearchReportRevision {
  report: string
  outcome: string
  iteration: number
  saved_at: number
}

export type AutoResearchSessionStatus =
  | 'preparing'
  | 'queued'
  | 'running'
  | 'waiting'
  | 'pausing'
  | 'paused'
  | 'stopping'
  | 'completed'
  | 'failed'
  | 'interrupted'
  | 'blocked'

export interface ResearchRecovery {
  reason: string
  summary?: string
  next_steps?: string[]
  detail?: string
}

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
  task_kind?: 'auto' | 'analysis' | 'experiment' | 'document'
  report_policy?: 'auto' | 'summary' | 'manuscript'
  research_standard?: 'standard' | 'scientific' | null
  current_goal?: string | null
  conversation_id?: string
  chat_conversation_id?: string
  title?: string
  title_pending?: boolean
  question: string
  user_id?: string
  username?: string | null
  model?: string
  status: AutoResearchSessionStatus | string
  stage?: string
  created_at?: number
  updated_at?: number
  workspace_path?: string
  workspace_size_bytes?: number | null
  resume_available?: boolean
  current_iteration?: number | null
  max_iterations?: number | null
  training_progress?: AutoResearchTrainingProgress
  error?: string
  sequence?: number
  outcome?: 'completed' | 'partial' | 'no_result' | string
  recovery?: ResearchRecovery | null
  queue?: { limit: number; running: number; position: number; busy: boolean }
}

export interface AutoResearchEvent {
  /** Monotonic per-session sequence number assigned by the backend. */
  seq?: number
  activity_seq?: number
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
  activity?: AutoResearchEvent[]
  activity_before?: number | null
  jobs?: ResearchJob[]
  experiments?: ResearchExperiment[]
}

export interface ResearchJob {
  job_id: string
  kind: string
  status: string
  payload: Record<string, unknown>
  scheduling?: { state: string; position: number; required_vram_mb: number; reason: string; wait_seconds: number } | null
  result: {
    metrics?: Record<string, number>
    /** Number of metrics the job produced; `metrics` is a preview when larger. */
    metrics_total?: number
    artifacts?: ResearchArtifact[]
    error?: string
    log_path?: string
    registration?: Record<string, unknown>
  }
}

export interface ResearchExperiment {
  run_id: string
  experiment_name: string
  status: string
  iteration: number
  metrics: Record<string, number>
  /** Number of metrics the run produced; `metrics` is a preview when larger. */
  metrics_total?: number
  config: Record<string, unknown>
}

export interface ResearchArtifact {
  path: string
  name: string
  size?: number
  kind?: string
}
export interface ResearchDataset {
  dataset_id: string
  name: string
  data_type: string
  file_count: number
  feature_extractors?: string[]
  manifest_path?: string
}

export interface AutoResearchSessionListResponse {
  items: AutoResearchSessionSummary[]
}

export interface DeleteAutoResearchSessionResponse {
  session_id: string
  conversation_id: string
  status: string
}
