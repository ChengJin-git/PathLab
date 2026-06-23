import type { PathScientistEvent, PathScientistSessionDetail } from '../types/pathscientist'

export type PathScientistStageStatus = 'pending' | 'current' | 'complete' | 'error'
export type PathScientistToolStatus = 'running' | 'success' | 'error' | 'info'

export const PATHSCIENTIST_STAGE_ORDER = [
  'intake',
  'grounding',
  'acquisition',
  'pre_execution_ready',
  'execution',
  'review',
  'synthesis',
  'completed',
] as const

const STAGE_LABELS: Record<string, string> = {
  intake: 'Intake',
  grounding: 'Grounding',
  acquisition: 'Acquisition',
  pre_execution_ready: 'Pre-exec',
  execution: 'Execution',
  review: 'Review',
  synthesis: 'Synthesis',
  completed: 'Completed',
}

export interface PathScientistStageView {
  id: string
  label: string
  status: PathScientistStageStatus
  eventCount: number
  durationMs?: number
  durationLabel: string
  summary?: string
}

export interface PathScientistGroundingPaperView {
  id: string
  title: string
  year?: string
  source?: string
  provider?: string
  url?: string
}

export interface PathScientistGroundingTaskProfileView {
  taskType?: string
  assetLevel?: string
  predictionTarget?: string
  organ?: string
  datasetHint?: string
}

export interface PathScientistGroundingView {
  selectedSkill: string
  route: string
  reason: string
  literatureCount: number
  baselineCount: number
  passageCount: number
  providers: string[]
  sotaStatusLabel: string
  taskProfile: PathScientistGroundingTaskProfileView
  papers: PathScientistGroundingPaperView[]
}

export interface PathScientistAcquisitionDatasetView {
  name: string
  provider: string
  access: string
}

export interface PathScientistAcquisitionPathView {
  label: string
  value: string
}

export interface PathScientistAcquisitionPlanStepView {
  id: string
  skill: string
  title: string
  isCurrent: boolean
}

export interface PathScientistDownloadProgressView {
  status: string
  datasetId: string
  provider: string
  rawRoot: string
  currentFile: string
  downloadedBytes: number
  bytesTotal: number
  currentBytes: number
  currentTotalBytes: number
  speedBps: number
  etaSeconds: number | null
  percent: number | null
  reason: string
}

export interface PathScientistAcquisitionView {
  status: string
  notes: string
  selectedDataset: PathScientistAcquisitionDatasetView | null
  datasetCandidateCount: number
  manifestPath: string
  readinessStatus: string
  missing: string[]
  paths: PathScientistAcquisitionPathView[]
  planStatus: string
  planNotes: string[]
  planSteps: PathScientistAcquisitionPlanStepView[]
  downloadProgress: PathScientistDownloadProgressView | null
  summary: string
}

export interface PathScientistToolView {
  id: string
  tool: string
  iteration: number | null
  status: PathScientistToolStatus
  summary: string
  stage: string
  events: PathScientistEvent[]
}

export interface PathScientistIterationView {
  index: number
  status: PathScientistToolStatus
  metricName?: string
  metricValue?: number
  committed?: boolean
  runId?: string
  tools: PathScientistToolView[]
}

export interface PathScientistMetricView {
  name: string
  value: number | null
  runId?: string
  source?: string
}

export interface PathScientistExternalTestView {
  runId: string
  status: string
  committed: boolean
  modelPath: string
  runDir: string
  primaryMetric: PathScientistMetricView | null
  sampleCount: number | null
  datasetName: string
}

export interface PathScientistInternalTestView {
  runId: string
  status: string
  committed: boolean
  modelPath: string
  runDir: string
  primaryMetric: PathScientistMetricView | null
  sampleCount: number | null
  coverage: number | null
  missingFeatureCount: number | null
  datasetName: string
}

export type PathScientistTaskTypeView =
  | 'patch-level classification'
  | 'slide-level classification'
  | 'slide-level survival prediction'
  | 'Not detected'

export interface PathScientistSessionMetadataView {
  taskType: PathScientistTaskTypeView
  foundationModel: string
  milMethod: string | null
}

export interface PathScientistActivityView {
  label: string
  event?: PathScientistEvent
}

export interface PathScientistRunNarrativeView {
  userRequest: string
  agentActions: string
  result: string
  brief: string
  source: 'llm' | 'fallback'
  model?: string
}

export interface PathScientistRunSummaryView {
  title: string
  status: string
  stage: string
  totalDurationMs?: number
  totalDurationLabel: string
  eventCount: number
  toolCallCount: number
  iterationCount: number
  bestMetric: PathScientistMetricView | null
  internalTest: PathScientistInternalTestView | null
  externalTest: PathScientistExternalTestView | null
  sessionMetadata: PathScientistSessionMetadataView
  currentActivityLabel: string
  narrative: PathScientistRunNarrativeView
}

export interface PathScientistExecutionView {
  stages: PathScientistStageView[]
  iterations: PathScientistIterationView[]
  toolCards: PathScientistToolView[]
  visibleEvents: PathScientistEvent[]
  debugEvents: PathScientistEvent[]
  currentActivity: PathScientistActivityView | null
  bestMetric: PathScientistMetricView | null
  targetMetric: PathScientistMetricView | null
  sessionMetadata: PathScientistSessionMetadataView
  grounding: PathScientistGroundingView | null
  acquisition: PathScientistAcquisitionView | null
  runSummary: PathScientistRunSummaryView
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function asNumber(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string' && value.trim()) {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) return parsed
  }
  return undefined
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value : value === undefined || value === null ? '' : String(value)
}

function asRecordArray(value: unknown): Record<string, unknown>[] {
  return Array.isArray(value) ? value.map(asRecord).filter((item) => Object.keys(item).length > 0) : []
}

function mergeNestedMetricRecords(
  base: Record<string, unknown>,
  overlay: Record<string, unknown>,
): Record<string, unknown> {
  const merged: Record<string, unknown> = { ...base, ...overlay }
  Object.keys(merged).forEach((key) => {
    const baseValue = asRecord(base[key])
    const overlayValue = asRecord(overlay[key])
    if (Object.keys(baseValue).length > 0 && Object.keys(overlayValue).length > 0) {
      merged[key] = { ...baseValue, ...overlayValue }
    }
  })
  return merged
}

function recordIdentity(record: Record<string, unknown>, index: number): string {
  const runId = asString(record.run_id).trim()
  if (runId) return `run:${runId}`
  const iteration = asNumber(record.iteration)
  if (typeof iteration === 'number') return `iteration:${iteration}`
  return `index:${index}`
}

function mergeStateRecord(base: Record<string, unknown>, overlay: Record<string, unknown>): Record<string, unknown> {
  const merged: Record<string, unknown> = { ...base, ...overlay }
  const baseMetrics = asRecord(base.metrics)
  const overlayMetrics = asRecord(overlay.metrics)
  if (Object.keys(baseMetrics).length > 0 || Object.keys(overlayMetrics).length > 0) {
    merged.metrics = mergeNestedMetricRecords(baseMetrics, overlayMetrics)
  }
  return merged
}

function mergeRecordHistory(baseValue: unknown, overlayValue: unknown): Record<string, unknown>[] {
  const base = asRecordArray(baseValue)
  const overlay = asRecordArray(overlayValue)
  if (base.length === 0) return overlay
  if (overlay.length === 0) return base

  const selected = new Map<string, Record<string, unknown>>()
  const order: string[] = []
  base.forEach((record, index) => {
    const key = recordIdentity(record, index)
    selected.set(key, record)
    order.push(key)
  })
  overlay.forEach((record, index) => {
    const key = recordIdentity(record, index)
    const existing = selected.get(key)
    if (existing) {
      selected.set(key, mergeStateRecord(existing, record))
    } else {
      selected.set(key, record)
      order.push(key)
    }
  })

  return order
    .map((key) => selected.get(key))
    .filter((record): record is Record<string, unknown> => Boolean(record))
}

function mergeSessionState(
  sessionState: Record<string, unknown>,
  eventState: Record<string, unknown>,
): Record<string, unknown> {
  const merged = { ...sessionState, ...eventState }
  if (sessionState.run_history || eventState.run_history) {
    merged.run_history = mergeRecordHistory(sessionState.run_history, eventState.run_history)
  }
  if (sessionState.external_test_history || eventState.external_test_history) {
    merged.external_test_history = mergeRecordHistory(sessionState.external_test_history, eventState.external_test_history)
  }
  return merged
}

function asStringList(value: unknown): string[] {
  if (Array.isArray(value)) return value.map(asString).map((item) => item.trim()).filter(Boolean)
  const text = asString(value).trim()
  return text ? text.split(',').map((item) => item.trim()).filter(Boolean) : []
}

