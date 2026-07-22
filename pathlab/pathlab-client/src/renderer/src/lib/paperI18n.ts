import type { TFunction } from 'i18next'
import type { PaperRunStage, PaperRunStatus, PaperStageLogEntry, TaskRole, TemplateId } from '../api/papers'

function fallbackLabel(value: string | null | undefined): string {
  if (!value) return '-'
  return value
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

export function paperStatusLabel(t: TFunction, status: PaperRunStatus | string): string {
  return t(`paperAgent.status.${status}`, { defaultValue: fallbackLabel(status) })
}

export function paperStageLabel(t: TFunction, stage: PaperRunStage | string | null | undefined): string {
  if (!stage) return '-'
  return t(`paperAgent.stage.${stage}`, { defaultValue: fallbackLabel(stage) })
}

export function paperStageDiagnosticMessage(
  t: TFunction,
  message: string | null | undefined,
): string {
  if (!message) return ''
  const rawMetricMatch = message.match(/Section\s+([A-Za-z0-9_:-]+)\s+contains raw metric-like value\s+'([^']+)'/)
  if (rawMetricMatch) {
    return t('paperAgent.diagnostics.rawMetricFinalFailure', {
      section: rawMetricMatch[1],
      value: rawMetricMatch[2],
    })
  }
  return message
}

export function paperStageLogMessage(t: TFunction, entry: PaperStageLogEntry | null | undefined): string {
  if (!entry) return ''
  const messageKey = (entry as PaperStageLogEntry & { message_key?: unknown }).message_key
  if (typeof messageKey === 'string' && messageKey) {
    return t(messageKey, { defaultValue: paperStageDiagnosticMessage(t, entry.message) })
  }
  if (entry.message && /^Stage\s+[A-Za-z0-9_:-]+\s+(?:started|completed)\.$/.test(entry.message)) {
    return ''
  }
  return paperStageDiagnosticMessage(t, entry.message)
}

export function paperTemplateTitle(t: TFunction, template: TemplateId | string | null | undefined): string {
  if (!template) return '-'
  return t(`paperAgent.templates.${template}.title`, { defaultValue: fallbackLabel(template) })
}

export function paperTemplateDescription(t: TFunction, template: TemplateId | string): string {
  return t(`paperAgent.templates.${template}.description`, { defaultValue: '' })
}

export function paperTaskRoleLabel(t: TFunction, role: TaskRole | string): string {
  return t(`paperAgent.taskRoles.${role}`, { defaultValue: fallbackLabel(role) })
}

export function paperArtifactStatusLabel(t: TFunction, status: string | null | undefined): string {
  if (!status) return '-'
  return t(`paperAgent.artifactStatus.${status}`, { defaultValue: fallbackLabel(status) })
}

export function paperCitationTypeLabel(t: TFunction, type: string): string {
  return t(`paperAgent.citations.types.${type}`, { defaultValue: type })
}

export function paperGuardLabel(t: TFunction, guard: string): string {
  return t(`paperAgent.validation.guards.${guard}`, { defaultValue: fallbackLabel(guard) })
}

export function paperGuardDescription(t: TFunction, guard: string): string {
  return t(`paperAgent.validation.guardDescriptions.${guard}`, { defaultValue: '' })
}

export function paperGuardIssueLabel(t: TFunction, code: string): string {
  return t(`paperAgent.validation.issueLabels.${code}`, { defaultValue: fallbackLabel(code) })
}

export function paperGuardIssueDescription(t: TFunction, code: string, fallback: string): string {
  return t(`paperAgent.validation.issueDescriptions.${code}`, { defaultValue: fallback })
}

export function paperValidationStatusLabel(t: TFunction, status: string | null | undefined): string {
  if (!status) return '-'
  return t(`paperAgent.validation.status.${status}`, { defaultValue: fallbackLabel(status) })
}

export function paperRegenerateStatusLabel(t: TFunction, status: string | null | undefined): string {
  if (!status) return '-'
  return t(`paperAgent.regenerate.status.${status}`, { defaultValue: fallbackLabel(status) })
}

export function paperRegenerateStepLabel(t: TFunction, step: string): string {
  return t(`paperAgent.regenerate.steps.${step}`, { defaultValue: fallbackLabel(step) })
}
