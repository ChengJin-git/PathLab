import type { TFunction } from 'i18next'
import type { PathScientistStageStatus, PathScientistToolStatus } from './pathscientistEventSelectors'

type Translate = TFunction<'translation', undefined>

function translatedOrFallback(t: Translate, key: string, fallback: string, options?: Record<string, unknown>) {
  const translated = t(key, { defaultValue: fallback, ...options })
  return typeof translated === 'string' ? translated : fallback
}

export function pathScientistStageLabel(stage: string, t: Translate) {
  const normalized = stage || 'unknown'
  return translatedOrFallback(t, `pathScientist.stages.${normalized}`, stage || translatedOrFallback(t, 'pathScientist.common.unknown', 'unknown'))
}

export function pathScientistStatusLabel(status: string | undefined, t: Translate) {
  const normalized = status || 'unknown'
  return translatedOrFallback(t, `pathScientist.status.${normalized}`, normalized)
}

export function pathScientistStageStatusLabel(status: PathScientistStageStatus, t: Translate) {
  return translatedOrFallback(t, `pathScientist.stageStatus.${status}`, status)
}

export function pathScientistToolStatusLabel(status: PathScientistToolStatus, t: Translate) {
  return translatedOrFallback(t, `pathScientist.toolStatus.${status}`, status)
}

export function pathScientistIterationStatusLabel(status: string, t: Translate) {
  return translatedOrFallback(t, `pathScientist.iteration.status.${status}`, status)
}

export function pathScientistIterationLabel(iteration: number, t: Translate) {
  return translatedOrFallback(t, 'pathScientist.iteration.label', `Iter ${iteration}`, { iteration })
}

export function pathScientistRunningIterationLabel(
  currentIteration: number,
  maxIterations: number | null | undefined,
  t: Translate,
) {
  return maxIterations && maxIterations > 0
    ? translatedOrFallback(t, 'pathScientist.iteration.runningWithMax', `Iter ${currentIteration}/${maxIterations} running`, {
      current: currentIteration,
      max: maxIterations,
    })
    : translatedOrFallback(t, 'pathScientist.iteration.running', `Iter ${currentIteration} running`, {
      current: currentIteration,
    })
}

export function pathScientistVisibleEventsLabel(count: number, t: Translate) {
  return translatedOrFallback(t, 'pathScientist.executionConsole.visibleEvents', `${count} visible events`, { count })
}

export function pathScientistCountLabel(
  count: number,
  singularKey: string,
  pluralKey: string,
  t: Translate,
  fallbackSingular: string,
  fallbackPlural: string,
) {
  const key = count === 1 ? singularKey : pluralKey
  const fallback = `${count} ${count === 1 ? fallbackSingular : fallbackPlural}`
  return translatedOrFallback(t, key, fallback, { count })
}