function eventStage(event: PathScientistEvent): string {
  const explicit = asString(event.stage)
  if (explicit) return explicit
  const state = asRecord(event.state)
  const stateStage = asString(state.stage)
  if (stateStage) return stateStage
  if (event.kind.startsWith('tool_')) return 'execution'
  return ''
}

function eventIteration(event: PathScientistEvent): number | null {
  const value = asNumber(event.iteration)
  return typeof value === 'number' ? value : null
}

const ITERATION_BOUNDARY_TOOLS = new Set(['ratchet_commit', 'ratchet_revert'])

function isLiveObservationAsToolCall(event: PathScientistEvent): boolean {
  return event.kind === 'tool_call' && Object.prototype.hasOwnProperty.call(event, 'action') && event.action === null && Boolean(asString(event.tool))
}

function toolEventKind(event: PathScientistEvent): 'tool_call' | 'tool_observation' | '' {
  if (event.kind === 'tool_observation' || isLiveObservationAsToolCall(event)) return 'tool_observation'
  if (event.kind === 'tool_call') return 'tool_call'
  return ''
}

function isIterationBoundaryObservation(event: PathScientistEvent): boolean {
  return toolEventKind(event) === 'tool_observation' && ITERATION_BOUNDARY_TOOLS.has(asString(event.tool))
}

interface EffectiveIterationResolver {
  forEvent: (event: PathScientistEvent) => number | null
}

function buildEffectiveIterationResolver(
  visibleEvents: PathScientistEvent[],
  state: Record<string, unknown>,
): EffectiveIterationResolver {
  const toolEvents = visibleEvents.filter((event) => toolEventKind(event))
  const rawToolIterations = new Set(
    toolEvents
      .map(eventIteration)
      .filter((value): value is number => typeof value === 'number'),
  )
  const shouldRepairLiveStream =
    rawToolIterations.size === 1
    && rawToolIterations.has(0)
    && runHistory(state).length > 1
    && toolEvents.some(isIterationBoundaryObservation)

  if (!shouldRepairLiveStream) {
    return { forEvent: eventIteration }
  }

  const maxIterations = asNumber(state.max_iterations)
  const maxRawIteration = typeof maxIterations === 'number' && maxIterations > 0 ? maxIterations - 1 : undefined
  const repaired = new Map<PathScientistEvent, number>()
  let iteration = 0

  visibleEvents.forEach((event) => {
    if (!toolEventKind(event)) return
    repaired.set(event, iteration)
    if (isIterationBoundaryObservation(event)) {
      const nextIteration = iteration + 1
      iteration = typeof maxRawIteration === 'number' ? Math.min(nextIteration, maxRawIteration) : nextIteration
    }
  })

  return {
    forEvent(event) {
      return repaired.get(event) ?? eventIteration(event)
    },
  }
}

function runHistory(state: Record<string, unknown>): Record<string, unknown>[] {
  return Array.isArray(state.run_history) ? state.run_history.map(asRecord) : []
}

function normalizedMetricKey(value: string): string {
  return value.trim().toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '')
}

function displayMetricName(value: string): string {
  const normalized = normalizedMetricKey(value)
  const prefixPattern = /^(external|external_test|external_validation|internal|internal_test|test|validation|eval)_/
  const stripped = normalized.replace(prefixPattern, '')
  return stripped || normalized || value.trim()
}

function metricValueByKey(metrics: Record<string, unknown>, metricName: string): number | undefined {
  const normalizedName = normalizedMetricKey(metricName)
  if (!normalizedName) return undefined

  for (const [key, value] of Object.entries(metrics)) {
    if (normalizedMetricKey(key) === normalizedName) return asNumber(value)
  }

  return undefined
}

function nestedMetricValue(metrics: Record<string, unknown>, metricName: string): number | undefined {
  const splitPriority = ['test', 'eval', 'evaluation', 'validation', 'val']
  for (const split of splitPriority) {
    const value = metricValueByKey(asRecord(metrics[split]), metricName)
    if (typeof value === 'number') return value
  }

  return undefined
}

function prefixedMetricValue(metrics: Record<string, unknown>, metricName: string): number | undefined {
  const normalizedName = normalizedMetricKey(metricName)
  if (!normalizedName) return undefined
  const prefixPriority = ['test', 'eval', 'evaluation', 'validation', 'val', 'best_val', 'best_validation', 'best']
  for (const prefix of prefixPriority) {
    const value = metricValueByKey(metrics, `${prefix}_${normalizedName}`)
    if (typeof value === 'number') return value
  }

  return undefined
}

function runMetricValue(record: Record<string, unknown>, metricName: string): number | undefined {
  const explicitValue = asNumber(record.metric_value)
  if (typeof explicitValue === 'number') return explicitValue

  const metrics = asRecord(record.metrics)
  const directValue = metricValueByKey(metrics, metricName)
  if (typeof directValue === 'number') return directValue

  const nestedValue = nestedMetricValue(metrics, metricName)
  if (typeof nestedValue === 'number') return nestedValue

  return prefixedMetricValue(metrics, metricName)
}

interface IterationDisplayMapper {
  toDisplay: (raw: number | null) => number | null
}

function buildIterationDisplayMapper(
  visibleEvents: PathScientistEvent[],
  state: Record<string, unknown>,
): IterationDisplayMapper {
  const history = runHistory(state)
  const rawIterations = [
    ...visibleEvents.map(eventIteration).filter((value): value is number => typeof value === 'number'),
    ...history.map((entry) => asNumber(entry.iteration)).filter((value): value is number => typeof value === 'number'),
  ]
  const zeroBased = rawIterations.some((value) => value === 0)
  const maxIterations = asNumber(state.max_iterations)

  return {
    toDisplay(raw) {
      if (raw === null) return null
      let display = zeroBased && raw >= 0 ? raw + 1 : raw
      if (typeof maxIterations === 'number' && maxIterations > 0 && display > maxIterations) {
        display = maxIterations
      }
      return display
    },
  }
}

function eventSummary(event: PathScientistEvent): string {
  const summary = asString(event.summary)
  if (summary) return summary
  if (event.kind === 'state') {
    const status = asString(event.status)
    if (status === 'completed' || status === 'finished') return 'Session completed'
    const state = asRecord(event.state)
    const stage = asString(state.stage)
    return stage ? `Stage ${stage}` : 'State update'
  }
  if (event.kind === 'session') {
    const status = asString(event.status)
    return status ? `Session ${status}` : 'Session update'
  }
  if (event.kind.startsWith('tool_')) {
    return asString(event.tool) || event.kind
  }
  return asString(event.message) || event.kind || 'Event'
}

function eventStatus(event: PathScientistEvent): PathScientistToolStatus {
  const severity = asString(event.severity)
  if (severity === 'error') return 'error'
  const exitCode = asNumber(event.exit_code)
  if (typeof exitCode === 'number' && exitCode !== 0) return 'error'
  if (toolEventKind(event) === 'tool_observation') return 'success'
  return 'info'
}

function latestState(session: PathScientistSessionDetail | null, events: PathScientistEvent[]): Record<string, unknown> {
  const stateEvent = [...events].reverse().find((event) => event.state)
  return mergeSessionState(asRecord(session?.state), asRecord(stateEvent?.state))
}

function timestampValueMs(value: unknown): number | undefined {
  const parsed = asNumber(value)
  if (typeof parsed !== 'number') return undefined
  return Math.abs(parsed) < 1_000_000_000_000 ? parsed * 1000 : parsed
}

function eventTimeMs(event: PathScientistEvent): number | undefined {
  const value = asNumber(event.ts)
  if (typeof value !== 'number') return undefined
  return Math.abs(value) < 1_000_000_000_000 ? value * 1000 : value
}

function isPersistedSyntheticStageEvent(event: PathScientistEvent): boolean {
  return event.kind === 'stage_summary' && asString(event.source) === 'persisted_summary'
}

function isTerminalStatus(status: string | undefined): boolean {
  return ['completed', 'finished', 'failed', 'interrupted'].includes(asString(status))
}

function isSuccessTerminalStatus(status: string | undefined): boolean {
  return ['completed', 'finished'].includes(asString(status))
}

function isErrorTerminalStatus(status: string | undefined): boolean {
  return ['failed', 'interrupted'].includes(asString(status))
}

const FAILED_FINAL_REVIEW_STATUSES = new Set(['failed', 'no_finalized_run', 'error'])

