export type TrainingSubmissionState = 'pending' | 'created' | 'failed'

export interface TrainingSubmissionRecord {
  taskId: string
  state: TrainingSubmissionState
  taskName?: string
  error?: string
  createdAt: number
  updatedAt: number
}

const STORAGE_KEY = 'pathlab_training_submission_tracker_v1'
const RETENTION_MS = 7 * 24 * 60 * 60 * 1000

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

export function markTrainingSubmissionPending(taskId: string, taskName?: string): TrainingSubmissionRecord {
  const now = Date.now()
  return updateRecord(taskId, previous => ({
    taskId,
    state: 'pending',
    taskName: taskName ?? previous?.taskName,
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

export function clearTrainingSubmissionRecord(taskId: string): void {
  const store = loadStore()
  if (!store[taskId]) return
  delete store[taskId]
  saveStore(store)
}