export type LocaleKey = 'zh-CN' | 'zh-TW' | 'en'

export type HeroDemoPhase =
  | 'idle'
  | 'typing'
  | 'intent-visible'
  | 'config-visible'
  | 'run-ready'
  | 'queueing'
  | 'running'
  | 'completed'

export type WorkflowStoryStep = 'goal' | 'autoconfig' | 'evidence'

export type DemoField = {
  label: string
  value: string
  emphasized?: boolean
}

export type HeroDemoScenario = {
  prompt: string
  intent: DemoField[]
  config: DemoField[]
  splitOptions: string[]
  defaultSplit: string
  run: {
    readyLabel: string
    queueingLabel: string
    runningLabel: string
    progressTarget: number
    ctaLabel: string
  }
}

export type CapabilityCardData = {
  title: string
  description: string
  badge?: string
}

export type SolutionTabKey = 'clinician' | 'researcher' | 'institution'