function runFailed(record: Record<string, unknown>): boolean {
  if (record.committed) return false
  const exitCode = asNumber(record.exit_code)
  if (typeof exitCode === 'number' && exitCode !== 0) return true
  const metrics = asRecord(record.metrics)
  if (asString(metrics.status).trim().toLowerCase() === 'failed') return true
  return Boolean(asString(record.error).trim() || asString(record.error_type).trim())
}

function completedWorkflowFailedScientifically(state: Record<string, unknown>): boolean {
  const stage = asString(state.stage).trim().toLowerCase()
  if (!['completed', 'finished', 'synthesis', 'failed'].includes(stage)) return false
  const history = runHistory(state)
  if (history.some((record) => Boolean(record.committed))) return false
  const latestReview = asRecord(state.latest_review)
  const reviewStatus = asString(latestReview.status).trim().toLowerCase()
  const reviewDecision = asString(state.review_decision || latestReview.decision).trim().toLowerCase()
  const allRunsFailed = history.length > 0 && history.every(runFailed)
  return reviewDecision === 'enter_synthesis' && (FAILED_FINAL_REVIEW_STATUSES.has(reviewStatus) || allRunsFailed)
}

export function derivePathScientistDisplayStatus(
  session: PathScientistSessionDetail | null,
  state: Record<string, unknown>,
): string {
  if (completedWorkflowFailedScientifically(state)) return 'failed'
  return asString(session?.status)
}

function stageTimingEventTimeMs(event: PathScientistEvent): number | undefined {
  // Persisted legacy sessions synthesize evenly spaced stage_summary
  // breadcrumbs; they are useful labels, but not real timing boundaries.
  if (isPersistedSyntheticStageEvent(event)) return undefined
  return eventTimeMs(event)
}

function formatDuration(ms: number | undefined): string {
  if (typeof ms !== 'number' || !Number.isFinite(ms)) return '--'
  if (ms > 0 && ms < 1000) return '<1s'
  const totalSeconds = Math.max(0, Math.round(ms / 1000))
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60
  if (hours > 0) return `${hours}h ${minutes}m`
  if (minutes > 0) return `${minutes}m ${seconds}s`
  return `${seconds}s`
}

function buildStageTimings(
  visibleEvents: PathScientistEvent[],
  activeStage: string,
  nowMs?: number,
): Map<string, { durationMs?: number; durationLabel: string }> {
  const firstByStage = new Map<string, number>()
  const timestamps: number[] = []

  visibleEvents.forEach((event) => {
    const stage = eventStage(event)
    const timestamp = stageTimingEventTimeMs(event)
    if (!stage || typeof timestamp !== 'number') return
    if (!firstByStage.has(stage)) firstByStage.set(stage, timestamp)
    timestamps.push(timestamp)
  })

  const latestTimestamp = timestamps.length > 0 ? Math.max(...timestamps) : undefined
  const timings = new Map<string, { durationMs?: number; durationLabel: string }>()

  PATHSCIENTIST_STAGE_ORDER.forEach((stageId, index) => {
    const start = firstByStage.get(stageId)
    if (typeof start !== 'number') {
      timings.set(stageId, { durationLabel: '--' })
      return
    }

    const nextStart = PATHSCIENTIST_STAGE_ORDER
      .slice(index + 1)
      .map((nextStageId) => firstByStage.get(nextStageId))
      .find((timestamp): timestamp is number => typeof timestamp === 'number' && timestamp >= start)
    const liveEnd = stageId === activeStage && typeof nowMs === 'number' ? nowMs : undefined
    const end = nextStart ?? liveEnd ?? latestTimestamp
    const durationMs = typeof end === 'number' ? Math.max(0, end - start) : undefined
    timings.set(stageId, { durationMs, durationLabel: formatDuration(durationMs) })
  })

  return timings
}

function buildStateStageTimings(
  state: Record<string, unknown>,
  activeStage: string,
  nowMs?: number,
): Map<string, { durationMs?: number; durationLabel: string }> {
  const history = Array.isArray(state.stage_history) ? state.stage_history.map(asRecord) : []
  const durationsByStage = new Map<string, number>()

  history.forEach((entry) => {
    const stage = asString(entry.stage)
    if (!stage) return
    const durationSeconds = asNumber(entry.duration_sec)
    let durationMs = typeof durationSeconds === 'number' ? durationSeconds * 1000 : undefined
    if (typeof durationMs !== 'number') {
      const startedAt = timestampValueMs(entry.started_at)
      const endedAt = timestampValueMs(entry.ended_at)
      if (typeof startedAt === 'number' && typeof endedAt === 'number') {
        durationMs = Math.max(0, endedAt - startedAt)
      } else if (stage === activeStage && typeof startedAt === 'number' && typeof nowMs === 'number') {
        durationMs = Math.max(0, nowMs - startedAt)
      }
    }
    if (typeof durationMs !== 'number') return
    durationsByStage.set(stage, (durationsByStage.get(stage) || 0) + durationMs)
  })

  const stageStartedAt = timestampValueMs(state.stage_started_at)
  if (
    activeStage &&
    !durationsByStage.has(activeStage) &&
    typeof stageStartedAt === 'number' &&
    typeof nowMs === 'number'
  ) {
    durationsByStage.set(activeStage, Math.max(0, nowMs - stageStartedAt))
  }

  return new Map([...durationsByStage.entries()].map(([stage, durationMs]) => [
    stage,
    { durationMs, durationLabel: formatDuration(durationMs) },
  ]))
}

function stateStageHistoryTotalDurationMs(state: Record<string, unknown>): number | undefined {
  const history = Array.isArray(state.stage_history) ? state.stage_history.map(asRecord) : []
  const starts = history
    .map((entry) => timestampValueMs(entry.started_at))
    .filter((timestamp): timestamp is number => typeof timestamp === 'number')
  const ends = history
    .flatMap((entry) => [timestampValueMs(entry.ended_at), timestampValueMs(entry.started_at)])
    .filter((timestamp): timestamp is number => typeof timestamp === 'number')
  if (starts.length === 0 || ends.length === 0) return undefined
  return Math.max(0, Math.max(...ends) - Math.min(...starts))
}

function stageHistorySummary(
  stageId: string,
  status: PathScientistStageStatus,
  label: string,
  timing?: { durationMs?: number; durationLabel: string },
): string | undefined {
  if (!timing || timing.durationLabel === '--') return undefined
  if (status === 'complete') return `${label} completed in ${timing.durationLabel}.`
  if (status === 'current') return `${label} running for ${timing.durationLabel}.`
  if (status === 'error') return `${label} interrupted after ${timing.durationLabel}.`
  return stageId ? undefined : undefined
}

function acquisitionStageSummary(acquisition: PathScientistAcquisitionView | null): string | undefined {
  return acquisition?.summary || undefined
}

function buildStages(
  session: PathScientistSessionDetail | null,
  visibleEvents: PathScientistEvent[],
  state: Record<string, unknown>,
  acquisition: PathScientistAcquisitionView | null,
  nowMs?: number,
): PathScientistStageView[] {
  const eventStages = visibleEvents.map(eventStage).filter(Boolean)
  const rawStage = asString(state.stage) || session?.stage || eventStages.at(-1) || 'intake'
  const currentStage = PATHSCIENTIST_STAGE_ORDER.includes(rawStage as typeof PATHSCIENTIST_STAGE_ORDER[number])
    ? rawStage
    : eventStages.at(-1) || 'intake'
  const currentIndex = Math.max(0, PATHSCIENTIST_STAGE_ORDER.indexOf(currentStage as typeof PATHSCIENTIST_STAGE_ORDER[number]))
  const sessionStatus = derivePathScientistDisplayStatus(session, state)
  const successTerminal = isSuccessTerminalStatus(sessionStatus) || (rawStage === 'completed' && sessionStatus !== 'failed')
  const failed = isErrorTerminalStatus(sessionStatus) || rawStage === 'interrupted'
  const stageTimings = buildStageTimings(visibleEvents, successTerminal || failed ? '' : currentStage, nowMs)
  const stateStageTimings = buildStateStageTimings(state, successTerminal || failed ? '' : currentStage, nowMs)
  const latestReview = asRecord(state.latest_review)
  const reviewSummary = asString(latestReview.summary)

  return PATHSCIENTIST_STAGE_ORDER.map((id, index) => {
    const eventCount = visibleEvents.filter((event) => eventStage(event) === id).length
    let status: PathScientistStageStatus = 'pending'
    if (successTerminal || index < currentIndex) status = 'complete'
    if (!successTerminal && index === currentIndex) status = failed ? 'error' : 'current'
    const timing = stateStageTimings.get(id) || stageTimings.get(id)
    const eventSummaryText = visibleEvents.find((event) => eventStage(event) === id)?.summary as string | undefined
    const summary = eventSummaryText
      || (id === 'acquisition' ? acquisitionStageSummary(acquisition) : undefined)
      || (id === 'review' ? reviewSummary : undefined)
      || (eventCount === 0 ? stageHistorySummary(id, status, STAGE_LABELS[id], timing) : undefined)
    return {
      id,
      label: STAGE_LABELS[id],
      status,
      eventCount,
      durationMs: timing?.durationMs,
      durationLabel: timing?.durationLabel ?? '--',
      summary,
    }
  })
}

