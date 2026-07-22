import { describe, expect, it } from 'vitest'
import type { TFunction } from 'i18next'
import { paperStageDiagnosticMessage, paperStageLogMessage } from '../../../src/renderer/src/lib/paperI18n'

const t = ((key: string, values?: Record<string, unknown>) =>
  `${key}:${values?.section ?? ''}:${values?.value ?? ''}`) as TFunction

describe('paperStageDiagnosticMessage', () => {
  it('maps raw metric contract errors to user-facing diagnostics', () => {
    expect(
      paperStageDiagnosticMessage(
        t,
        "Section related_work contains raw metric-like value '18.2'; use {{m:metric_key}}",
      ),
    ).toBe('paperAgent.diagnostics.rawMetricFinalFailure:related_work:18.2')
  })

  it('leaves unrelated messages unchanged', () => {
    expect(paperStageDiagnosticMessage(t, 'Stage plotting failed')).toBe('Stage plotting failed')
  })
})

describe('paperStageLogMessage', () => {
  it('uses translated public progress message keys when available', () => {
    expect(
      paperStageLogMessage(t, {
        stage: 'section_writing',
        status: 'running',
        message: 'fallback message',
        message_key: 'paperAgent.pipeline.messages.sectionMetricRetryAttempted',
      }),
    ).toBe('paperAgent.pipeline.messages.sectionMetricRetryAttempted::')
  })

  it('falls back to diagnostic message mapping for legacy stage messages', () => {
    expect(
      paperStageLogMessage(t, {
        stage: 'section_writing',
        status: 'failed',
        message: "Section related_work contains raw metric-like value '18.2'; use {{m:metric_key}}",
      }),
    ).toBe('paperAgent.diagnostics.rawMetricFinalFailure:related_work:18.2')
  })

  it('hides generic backend stage lifecycle messages', () => {
    expect(
      paperStageLogMessage(t, {
        stage: 'literature_review',
        status: 'running',
        message: 'Stage literature_review started.',
      }),
    ).toBe('')
  })
})
