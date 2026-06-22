export type TrainingSubmissionState = 'pending' | 'created' | 'failed' | 'cancelled'

export interface TrainingSubmissionRecord {
  taskId: string
  state: TrainingSubmissionState
  taskName?: string
  dataType?: string
  error?: string
  createdAt: number
  updatedAt: number
}

const STORAGE_KEY = 'pathlab_training_submission_tracker_v1'
const RETENTION_MS = 7 * 24 * 60 * 60 * 1000
export const TRAINING_SUBMISSION_PENDING_TIMEOUT_MS = 30 * 60 * 1000

const ANALYSIS_TIMESTAMP_ID_PATTERN = /^\d{8}_\d{6}$/

function isTrainingSubmissionTaskId(taskId: string): boolean {
  return !ANALYSIS_TIMESTAMP_ID_PATTERN.test(taskId)
}

function loadStore(): Record<string, TrainingSubmissionRecord> {
  if (typeof window === 'undefined') return {}

  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    const parsed = raw ? JSON.parse(raw) as Record<string, TrainingSubmissionRecord> : {}
    const now = Date.now()
    return Object.fromEntries(
      Object.entries(parsed).filter(([, record]) => now - record.updatedAt < RETENTION_MS)
    )
  } catch {
    return {}
  }
}

function saveStore(store: Record<string, TrainingSubmissionRecord>): void {
  if (typeof window === 'undefined') return

  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(store))
  } catch {
    // Ignore storage failures — this tracker is best-effort UX only.
  }
}

function updateRecord(
  taskId: string,
  updater: (previous: TrainingSubmissionRecord | null) => TrainingSubmissionRecord
): TrainingSubmissionRecord {
  const store = loadStore()
  const next = updater(store[taskId] ?? null)
  store[taskId] = next
  saveStore(store)
  return next
}

export function markTrainingSubmissionPending(taskId: string, taskName?: string, dataType?: string): TrainingSubmissionRecord {
  const now = Date.now()
  return updateRecord(taskId, previous => ({
    taskId,
    state: 'pending',
    taskName: taskName ?? previous?.taskName,
    dataType: dataType ?? previous?.dataType,
    error: undefined,
    createdAt: previous?.createdAt ?? now,
    updatedAt: now,
  }))
}

export function markTrainingSubmissionCreated(taskId: string): TrainingSubmissionRecord {
  const now = Date.now()
  return updateRecord(taskId, previous => ({
    taskId,
    state: 'created',
    taskName: previous?.taskName,
    error: undefined,
    createdAt: previous?.createdAt ?? now,
    updatedAt: now,
  }))
}

export function markTrainingSubmissionFailed(taskId: string, error: string): TrainingSubmissionRecord {
  const now = Date.now()
  return updateRecord(taskId, previous => ({
    taskId,
    state: 'failed',
    taskName: previous?.taskName,
    error,
    createdAt: previous?.createdAt ?? now,
    updatedAt: now,
  }))
}

export function markTrainingSubmissionCancelled(taskId: string, error?: string): TrainingSubmissionRecord {
  const now = Date.now()
  return updateRecord(taskId, previous => ({
    taskId,
    state: 'cancelled',
    taskName: previous?.taskName,
    error,
    createdAt: previous?.createdAt ?? now,
    updatedAt: now,
  }))
}

export function getTrainingSubmissionRecord(taskId: string): TrainingSubmissionRecord | null {
  const store = loadStore()
  const record = store[taskId]
  if (!record) return null

  if (Date.now() - record.updatedAt >= RETENTION_MS) {
    delete store[taskId]
    saveStore(store)
    return null
  }

  return record
}

export function listTrainingSubmissionRecords(
  states?: TrainingSubmissionState[]
): TrainingSubmissionRecord[] {
  const store = loadStore()
  const allowed = states ? new Set(states) : null

  return Object.values(store)
    .filter(record => isTrainingSubmissionTaskId(record.taskId))
    .filter(record => (allowed ? allowed.has(record.state) : true))
    .sort((a, b) => b.updatedAt - a.updatedAt)
}

export function isTrainingSubmissionPendingTimedOut(
  record: TrainingSubmissionRecord,
  timeoutMs: number = TRAINING_SUBMISSION_PENDING_TIMEOUT_MS
): boolean {
  return record.state === 'pending' && Date.now() - record.updatedAt > timeoutMs
}

export function clearTrainingSubmissionRecord(taskId: string): void {
  const store = loadStore()
  if (!store[taskId]) return
  delete store[taskId]
  saveStore(store)
}