function buildToolCards(
  visibleEvents: PathScientistEvent[],
  iterationDisplay: IterationDisplayMapper,
  iterationResolver: EffectiveIterationResolver,
): PathScientistToolView[] {
  const cards: PathScientistToolView[] = []
  visibleEvents.forEach((event, index) => {
    if (toolEventKind(event) !== 'tool_call') return
    const tool = asString(event.tool) || 'tool'
    const rawIteration = iterationResolver.forEvent(event)
    const observation = visibleEvents.slice(index + 1).find((candidate) => {
      if (toolEventKind(candidate) !== 'tool_observation') return false
      if (asString(candidate.tool) !== tool) return false
      return iterationResolver.forEvent(candidate) === rawIteration
    })
    const status = observation ? eventStatus(observation) : 'running'
    const iteration = iterationDisplay.toDisplay(rawIteration)
    cards.push({
      id: `${iteration ?? 'pre'}:${tool}:${index}`,
      tool,
      iteration,
      status,
      summary: observation ? eventSummary(observation) : eventSummary(event),
      stage: eventStage(event) || 'execution',
      events: observation ? [event, observation] : [event],
    })
  })
  return cards
}

function buildIterations(
  state: Record<string, unknown>,
  toolCards: PathScientistToolView[],
  iterationDisplay: IterationDisplayMapper,
): PathScientistIterationView[] {
  const byIndex = new Map<number, PathScientistIterationView>()
  const objective = asRecord(state.objective)
  const objectiveMetricName = asString(objective.success_metric)
  toolCards.forEach((tool) => {
    if (tool.iteration === null) return
    const existing = byIndex.get(tool.iteration) || { index: tool.iteration, status: 'info' as const, tools: [] }
    existing.tools.push(tool)
    if (tool.status === 'error') existing.status = 'error'
    else if (existing.status !== 'error' && tool.status === 'running') existing.status = 'running'
    byIndex.set(tool.iteration, existing)
  })

  runHistory(state).forEach((record) => {
    const index = iterationDisplay.toDisplay(asNumber(record.iteration) ?? null)
    if (index === null) return
    const existing = byIndex.get(index) || { index, status: 'info' as const, tools: [] }
    const metricName = asString(record.metric_name) || objectiveMetricName
    existing.metricName = metricName ? displayMetricName(metricName) : existing.metricName
    const metricValue = metricName ? runMetricValue(record, metricName) : asNumber(record.metric_value)
    existing.metricValue = metricValue
    existing.committed = Boolean(record.committed)
    existing.runId = asString(record.run_id) || existing.runId
    const hasRunOutcome = typeof metricValue === 'number' || Boolean(existing.runId)
    if (hasRunOutcome || existing.status !== 'error') {
      existing.status = existing.committed ? 'success' : 'info'
    }
    byIndex.set(index, existing)
  })

  return [...byIndex.values()].sort((a, b) => a.index - b.index)
}

function inferBestRunId(state: Record<string, unknown>, metricName: string, bestValue: number): string | undefined {
  let match: string | undefined
  runHistory(state).forEach((record) => {
    const recordMetricName = asString(record.metric_name) || metricName
    const value = recordMetricName ? runMetricValue(record, recordMetricName) : undefined
    const runId = asString(record.run_id)
    if (typeof value === 'number' && runId && Math.abs(value - bestValue) < 1e-6) {
      match = runId
    }
  })
  return match
}

function buildBestMetric(state: Record<string, unknown>): PathScientistMetricView | null {
  const objective = asRecord(state.objective)
  const value = asNumber(state.best_metric_value)
  if (typeof value !== 'number' || value <= 0) return null
  const name = asString(objective.success_metric) || 'metric'
  return {
    name: displayMetricName(name),
    value,
    runId: asString(state.best_run_id) || inferBestRunId(state, name, value),
  }
}

function buildTargetMetric(state: Record<string, unknown>): PathScientistMetricView | null {
  const objective = asRecord(state.objective)
  const value = asNumber(objective.target_metric_value)
  if (typeof value !== 'number' || value <= 0) return null
  return {
    name: displayMetricName(asString(objective.success_metric) || 'metric'),
    value,
    source: asString(objective.target_source) || undefined,
  }
}

const EXTERNAL_SAMPLE_COUNT_KEYS = [
  'n_external_evaluated',
  'external_evaluated',
  'n_evaluated',
  'n_samples',
  'sample_count',
  'num_samples',
  'total_samples',
]

const EXTERNAL_METRIC_FALLBACK_KEYS = [
  'auc',
  'auroc',
  'accuracy',
  'acc',
  'c_index',
  'cindex',
  'dice',
  'f1',
  'balanced_accuracy',
]

const INTERNAL_SAMPLE_COUNT_KEYS = [
  'n',
  'n_test',
  'n_internal',
  'n_internal_test',
  'n_evaluated',
  'n_samples',
  'sample_count',
  'num_samples',
  'total_samples',
]

const INTERNAL_MISSING_FEATURE_KEYS = [
  'missing_feature_count',
  'missing_features',
  'missing_feature_total',
]

const INTERNAL_METRIC_FALLBACK_KEYS = [
  'auc',
  'auroc',
  'accuracy',
  'acc',
  'balanced_accuracy',
  'f1',
  'loss',
  'c_index',
  'cindex',
  'dice',
]

function metricFromCandidates(
  metrics: Record<string, unknown>,
  candidates: string[],
): PathScientistMetricView | null {
  const seen = new Set<string>()

  for (const key of candidates.map((candidate) => candidate.trim()).filter(Boolean)) {
    const normalized = normalizedMetricKey(key)
    if (!normalized || seen.has(normalized)) continue
    seen.add(normalized)
    const value = metricValueByKey(metrics, key)
    if (typeof value === 'number') return { name: displayMetricName(key), value }
  }

  return null
}

function metricKeyExists(metrics: Record<string, unknown>, metricName: string): boolean {
  const normalizedName = normalizedMetricKey(metricName)
  if (!normalizedName) return false
  return Object.keys(metrics).some((key) => normalizedMetricKey(key) === normalizedName)
}

function datasetDisplayName(record: Record<string, unknown>): string {
  return asString(
    record.dataset_name
    || record.datasetName
    || record.dataset
    || record.name
    || record.dataset_id
    || record.datasetId,
  ).trim()
}

function datasetNameFromContract(state: Record<string, unknown>, role: 'internal' | 'external'): string {
  const sources = [
    asRecord(asRecord(state.external_test_request).contract),
    asRecord(state.external_test_contract),
    asRecord(asRecord(state.grounding).external_test_contract),
  ]

  for (const source of sources) {
    const datasets = asRecordArray(source.datasets)
    const match = datasets.find((dataset) => asString(dataset.role).trim().toLowerCase() === role)
    const name = match ? datasetDisplayName(match) : ''
    if (name) return name
  }

  return ''
}

function internalDatasetName(state: Record<string, unknown>, record: Record<string, unknown>): string {
  const grounding = nestedGrounding(state)
  const request = asRecord(state.external_test_request)
  const candidates = [
    datasetDisplayName(record),
    datasetDisplayName(asRecord(state.selected_dataset)),
    datasetDisplayName(asRecord(grounding.selected_dataset)),
    datasetDisplayName(asRecord(state.training_data)),
    datasetDisplayName(asRecord(request.training_data)),
    datasetNameFromContract(state, 'internal'),
  ]

  return candidates.find(Boolean) || ''
}

function externalDatasetName(state: Record<string, unknown>, record: Record<string, unknown>): string {
  const request = asRecord(state.external_test_request)
  const candidates = [
    datasetDisplayName(record),
    datasetDisplayName(asRecord(state.external_test)),
    datasetDisplayName(asRecord(request.external_data)),
    datasetNameFromContract(state, 'external'),
    asString(state.external_dataset_name).trim(),
  ]

  return candidates.find(Boolean) || ''
}

function externalHistory(state: Record<string, unknown>): Record<string, unknown>[] {
  const direct = asRecordArray(state.external_test_history)
  if (direct.length > 0) return direct

  const comparison = asRecord(state.comparison_results)
  const fromComparison = asRecordArray(comparison.external_test_history)
  if (fromComparison.length > 0) return fromComparison

  const recovery = asRecord(state.recovery_metadata)
  return asRecordArray(recovery.external_test_history)
}

