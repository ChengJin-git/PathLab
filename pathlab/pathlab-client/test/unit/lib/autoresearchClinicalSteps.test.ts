import { describe, expect, it } from 'vitest'
import { buildClinicalProgressSteps } from '@renderer/lib/autoresearchClinicalSteps'
import type { AutoResearchStageView } from '@renderer/lib/autoresearchEventSelectors'

function stage(id: string, status: AutoResearchStageView['status'], summary = ''): AutoResearchStageView {
  return {
    id,
    label: id,
    status,
    eventCount: 1,
    durationLabel: '',
    summary,
  }
}

describe('buildClinicalProgressSteps', () => {
  it('maps backend stages into four clinical steps', () => {
    const steps = buildClinicalProgressSteps([
      stage('intake', 'complete'),
      stage('grounding', 'complete', 'Identified MIL classification task'),
      stage('acquisition', 'current', 'Downloading dataset'),
      stage('execution', 'pending'),
    ])

    expect(steps).toHaveLength(4)
    expect(steps[0].status).toBe('complete')
    expect(steps[1].status).toBe('current')
    expect(steps[1].summary).toBe('Downloading dataset')
    expect(steps[2].status).toBe('pending')
  })
})
