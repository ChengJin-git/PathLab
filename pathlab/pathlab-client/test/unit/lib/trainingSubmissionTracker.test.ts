import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import {
  markTrainingSubmissionPending,
  markTrainingSubmissionCreated,
  markTrainingSubmissionFailed,
  markTrainingSubmissionCancelled,
  getTrainingSubmissionRecord,
  listTrainingSubmissionRecords,
  isTrainingSubmissionPendingTimedOut,
  clearTrainingSubmissionRecord,
  TRAINING_SUBMISSION_PENDING_TIMEOUT_MS,
} from '@renderer/lib/trainingSubmissionTracker'

beforeEach(() => {
  localStorage.clear()
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

// ---------------------------------------------------------------------------
// State transitions
// ---------------------------------------------------------------------------

describe('markTrainingSubmissionPending', () => {
  it('creates a pending record with the given taskId', () => {
    const record = markTrainingSubmissionPending('task_1')
    expect(record.taskId).toBe('task_1')
    expect(record.state).toBe('pending')
    expect(record.error).toBeUndefined()
  })

  it('stores optional taskName', () => {
    const record = markTrainingSubmissionPending('task_1', 'My Training Run')
    expect(record.taskName).toBe('My Training Run')
  })

  it('preserves createdAt when called a second time on same task', () => {
    const first = markTrainingSubmissionPending('task_1')
    vi.advanceTimersByTime(5000)
    const second = markTrainingSubmissionPending('task_1')
    expect(second.createdAt).toBe(first.createdAt)
    expect(second.updatedAt).toBeGreaterThan(first.updatedAt)
  })

  it('persists to localStorage', () => {
    markTrainingSubmissionPending('task_1')
    expect(localStorage.getItem('pathlab_training_submission_tracker_v1')).not.toBeNull()
  })
})

describe('markTrainingSubmissionCreated', () => {
  it('transitions from pending to created', () => {
    markTrainingSubmissionPending('task_1', 'Run A')
    const record = markTrainingSubmissionCreated('task_1')
    expect(record.state).toBe('created')
    expect(record.taskName).toBe('Run A')
    expect(record.error).toBeUndefined()
  })

  it('preserves createdAt from initial pending record', () => {
    const pending = markTrainingSubmissionPending('task_1')
    vi.advanceTimersByTime(3000)
    const created = markTrainingSubmissionCreated('task_1')
    expect(created.createdAt).toBe(pending.createdAt)
  })
})

describe('markTrainingSubmissionFailed', () => {
  it('sets state to failed with error message', () => {
    markTrainingSubmissionPending('task_1')
    const record = markTrainingSubmissionFailed('task_1', 'out of memory')
    expect(record.state).toBe('failed')
    expect(record.error).toBe('out of memory')
  })
})

describe('markTrainingSubmissionCancelled', () => {
  it('sets state to cancelled', () => {
    markTrainingSubmissionPending('task_1')
    const record = markTrainingSubmissionCancelled('task_1')
    expect(record.state).toBe('cancelled')
    expect(record.error).toBeUndefined()
  })

  it('stores optional cancellation reason', () => {
    markTrainingSubmissionPending('task_1')
    const record = markTrainingSubmissionCancelled('task_1', 'user cancelled')
    expect(record.error).toBe('user cancelled')
  })
})

// ---------------------------------------------------------------------------
// getTrainingSubmissionRecord
// ---------------------------------------------------------------------------

describe('getTrainingSubmissionRecord', () => {
  it('returns the record for a known task', () => {
    markTrainingSubmissionPending('task_1')
    const record = getTrainingSubmissionRecord('task_1')
    expect(record).not.toBeNull()
    expect(record?.taskId).toBe('task_1')
  })

  it('returns null for an unknown task', () => {
    expect(getTrainingSubmissionRecord('nonexistent')).toBeNull()
  })

  it('returns null for a record past retention period', () => {
    markTrainingSubmissionPending('task_1')
    vi.advanceTimersByTime(7 * 24 * 60 * 60 * 1000 + 1)
    expect(getTrainingSubmissionRecord('task_1')).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// listTrainingSubmissionRecords
// ---------------------------------------------------------------------------

describe('listTrainingSubmissionRecords', () => {
  it('returns all records when no state filter is given', () => {
    markTrainingSubmissionPending('task_1')
    markTrainingSubmissionPending('task_2')
    markTrainingSubmissionCreated('task_2')
    const records = listTrainingSubmissionRecords()
    expect(records).toHaveLength(2)
  })

  it('filters by state', () => {
    markTrainingSubmissionPending('task_1')
    markTrainingSubmissionPending('task_2')
    markTrainingSubmissionCreated('task_2')
    const pendingRecords = listTrainingSubmissionRecords(['pending'])
    expect(pendingRecords).toHaveLength(1)
    expect(pendingRecords[0].taskId).toBe('task_1')
  })

  it('returns multiple matching states', () => {
    markTrainingSubmissionPending('task_1')
    markTrainingSubmissionFailed('task_1', 'error')
    markTrainingSubmissionPending('task_2')
    markTrainingSubmissionCancelled('task_2')
    const records = listTrainingSubmissionRecords(['failed', 'cancelled'])
    expect(records).toHaveLength(2)
  })

  it('returns records sorted by updatedAt descending', () => {
    markTrainingSubmissionPending('task_1')
    vi.advanceTimersByTime(1000)
    markTrainingSubmissionPending('task_2')
    const records = listTrainingSubmissionRecords()
    expect(records[0].taskId).toBe('task_2')
    expect(records[1].taskId).toBe('task_1')
  })

  it('returns empty array when no records exist', () => {
    expect(listTrainingSubmissionRecords()).toHaveLength(0)
  })
})

// ---------------------------------------------------------------------------
// isTrainingSubmissionPendingTimedOut
// ---------------------------------------------------------------------------

describe('isTrainingSubmissionPendingTimedOut', () => {
  it('returns false for a recently created pending record', () => {
    const record = markTrainingSubmissionPending('task_1')
    expect(isTrainingSubmissionPendingTimedOut(record)).toBe(false)
  })

  it('returns true after the default timeout has elapsed', () => {
    const record = markTrainingSubmissionPending('task_1')
    vi.advanceTimersByTime(TRAINING_SUBMISSION_PENDING_TIMEOUT_MS + 1)
    expect(isTrainingSubmissionPendingTimedOut(record)).toBe(true)
  })

  it('returns false for a created (non-pending) record regardless of age', () => {
    markTrainingSubmissionPending('task_1')
    const record = markTrainingSubmissionCreated('task_1')
    vi.advanceTimersByTime(TRAINING_SUBMISSION_PENDING_TIMEOUT_MS + 1)
    expect(isTrainingSubmissionPendingTimedOut(record)).toBe(false)
  })

  it('respects a custom timeout value', () => {
    const record = markTrainingSubmissionPending('task_1')
    vi.advanceTimersByTime(5001)
    expect(isTrainingSubmissionPendingTimedOut(record, 5000)).toBe(true)
    expect(isTrainingSubmissionPendingTimedOut(record, 10000)).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// clearTrainingSubmissionRecord
// ---------------------------------------------------------------------------

describe('clearTrainingSubmissionRecord', () => {
  it('removes a record from storage', () => {
    markTrainingSubmissionPending('task_1')
    clearTrainingSubmissionRecord('task_1')
    expect(getTrainingSubmissionRecord('task_1')).toBeNull()
  })

  it('does nothing for a non-existent record', () => {
    expect(() => clearTrainingSubmissionRecord('nonexistent')).not.toThrow()
  })

  it('only removes the specified record, not others', () => {
    markTrainingSubmissionPending('task_1')
    markTrainingSubmissionPending('task_2')
    clearTrainingSubmissionRecord('task_1')
    expect(getTrainingSubmissionRecord('task_1')).toBeNull()
    expect(getTrainingSubmissionRecord('task_2')).not.toBeNull()
  })
})