function externalRecordFromRunHistory(state: Record<string, unknown>): Record<string, unknown> {
  const history = runHistory(state)
  if (history.length === 0) return {}

  const recordWithExternal = (record: Record<string, unknown>): Record<string, unknown> => {
    const metrics = asRecord(record.metrics)
    const externalMetrics = asRecord(metrics.external_test)
    if (Object.keys(externalMetrics).length === 0) return {}
    const pathlab = asRecord(record.pathlab)
    const committed = Boolean(record.committed)
    return {
      run_id: asString(record.run_id).trim(),
      status: asString(record.external_test_status || record.status).trim() || (committed ? 'completed' : ''),
      committed,
      model_path: asString(record.model_path || pathlab.model_path).trim(),
      run_dir: asString(record.run_dir).trim(),
      metrics: externalMetrics,
    }
  }

  const bestRunId = asString(state.best_run_id).trim()
  if (bestRunId) {
    const best = history.find((record) => asString(record.run_id).trim() === bestRunId)
    if (best) {
      const record = recordWithExternal(best)
      if (Object.keys(record).length > 0) return record
    }
  }

  for (const record of [...history].reverse()) {
    if (!record.committed) continue
    const candidate = recordWithExternal(record)
    if (Object.keys(candidate).length > 0) return candidate
  }

  for (const record of [...history].reverse()) {
    const candidate = recordWithExternal(record)
    if (Object.keys(candidate).length > 0) return candidate
  }

  return {}
}

function latestExternalRecord(state: Record<string, unknown>): Record<string, unknown> {
  const direct = asRecord(state.external_test)
  if (Object.keys(direct).length > 0) return direct

  const history = externalHistory(state)
  if (history.length > 0) return history[history.length - 1]

  const recovery = asRecord(state.recovery_metadata)
  const recovered = asRecord(recovery.external_test)
  if (Object.keys(recovered).length > 0) return recovered

  return externalRecordFromRunHistory(state)
}

function externalSampleCount(metrics: Record<string, unknown>, record: Record<string, unknown>): number | null {
  for (const key of EXTERNAL_SAMPLE_COUNT_KEYS) {
    const value = asNumber(metrics[key] ?? record[key])
    if (typeof value === 'number' && value >= 0) return value
  }
  const coverage = asRecord(metrics.coverage)
  for (const key of EXTERNAL_SAMPLE_COUNT_KEYS) {
    const value = asNumber(coverage[key])
    if (typeof value === 'number' && value >= 0) return value
  }
  return null
}

function externalPrimaryMetric(
  metrics: Record<string, unknown>,
  objectiveMetricName: string,
): PathScientistMetricView | null {
  return metricFromCandidates(metrics, [
    objectiveMetricName,
    ...EXTERNAL_METRIC_FALLBACK_KEYS,
    ...Object.keys(metrics),
  ])
}

function buildExternalTestView(state: Record<string, unknown>): PathScientistExternalTestView | null {
  const record = latestExternalRecord(state)
  if (Object.keys(record).length === 0) return null

  const metrics = asRecord(record.metrics)
  const objective = asRecord(state.objective)
  const primaryMetric = externalPrimaryMetric(metrics, asString(objective.success_metric))
  const runId = asString(record.run_id).trim()
  const status = asString(record.status).trim()
  const modelPath = asString(record.model_path).trim()
  const runDir = asString(record.run_dir).trim()
  const hasDisplayableData = Boolean(
    runId
    || status
    || modelPath
    || runDir
    || primaryMetric
    || Object.keys(metrics).length > 0,
  )
  if (!hasDisplayableData) return null

  return {
    runId,
    status,
    committed: Boolean(record.committed),
    modelPath,
    runDir,
    datasetName: externalDatasetName(state, record),
    primaryMetric,
    sampleCount: externalSampleCount(metrics, record),
  }
}

function internalRecordFromRunHistory(state: Record<string, unknown>): Record<string, unknown> {
  const history = runHistory(state)
  if (history.length === 0) return {}

  const recordWithInternal = (record: Record<string, unknown>): Record<string, unknown> => {
    const metrics = asRecord(record.metrics)
    const explicitInternalMetrics = asRecord(metrics.internal_test)
    const testMetrics = asRecord(metrics.test)
    const internalMetrics = Object.keys(explicitInternalMetrics).length > 0 ? explicitInternalMetrics : testMetrics
    if (Object.keys(internalMetrics).length === 0) return {}
    const pathlab = asRecord(record.pathlab)
    const committed = Boolean(record.committed)
    return {
      run_id: asString(record.run_id).trim(),
      status: asString(record.status).trim() || (committed ? 'completed' : ''),
      committed,
      model_path: asString(record.model_path || pathlab.model_path).trim(),
      run_dir: asString(record.run_dir).trim(),
      metrics: {
        ...internalMetrics,
        data_coverage: metrics.data_coverage,
        split_counts: metrics.split_counts,
      },
    }
  }

  const bestRunId = asString(state.best_run_id).trim()
  if (bestRunId) {
    const best = history.find((record) => asString(record.run_id).trim() === bestRunId)
    if (best) {
      const record = recordWithInternal(best)
      if (Object.keys(record).length > 0) return record
    }
  }

  for (const record of [...history].reverse()) {
    if (!record.committed) continue
    const candidate = recordWithInternal(record)
    if (Object.keys(candidate).length > 0) return candidate
  }

  for (const record of [...history].reverse()) {
    const candidate = recordWithInternal(record)
    if (Object.keys(candidate).length > 0) return candidate
  }

  return {}
}

function internalSampleCount(metrics: Record<string, unknown>, record: Record<string, unknown>): number | null {
  for (const key of INTERNAL_SAMPLE_COUNT_KEYS) {
    const value = asNumber(metrics[key] ?? record[key])
    if (typeof value === 'number' && value >= 0) return value
  }
  const splitCounts = asRecord(metrics.split_counts)
  const splitTestCount = asNumber(splitCounts.test)
  if (typeof splitTestCount === 'number' && splitTestCount >= 0) return splitTestCount

  const dataCoverage = asRecord(metrics.data_coverage)
  const usableCounts = asRecord(dataCoverage.usable_counts)
  const usableTestCount = asNumber(usableCounts.test)
  if (typeof usableTestCount === 'number' && usableTestCount >= 0) return usableTestCount

  const rawCounts = asRecord(dataCoverage.raw_counts)
  const rawTestCount = asNumber(rawCounts.test)
  if (typeof rawTestCount === 'number' && rawTestCount >= 0) return rawTestCount

  return null
}

function internalMissingFeatureCount(metrics: Record<string, unknown>): number | null {
  for (const key of INTERNAL_MISSING_FEATURE_KEYS) {
    const value = asNumber(metrics[key])
    if (typeof value === 'number' && value >= 0) return value
  }
  const dataCoverage = asRecord(metrics.data_coverage)
  const missingFeatureCounts = asRecord(dataCoverage.missing_feature_counts)
  const testMissingCount = asNumber(missingFeatureCounts.test)
  if (typeof testMissingCount === 'number' && testMissingCount >= 0) return testMissingCount
  return null
}

function internalPrimaryMetric(
  metrics: Record<string, unknown>,
  objectiveMetricName: string,
): PathScientistMetricView | null {
  const requestedMetric = displayMetricName(objectiveMetricName)
  if (requestedMetric) {
    const value = metricValueByKey(metrics, requestedMetric)
    if (typeof value === 'number') return { name: displayMetricName(requestedMetric), value }
    if (metricKeyExists(metrics, requestedMetric)) return { name: displayMetricName(requestedMetric), value: null }
  }

  return metricFromCandidates(metrics, [
    ...INTERNAL_METRIC_FALLBACK_KEYS,
    ...Object.keys(metrics),
  ])
}

function buildInternalTestView(state: Record<string, unknown>): PathScientistInternalTestView | null {
  const record = internalRecordFromRunHistory(state)
  if (Object.keys(record).length === 0) return null

  const metrics = asRecord(record.metrics)
  const objective = asRecord(state.objective)
  const primaryMetric = internalPrimaryMetric(metrics, asString(objective.success_metric))
  const runId = asString(record.run_id).trim()
  const status = asString(record.status).trim()
  const modelPath = asString(record.model_path).trim()
  const runDir = asString(record.run_dir).trim()
  const coverage = asNumber(metrics.coverage)
  const missingFeatureCount = internalMissingFeatureCount(metrics)
  const hasDisplayableData = Boolean(
    runId
    || status
    || modelPath
    || runDir
    || primaryMetric
    || Object.keys(metrics).length > 0,
  )
  if (!hasDisplayableData) return null

  return {
    runId,
    status,
    committed: Boolean(record.committed),
    modelPath,
    runDir,
    primaryMetric,
    sampleCount: internalSampleCount(metrics, record),
    coverage: typeof coverage === 'number' ? coverage : null,
    datasetName: internalDatasetName(state, record),
    missingFeatureCount,
  }
}

