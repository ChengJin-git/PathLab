import type { TFunction } from 'i18next'
import type { AutoResearchStageStatus, AutoResearchToolStatus } from './autoresearchEventSelectors'

type Translate = TFunction<'translation', undefined>

function translatedOrFallback(t: Translate, key: string, fallback: string, options?: Record<string, unknown>) {
  const translated = t(key, { defaultValue: fallback, ...options })
  return typeof translated === 'string' ? translated : fallback
}

export function autoResearchStageLabel(stage: string, t: Translate) {
  const normalized = stage || 'unknown'
  return translatedOrFallback(t, `autoResearch.stages.${normalized}`, stage || translatedOrFallback(t, 'autoResearch.common.unknown', 'unknown'))
}

export function autoResearchStatusLabel(status: string | undefined, t: Translate) {
  const normalized = status || 'unknown'
  return translatedOrFallback(t, `autoResearch.status.${normalized}`, normalized)
}

export function autoResearchStageStatusLabel(status: AutoResearchStageStatus, t: Translate) {
  return translatedOrFallback(t, `autoResearch.stageStatus.${status}`, status)
}

export function autoResearchToolStatusLabel(status: AutoResearchToolStatus, t: Translate) {
  return translatedOrFallback(t, `autoResearch.toolStatus.${status}`, status)
}

export function autoResearchIterationStatusLabel(status: string, t: Translate) {
  return translatedOrFallback(t, `autoResearch.iteration.status.${status}`, status)
}

export function autoResearchIterationLabel(iteration: number, t: Translate) {
  return translatedOrFallback(t, 'autoResearch.iteration.label', `Iter ${iteration}`, { iteration })
}

export function autoResearchRunningIterationLabel(
  currentIteration: number,
  maxIterations: number | null | undefined,
  t: Translate,
) {
  return maxIterations && maxIterations > 0
    ? translatedOrFallback(t, 'autoResearch.iteration.runningWithMax', `Iter ${currentIteration}/${maxIterations} running`, {
      current: currentIteration,
      max: maxIterations,
    })
    : translatedOrFallback(t, 'autoResearch.iteration.running', `Iter ${currentIteration} running`, {
      current: currentIteration,
    })
}

export function autoResearchVisibleEventsLabel(count: number, t: Translate) {
  return translatedOrFallback(t, 'autoResearch.executionConsole.visibleEvents', `${count} visible events`, { count })
}

export function autoResearchCountLabel(
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
