import type { PathScientistStageView } from './pathscientistEventSelectors'

export type ClinicalStepStatus = 'pending' | 'current' | 'complete' | 'error'

export interface ClinicalProgressStep {
  id: string
  labelKey: string
  status: ClinicalStepStatus
  summary?: string
}

const STEP_STAGE_GROUPS: { id: string; labelKey: string; stages: string[] }[] = [
  { id: 'understand', labelKey: 'pathScientist.clinical.steps.understand', stages: ['intake', 'grounding'] },
  { id: 'prepare', labelKey: 'pathScientist.clinical.steps.prepare', stages: ['acquisition', 'pre_execution_ready'] },
  { id: 'run', labelKey: 'pathScientist.clinical.steps.run', stages: ['execution', 'review'] },
  { id: 'result', labelKey: 'pathScientist.clinical.steps.result', stages: ['synthesis', 'completed'] },
]

function stageRank(status: ClinicalStepStatus) {
  switch (status) {
    case 'error': return 4
    case 'current': return 3
    case 'complete': return 2
    default: return 1
  }
}

function mergeStepStatus(current: ClinicalStepStatus, next: ClinicalStepStatus): ClinicalStepStatus {
  return stageRank(next) > stageRank(current) ? next : current
}

function mapStageStatus(stage?: PathScientistStageView): ClinicalStepStatus {
  if (!stage || stage.status === 'pending') return 'pending'
  if (stage.status === 'error') return 'error'
  if (stage.status === 'current') return 'current'
  return 'complete'
}

export function buildClinicalProgressSteps(stages: PathScientistStageView[]): ClinicalProgressStep[] {
  const stageById = new Map(stages.map((stage) => [stage.id, stage]))

  const steps = STEP_STAGE_GROUPS.map((group) => {
    let status: ClinicalStepStatus = 'pending'
    let summary = ''

    for (const stageId of group.stages) {
      const stage = stageById.get(stageId)
      status = mergeStepStatus(status, mapStageStatus(stage))
      if (!summary && stage?.summary) summary = stage.summary
      if (!summary && stage?.status === 'current' && stage.durationLabel) {
        summary = stage.durationLabel
      }
    }

    return {
      id: group.id,
      labelKey: group.labelKey,
      status,
      summary,
    }
  })

  const hasCurrent = steps.some((step) => step.status === 'current')
  if (!hasCurrent) {
    const firstPendingIndex = steps.findIndex((step) => step.status === 'pending')
    if (firstPendingIndex >= 0 && steps.slice(0, firstPendingIndex).every((step) => step.status === 'complete')) {
      const allComplete = steps.every((step) => step.status === 'complete')
      if (!allComplete) {
        steps[firstPendingIndex] = { ...steps[firstPendingIndex], status: 'current' }
      }
    }
  }

  return steps
}

export function formatClinicalMetric(name?: string, value?: number | null) {
  if (!name || typeof value !== 'number' || !Number.isFinite(value)) return '—'
  const formatted = value >= 10 ? value.toFixed(2) : value.toFixed(3)
  return `${name.toUpperCase()} ${formatted}`
}

export function displayClinicalStatus(status?: string) {
  if (status === 'finished') return 'completed'
  return status || 'unknown'
}

export function isLiveClinicalStatus(status?: string) {
  return status === 'queued' || status === 'running'
}