function nestedGrounding(state: Record<string, unknown>): Record<string, unknown> {
  const direct = asRecord(state.grounding)
  if (Object.keys(direct).length > 0) return direct

  const agentState = asRecord(state.agent_state)
  const agentResearchSession = asRecord(agentState.research_session)
  const agentResearchGrounding = asRecord(agentResearchSession.grounding)
  if (Object.keys(agentResearchGrounding).length > 0) return agentResearchGrounding

  const persistedSummary = asRecord(state.persisted_summary)
  const researchSession = asRecord(persistedSummary.research_session)
  const researchGrounding = asRecord(researchSession.grounding)
  if (Object.keys(researchGrounding).length > 0) return researchGrounding

  return asRecord(persistedSummary.grounding)
}

function displaySotaStatus(status: string): string {
  const normalized = status.trim().toLowerCase()
  if (!normalized) return ''
  if (['cache_negative', 'miss', 'no_dataset_hint', 'no_dataset'].includes(normalized)) return 'no SOTA target found'
  if (normalized === 'disabled') return 'SOTA lookup disabled'
  if (normalized === 'error') return 'SOTA lookup error'
  if (['cache_hit', 'pwc_hit', 'fulltext_llm_hit', 'local_store_hit', 'openalex_llm_hit'].includes(normalized)) {
    return 'SOTA target found'
  }
  return status
}

function normalizeGroundingPaper(paper: Record<string, unknown>): PathScientistGroundingPaperView | null {
  const title = asString(paper.title || paper.paper_title).trim()
  if (!title) return null
  const id = asString(paper.paper_id || paper.id || paper.doi || title).trim()
  const year = asString(paper.year || paper.publication_year).trim()
  const source = asString(paper.source || paper.provider).trim()
  const provider = asString(paper.provider).trim()
  const url = asString(paper.url || paper.paper_url).trim()
  return {
    id,
    title,
    ...(year ? { year } : {}),
    ...(source ? { source } : {}),
    ...(provider && provider !== source ? { provider } : {}),
    ...(url ? { url } : {}),
  }
}

function buildGroundingView(state: Record<string, unknown>): PathScientistGroundingView | null {
  const grounding = nestedGrounding(state)
  if (Object.keys(grounding).length === 0) return null

  const profile = asRecord(grounding.task_profile)
  const papers = asRecordArray(grounding.papers)
    .map(normalizeGroundingPaper)
    .filter((paper): paper is PathScientistGroundingPaperView => paper !== null)
    .slice(0, 8)
  const baselines = asRecordArray(grounding.baselines)
  const passages = asRecordArray(grounding.passages)
  const providers = [
    ...asStringList(grounding.online_literature_providers),
    ...asStringList(grounding.online_literature_provider),
  ].filter((value, index, values) => values.indexOf(value) === index)
  const explicitCount = asNumber(grounding.online_literature_count)

  return {
    selectedSkill: asString(grounding.selected_skill).trim(),
    route: asString(grounding.route).trim(),
    reason: asString(grounding.reason).trim(),
    literatureCount: typeof explicitCount === 'number' ? explicitCount : papers.length,
    baselineCount: baselines.length,
    passageCount: passages.length,
    providers,
    sotaStatusLabel: displaySotaStatus(asString(grounding.sota_lookup_status)),
    taskProfile: {
      taskType: asString(profile.task_type).trim() || undefined,
      assetLevel: asString(profile.asset_level).trim() || undefined,
      predictionTarget: asString(profile.prediction_target).trim() || undefined,
      organ: asString(profile.organ).trim() || undefined,
      datasetHint: asString(grounding.dataset_hint_inferred || grounding.sota_dataset_used).trim() || undefined,
    },
    papers,
  }
}

function firstNonEmptyRecord(...values: unknown[]): Record<string, unknown> {
  for (const value of values) {
    const record = asRecord(value)
    if (Object.keys(record).length > 0) return record
  }
  return {}
}

function firstNonEmptyRecordArray(...values: unknown[]): Record<string, unknown>[] {
  for (const value of values) {
    const records = asRecordArray(value)
    if (records.length > 0) return records
  }
  return []
}

const ACQUISITION_PATH_KEYS = [
  'features_dir',
  'splits_file',
  'wsi_dir',
  'labels_file',
  'data_output_dir',
  'generated_features_dir',
  'manifest_path',
]

function acquisitionPaths(readiness: Record<string, unknown>, plan: Record<string, unknown>): PathScientistAcquisitionPathView[] {
  const paths: PathScientistAcquisitionPathView[] = []
  const seen = new Set<string>()
  const addPath = (label: string, value: unknown) => {
    const text = asString(value).trim()
    if (!text) return
    const key = `${label}:${text}`
    if (seen.has(key)) return
    seen.add(key)
    paths.push({ label, value: text })
  }

  ACQUISITION_PATH_KEYS.forEach((key) => addPath(key, readiness[key]))
  asRecordArray(plan.steps).forEach((step) => {
    const inputs = asRecord(step.inputs)
    const outputs = asRecord(step.outputs)
    ACQUISITION_PATH_KEYS.forEach((key) => {
      addPath(key, inputs[key])
      addPath(key, outputs[key])
    })
  })

  return paths
}

function acquisitionSummaryText(
  status: string,
  readinessStatus: string,
  missing: string[],
  planStatus: string,
  downloadProgress: PathScientistDownloadProgressView | null,
): string {
  if (downloadProgress?.status === 'downloading') {
    return `Downloading ${downloadProgress.datasetId || downloadProgress.provider || 'dataset'}.`
  }
  if (status && status !== 'none') {
    return readinessStatus ? `Acquisition ${status}: ${readinessStatus}.` : `Acquisition ${status}.`
  }
  if (readinessStatus === 'missing_data' && missing.length > 0) {
    return `Acquisition needs data: missing ${missing.join(', ')}.`
  }
  if (readinessStatus) return `Data readiness: ${readinessStatus}.`
  if (planStatus) return `Execution plan: ${planStatus}.`
  return ''
}

function buildDownloadProgressView(state: Record<string, unknown>): PathScientistDownloadProgressView | null {
  const progress = asRecord(state.download_progress)
  if (Object.keys(progress).length === 0) return null

  const downloadedBytes = asNumber(progress.downloaded_bytes) ?? 0
  const bytesTotal = asNumber(progress.bytes_total) ?? 0
  const percent = bytesTotal > 0
    ? Math.max(0, Math.min(100, Math.round((downloadedBytes / bytesTotal) * 100)))
    : null

  return {
    status: asString(progress.status).trim(),
    datasetId: asString(progress.dataset_id).trim(),
    provider: asString(progress.provider).trim(),
    rawRoot: asString(progress.raw_root).trim(),
    currentFile: asString(progress.current_file).trim(),
    downloadedBytes,
    bytesTotal,
    currentBytes: asNumber(progress.current_bytes) ?? 0,
    currentTotalBytes: asNumber(progress.current_total_bytes) ?? 0,
    speedBps: asNumber(progress.speed_bps) ?? 0,
    etaSeconds: progress.eta_seconds === null ? null : asNumber(progress.eta_seconds) ?? null,
    reason: asString(progress.reason).trim(),
    percent,
  }
}

