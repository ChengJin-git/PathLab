import type { PathScientistSessionSummary } from '../types/pathscientist'
import type { PathScientistTrainingProgress } from '../types/pathscientist'

export function displaySessionStatus(status?: string) {
  if (status === 'finished') return 'completed'
  return status || 'unknown'
}

export function isLiveSessionStatus(status?: string) {
  return status === 'queued' || status === 'running'
}

function finiteNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function trainingProgressRunLabel(progress?: PathScientistTrainingProgress | null) {
  const runKind = typeof progress?.run_kind === 'string' ? progress.run_kind.toLowerCase() : ''
  if (progress?.quick_check || ['quick_check', 'quick-check', 'quick_start', 'quick-start'].includes(runKind)) {
    return 'Quick start'
  }
  return 'Training'
}

export function trainingProgressEpochLabel(progress?: PathScientistTrainingProgress | null) {
  const currentEpoch = finiteNumber(progress?.current_epoch)
  if (currentEpoch === null) return ''
  const totalEpochs = finiteNumber(progress?.total_epochs)
  const epoch = totalEpochs && totalEpochs > 0 ? `Epoch ${currentEpoch}/${totalEpochs}` : `Epoch ${currentEpoch}`
  return `${trainingProgressRunLabel(progress)} · ${epoch}`
}

export function trainingProgressMetricLabels(progress?: PathScientistTrainingProgress | null) {
  const labels: string[] = []
  const currentAuc = finiteNumber(progress?.current_val_auc)
  if (currentAuc !== null) labels.push(`AUC ${currentAuc.toFixed(3)}`)
  const bestAuc = finiteNumber(progress?.best_val_auc)
  if (bestAuc !== null) labels.push(`best ${bestAuc.toFixed(3)}`)
  return labels
}

export function trainingProgressConsoleLabel(progress?: PathScientistTrainingProgress | null) {
  const epoch = trainingProgressEpochLabel(progress)
  if (!epoch) return ''
  const labels = [epoch]
  const currentAuc = finiteNumber(progress?.current_val_auc)
  if (currentAuc !== null) labels.push(`val AUC ${currentAuc.toFixed(3)}`)
  const bestAuc = finiteNumber(progress?.best_val_auc)
  if (bestAuc !== null) labels.push(`best ${bestAuc.toFixed(3)}`)
  return labels.join(' · ')
}

export function sessionIterationLabel(session?: PathScientistSessionSummary | null) {
  const rawCurrent = finiteNumber(session?.current_iteration)
  if (rawCurrent === null) return ''
  const currentIteration = rawCurrent <= 0 ? 1 : rawCurrent
  const maxIterations = finiteNumber(session?.max_iterations)
  return maxIterations && maxIterations > 0
    ? `Iter ${currentIteration}/${maxIterations}`
    : `Iter ${currentIteration}`
}

export function sessionTrainingProgressLabel(session?: PathScientistSessionSummary | null) {
  const epoch = trainingProgressEpochLabel(session?.training_progress)
  if (!epoch) return ''
  const labels = [sessionIterationLabel(session), epoch, ...trainingProgressMetricLabels(session?.training_progress)]
  return labels.filter(Boolean).join(' · ')
}

function sessionDedupeKey(session: PathScientistSessionSummary) {
  if (session.workspace_path) return `workspace:${session.workspace_path}`
  if (session.conversation_id) return `conversation:${session.conversation_id}`
  return `session:${session.session_id}`
}

function sessionRank(session: PathScientistSessionSummary) {
  return [
    isLiveSessionStatus(session.status) ? 1 : 0,
    session.model ? 1 : 0,
    session.conversation_id ? 1 : 0,
    session.updated_at || 0,
    session.created_at || 0,
  ]
}

function isBetterSessionCandidate(
  candidate: PathScientistSessionSummary,
  current: PathScientistSessionSummary,
) {
  const nextRank = sessionRank(candidate)
  const currentRank = sessionRank(current)
  for (let index = 0; index < nextRank.length; index += 1) {
    if (nextRank[index] !== currentRank[index]) {
      return nextRank[index] > currentRank[index]
    }
  }
  return false
}

export function dedupePathScientistSessions(sessions: PathScientistSessionSummary[]) {
  const selectedByKey = new Map<string, PathScientistSessionSummary>()
  const keyOrder: string[] = []
  for (const session of sessions) {
    const key = sessionDedupeKey(session)
    const current = selectedByKey.get(key)
    if (!current) {
      selectedByKey.set(key, session)
      keyOrder.push(key)
    } else if (isBetterSessionCandidate(session, current)) {
      selectedByKey.set(key, session)
    }
  }
  return keyOrder
    .map((key) => selectedByKey.get(key))
    .filter((session): session is PathScientistSessionSummary => Boolean(session))
}

export function sessionStatusClass(status?: string) {
  switch (displaySessionStatus(status)) {
    case 'completed':
      return 'bg-emerald-50 text-emerald-700 ring-emerald-200'
    case 'failed':
      return 'bg-red-50 text-red-700 ring-red-200'
    case 'running':
      return 'bg-blue-50 text-blue-700 ring-blue-200'
    case 'queued':
      return 'bg-amber-50 text-amber-700 ring-amber-200'
    default:
      return 'bg-gray-100 text-gray-600 ring-gray-200'
  }
}