function buildAcquisitionView(state: Record<string, unknown>): PathScientistAcquisitionView | null {
  const grounding = nestedGrounding(state)
  const selectedDataset = firstNonEmptyRecord(state.selected_dataset, grounding.selected_dataset)
  const candidates = firstNonEmptyRecordArray(state.dataset_candidates, grounding.dataset_candidates)
  const readiness = firstNonEmptyRecord(state.data_readiness, grounding.data_readiness)
  const plan = firstNonEmptyRecord(state.execution_plan, grounding.execution_plan)
  const status = asString(state.acquisition_status || grounding.acquisition_status).trim()
  const notes = asString(state.acquisition_notes || grounding.acquisition_notes).trim()
  const manifestPath = asString(state.dataset_manifest_path || grounding.dataset_manifest_path).trim()
  const readinessStatus = asString(readiness.status).trim()
  const planStatus = asString(plan.status).trim()
  const missing = asStringList(readiness.missing || plan.missing)
  const currentStep = asNumber(plan.current_step) ?? 0
  const downloadProgress = buildDownloadProgressView(state)
  const planSteps = asRecordArray(plan.steps).map((step, index) => {
    const skill = asString(step.skill).trim()
    const title = asString(step.title).trim() || skill || `Step ${index + 1}`
    return {
      id: asString(step.id).trim() || `${skill || 'step'}-${index + 1}`,
      skill,
      title,
      isCurrent: index === currentStep,
    }
  })
  const hasAcquisitionData = Boolean(
    status
    || notes
    || manifestPath
    || readinessStatus
    || planStatus
    || Object.keys(selectedDataset).length > 0
    || candidates.length > 0
    || planSteps.length > 0
    || downloadProgress !== null
  )
  if (!hasAcquisitionData) return null

  const datasetName = asString(selectedDataset.name || selectedDataset.dataset || selectedDataset.dataset_id).trim()
  const provider = asString(selectedDataset.provider).trim()
  const access = asString(selectedDataset.access || selectedDataset.access_type).trim()

  return {
    status,
    notes,
    selectedDataset: datasetName ? { name: datasetName, provider, access } : null,
    datasetCandidateCount: candidates.length,
    manifestPath,
    readinessStatus,
    missing,
    paths: acquisitionPaths(readiness, plan),
    planStatus,
    planNotes: asStringList(plan.notes),
    planSteps,
    downloadProgress,
    summary: acquisitionSummaryText(status, readinessStatus, missing, planStatus, downloadProgress),
  }
}

function metadataText(value: unknown): string {
  if (value === undefined || value === null) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return ''
  }
}

function buildMetadataCorpus(
  session: PathScientistSessionDetail | null,
  state: Record<string, unknown>,
  events: PathScientistEvent[],
): string {
  const parts: string[] = [
    metadataText(session?.title),
    metadataText(session?.question),
    metadataText(state),
  ]
  events.forEach((event) => {
    parts.push(
      metadataText(event.summary),
      metadataText(event.message),
      metadataText(event.text),
      metadataText(event.tool),
      metadataText(event.action),
      metadataText(event.observation),
    )
  })
  return parts.filter(Boolean).join('\n')
}

function inferTaskType(corpus: string): PathScientistTaskTypeView {
  const text = corpus.toLowerCase()
  if (
    /slide[-_\s]?level[^.\n]{0,80}survival/.test(text) ||
    /survival[_\s-]?analysis/.test(text) ||
    /survival[^.\n]{0,80}prediction/.test(text)
  ) {
    return 'slide-level survival prediction'
  }
  if (
    /patch[_\s-]?classification/.test(text) ||
    /patch[-_\s]?level[^.\n]{0,80}classification/.test(text) ||
    /patch[^.\n]{0,80}classifier/.test(text)
  ) {
    return 'patch-level classification'
  }
  if (
    /mil[_\s-]?classification/.test(text) ||
    /task profile:\s*mil[_\s-]?classification\s*\/\s*slide/.test(text) ||
    /slide[-_\s]?level[^.\n]{0,80}classification/.test(text) ||
    /whole[-_\s]?slide[^.\n]{0,80}classification/.test(text) ||
    /\bwsi\b[^.\n]{0,80}\bmil\b/.test(text) ||
    /\bmil\b[^.\n]{0,80}classif/.test(text)
  ) {
    return 'slide-level classification'
  }
  return 'Not detected'
}



function explicitTaskTypeFromProfile(state: Record<string, unknown>): PathScientistTaskTypeView | null {
  const profiles = [
    asRecord(state.task_profile),
    asRecord(nestedGrounding(state).task_profile),
  ].filter((profile) => Object.keys(profile).length > 0)

  for (const profile of profiles) {
    const taskType = asString(profile.task_type || profile.taskType).trim().toLowerCase()
    const assetLevel = asString(profile.asset_level || profile.assetLevel).trim().toLowerCase()
    const predictionTarget = asString(profile.prediction_target || profile.predictionTarget).trim().toLowerCase()
    const combined = `${taskType} ${assetLevel} ${predictionTarget}`
    if (/survival|time[_\s-]?to[_\s-]?event|c[_\s-]?index/.test(combined)) {
      return 'slide-level survival prediction'
    }
    if (taskType.includes('patch') || assetLevel.includes('patch')) {
      return 'patch-level classification'
    }
    if (/mil[_\s-]?classification|wsi[_\s-]?classification|slide[_\s-]?classification|classification/.test(combined)) {
      return 'slide-level classification'
    }
  }

  return null
}

function firstPatternMatch(patterns: Array<[RegExp, string]>, corpus: string): string {
  for (const [pattern, label] of patterns) {
    if (pattern.test(corpus)) return label
  }
  return ''
}

const FOUNDATION_MODEL_PATTERNS: Array<[RegExp, string]> = [
  [/\bvirchow\s*2\b|\bvirchow2\b/i, 'Virchow2'],
  [/\bvirchow\b/i, 'Virchow'],
  [/\buni\s*2\b|\buni2\b/i, 'UNI2'],
  [/\buni\b/i, 'UNI'],
  [/\bconch\b/i, 'CONCH'],
  [/\bphikon\s*2\b|\bphikon2\b/i, 'Phikon2'],
  [/\bh[-_\s]?optimus[-_\s]?1\b|\bhoptimus1\b/i, 'H-Optimus-1'],
  [/\bh[-_\s]?optimus[-_\s]?0\b|\bhoptimus0\b/i, 'H-Optimus-0'],
  [/\bopen[-_\s]?midnight\b/i, 'OpenMidnight'],
  [/\bgpfm\b/i, 'GPFM'],
  [/\bplip\b/i, 'PLIP'],
  [/\bdinov2\b|\bdino\s*v2\b/i, 'DINOv2'],
]

const MIL_METHOD_PATTERNS: Array<[RegExp, string]> = [
  [/\bdtfd[-_\s]?mil\b/i, 'DTFD-MIL'],
  [/\btrans[-_\s]?mil\b/i, 'TransMIL'],
  [/\bab[-_\s]?mil\b/i, 'ABMIL'],
  [/\bdsmil\b/i, 'DSMIL'],
  [/\bclam\b/i, 'CLAM'],
  [/\bmean[-_\s]?mil\b/i, 'MeanMIL'],
  [/\bmax[-_\s]?mil\b/i, 'MaxMIL'],
  [/\battention[-_\s]?mil\b/i, 'AttentionMIL'],
]

const FOUNDATION_MODEL_LABELS: Record<string, string> = {
  virchow2: 'Virchow2',
  virchow: 'Virchow',
  uni2: 'UNI2',
  uni: 'UNI',
  conch: 'CONCH',
  phikon2: 'Phikon2',
  hoptimus1: 'H-Optimus-1',
  hoptimus0: 'H-Optimus-0',
  openmidnight: 'OpenMidnight',
  gpfm: 'GPFM',
  plip: 'PLIP',
  dinov2: 'DINOv2',
}

const MIL_METHOD_LABELS: Record<string, string> = {
  abmil: 'ABMIL',
  attentionmil: 'AttentionMIL',
  clam: 'CLAM',
  clamsb: 'CLAM',
  clammb: 'CLAM',
  dsmil: 'DSMIL',
  dtfd: 'DTFD-MIL',
  dtfdmil: 'DTFD-MIL',
  meanmil: 'MeanMIL',
  maxmil: 'MaxMIL',
  transmil: 'TransMIL',
}

function normalizedModelKey(value: unknown): string {
  return asString(value).trim().toLowerCase().replace(/[^a-z0-9]+/g, '')
}

function canonicalModelLabel(value: unknown, labels: Record<string, string>): string {
  const key = normalizedModelKey(value)
  return key ? labels[key] || '' : ''
}

function selectedModelLabel(selection: Record<string, unknown>, labels: Record<string, string>): string {
  const fromCanonical = canonicalModelLabel(selection.canonical, labels)
  if (fromCanonical) return fromCanonical
  const fromName = canonicalModelLabel(selection.name, labels)
  if (fromName) return fromName
  return ''
}

function selectedFoundationModel(state: Record<string, unknown>, corpus: string): string {
  const grounding = nestedGrounding(state)
  const selectedExtractor = asRecord(grounding.selected_extractor)
  const contract = asRecord(grounding.model_selection_contract)
  const contractExtractor = asRecord(contract.feature_extractor)
  return selectedModelLabel(selectedExtractor, FOUNDATION_MODEL_LABELS)
    || selectedModelLabel(contractExtractor, FOUNDATION_MODEL_LABELS)
    || firstPatternMatch(FOUNDATION_MODEL_PATTERNS, corpus)
    || 'Not detected'
}

function selectedMilMethod(state: Record<string, unknown>, corpus: string, isSlideLevel: boolean): string | null {
  if (!isSlideLevel) return null
  const grounding = nestedGrounding(state)
  const selectedMil = asRecord(grounding.selected_mil_model)
  const contract = asRecord(grounding.model_selection_contract)
  const contractMil = asRecord(contract.mil_model)
  return selectedModelLabel(selectedMil, MIL_METHOD_LABELS)
    || selectedModelLabel(contractMil, MIL_METHOD_LABELS)
    || firstPatternMatch(MIL_METHOD_PATTERNS, corpus)
    || 'Not detected'
}

function buildSessionMetadata(
  session: PathScientistSessionDetail | null,
  state: Record<string, unknown>,
  events: PathScientistEvent[],
): PathScientistSessionMetadataView {
  const corpus = buildMetadataCorpus(session, state, events)
  const taskType = explicitTaskTypeFromProfile(state) || inferTaskType(corpus)
  const isSlideLevel = taskType.startsWith('slide-level')
  return {
    taskType,
    foundationModel: selectedFoundationModel(state, corpus),
    milMethod: selectedMilMethod(state, corpus, isSlideLevel),
  }
}

function cleanNarrativeText(value: unknown): string {
  return asString(value).replace(/\s+/g, ' ').trim()
}

function iterationLabelForRunId(iterations: PathScientistIterationView[], runId?: string): string {
  if (!runId) return ''
  const match = iterations.find((iteration) => iteration.runId === runId)
  return match ? `from iteration ${match.index}` : ''
}

function formatSummaryMetric(
  metric: PathScientistMetricView | null,
  iterations: PathScientistIterationView[] = [],
): string {
  if (!metric) return ''
  const value = typeof metric.value === 'number'
    ? (metric.value >= 10 ? metric.value.toFixed(2) : metric.value.toFixed(3))
    : '--'
  const iterationLabel = iterationLabelForRunId(iterations, metric.runId)
  return `${metric.name.toUpperCase()} ${value}${iterationLabel ? ` ${iterationLabel}` : ''}`
}

function buildAgentWorkSummary(
  session: PathScientistSessionDetail | null,
  iterations: PathScientistIterationView[],
  sessionMetadata: PathScientistSessionMetadataView,
): string {
  const iterationCount = iterations.length
  const models: string[] = []
  if (sessionMetadata.foundationModel !== 'Not detected') {
    models.push(`foundation model ${sessionMetadata.foundationModel}`)
  }
  if (sessionMetadata.milMethod && sessionMetadata.milMethod !== 'Not detected') {
    models.push(`MIL method ${sessionMetadata.milMethod}`)
  }
  const agentModel = cleanNarrativeText(session?.model)
  if (agentModel) {
    models.push(`agent LLM ${agentModel}`)
  }
  const iterationText = `Ran ${iterationCount} iteration${iterationCount === 1 ? '' : 's'}.`
  const modelText = models.length > 0
    ? `Models used: ${models.join(', ')}.`
    : 'Models used: not detected.'
  return `${iterationText} ${modelText}`
}

function buildFallbackNarrative(
  session: PathScientistSessionDetail | null,
  iterations: PathScientistIterationView[],
  bestMetric: PathScientistMetricView | null,
  sessionMetadata: PathScientistSessionMetadataView,
): PathScientistRunNarrativeView {
  const title = session?.title || 'PathScientist run'
  const userRequest = cleanNarrativeText(session?.question) || 'No user request was captured for this run.'
  const agentActions = buildAgentWorkSummary(session, iterations, sessionMetadata)
  const metric = formatSummaryMetric(bestMetric, iterations)
  const result = metric
    ? `The best detected result is ${metric}.`
    : 'No best metric has been detected yet.'

  return {
    userRequest,
    agentActions,
    result,
    brief: title,
    source: 'fallback',
  }
}

function buildRunNarrative(
  session: PathScientistSessionDetail | null,
  state: Record<string, unknown>,
  iterations: PathScientistIterationView[],
  bestMetric: PathScientistMetricView | null,
  sessionMetadata: PathScientistSessionMetadataView,
): PathScientistRunNarrativeView {
  const fallback = buildFallbackNarrative(session, iterations, bestMetric, sessionMetadata)
  const persisted = asRecord(state.ui_run_summary)
  const userRequest = cleanNarrativeText(persisted.user_request ?? persisted.userRequest)
  const agentActions = buildAgentWorkSummary(session, iterations, sessionMetadata)
  const result = cleanNarrativeText(persisted.result)
  const brief = cleanNarrativeText(persisted.brief)
  const model = cleanNarrativeText(persisted.model)

  if (!userRequest && !agentActions && !result && !brief) return fallback

  return {
    userRequest: userRequest || fallback.userRequest,
    agentActions: agentActions || fallback.agentActions,
    result: result || fallback.result,
    brief: brief || fallback.brief,
    source: 'llm',
    model: model || undefined,
  }
}

function buildRunSummary(
  session: PathScientistSessionDetail | null,
  state: Record<string, unknown>,
  visibleEvents: PathScientistEvent[],
  toolCards: PathScientistToolView[],
  iterations: PathScientistIterationView[],
  bestMetric: PathScientistMetricView | null,
  internalTest: PathScientistInternalTestView | null,
  externalTest: PathScientistExternalTestView | null,
  sessionMetadata: PathScientistSessionMetadataView,
  currentActivity: PathScientistActivityView | null,
  nowMs?: number,
): PathScientistRunSummaryView {
  const timestamps = visibleEvents
    .map(eventTimeMs)
    .filter((timestamp): timestamp is number => typeof timestamp === 'number')
  const firstTimestamp = timestamps.length > 0 ? Math.min(...timestamps) : undefined
  const latestEventTimestamp = timestamps.length > 0 ? Math.max(...timestamps) : undefined
  const liveEndTimestamp = !isTerminalStatus(session?.status) && typeof nowMs === 'number' ? nowMs : undefined
  const lastTimestamp = liveEndTimestamp ?? latestEventTimestamp
  const eventTotalDurationMs = typeof firstTimestamp === 'number' && typeof lastTimestamp === 'number'
    ? Math.max(0, lastTimestamp - firstTimestamp)
    : undefined
  const totalDurationMs = stateStageHistoryTotalDurationMs(state) ?? eventTotalDurationMs

  return {
    title: session?.title || session?.question || 'PathScientist run',
    status: derivePathScientistDisplayStatus(session, state) || asString(visibleEvents.at(-1)?.status) || 'unknown',
    stage: asString(state.stage) || session?.stage || visibleEvents.map(eventStage).filter(Boolean).at(-1) || 'intake',
    totalDurationMs,
    totalDurationLabel: formatDuration(totalDurationMs),
    eventCount: visibleEvents.length,
    toolCallCount: toolCards.length,
    iterationCount: iterations.length,
    bestMetric,
    internalTest,
    externalTest,
    sessionMetadata,
    currentActivityLabel: currentActivity?.label || 'Waiting for events',
    narrative: buildRunNarrative(session, state, iterations, bestMetric, sessionMetadata),
  }
}

export function buildPathScientistExecutionView(
  session: PathScientistSessionDetail | null,
  events: PathScientistEvent[] = [],
  nowMs?: number,
): PathScientistExecutionView {
  const visibleEvents = events.filter((event) => event.kind !== 'heartbeat')
  const state = latestState(session, visibleEvents)
  const iterationDisplay = buildIterationDisplayMapper(visibleEvents, state)
  const iterationResolver = buildEffectiveIterationResolver(visibleEvents, state)
  const toolCards = buildToolCards(visibleEvents, iterationDisplay, iterationResolver)
  const current = visibleEvents.at(-1)
  const currentActivity = current ? { label: eventSummary(current), event: current } : null
  const acquisition = buildAcquisitionView(state)
  const stages = buildStages(session, visibleEvents, state, acquisition, nowMs)
  const iterations = buildIterations(state, toolCards, iterationDisplay)
  const bestMetric = buildBestMetric(state)
  const internalTest = buildInternalTestView(state)
  const externalTest = buildExternalTestView(state)
  const sessionMetadata = buildSessionMetadata(session, state, visibleEvents)
  const grounding = buildGroundingView(state)

  return {
    stages,
    iterations,
    toolCards,
    visibleEvents,
    debugEvents: events,
    currentActivity,
    bestMetric,
    targetMetric: buildTargetMetric(state),
    sessionMetadata,
    grounding,
    acquisition,
    runSummary: buildRunSummary(
      session,
      state,
      visibleEvents,
      toolCards,
      iterations,
      bestMetric,
      internalTest,
      externalTest,
      sessionMetadata,
      currentActivity,
      nowMs,
    ),
  }
}
